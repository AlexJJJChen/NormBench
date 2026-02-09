"""One-call experiment: Article -> Units -> SG-DT.

Default prompt:
`benchmark/article2unit2structure/prompts/stage1_major_premise_extraction.md`

Because each article is processed with a single LLM call, each run stores
artifacts under a single stage directory:

- `runs/<run_id>/stage1/{meta.json,progress.json,summary.json,units.json,structured_units.json,checkpoints/*.json}`

Where:
- `units.json`: units inferred from model output (for analysis)
- `structured_units.json`: per-unit SG-DT outputs (st2.v3)
- `checkpoints/*.json`: prompt + raw response + parsed objects per article
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from rich.progress import Progress

from ...common.batching import BatchItem, BatchStateManager, utc_now
from ...common.dataset import load_article2unit2structure_dataset, input_record
from ...common.io import read_json, write_json
from ...common.llm import AsyncLLMClient, extract_final_block
from ...common.logging import get_logger
from ...common.model_config import load_model_registry, resolve_model_config


logger = get_logger(__name__, stage="normbench:article2unit2structure:oneshot")

# Dataset placeholder used in some legacy inputs to indicate missing extracted text.
MISSING_TEXT_SENTINEL = "未截取到条文"


def _bool_env(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def _maybe_extra_params(model_alias: str, enable_thinking: bool) -> Optional[Dict[str, Any]]:
    alias = (model_alias or "").lower()
    # Qwen3 supports hard switching between thinking / non-thinking mode.
    # We default to chat (non-thinking) mode for stability (avoid long `<think>` causing truncation),
    # but allow turning it on via CLI `--enable-thinking`.
    if "qwen3" in alias:
        return {"extra_body": {"enable_thinking": bool(enable_thinking)}}

    if not enable_thinking:
        return None

    if "deepseek" in alias:
        return {"extra_body": {"enable_thinking": True}}
    return None


def _default_prompt_path() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts" / "stage1_major_premise_extraction.md"


def _load_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_input(path: Path) -> List[Dict[str, Any]]:
    """Load either:
    - released NormBench dataset JSON (top-level dict with `items`)
    - legacy list-of-records JSON (top-level list)
    """

    try:
        payload = read_json(path)
    except Exception:
        payload = None

    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        items = load_article2unit2structure_dataset(path)
        return [input_record(it) for it in items]

    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    return []


def _rule_text(rec: Dict[str, Any]) -> str:
    v = rec.get("article_text")
    if isinstance(v, str) and v and MISSING_TEXT_SENTINEL not in v:
        return v
    v = rec.get("rule_text")
    if isinstance(v, str) and v and MISSING_TEXT_SENTINEL not in v:
        return v
    v = rec.get("full_article_text")
    if isinstance(v, str) and v and MISSING_TEXT_SENTINEL not in v:
        return v
    v = rec.get("article_full")
    if isinstance(v, str) and v and MISSING_TEXT_SENTINEL not in v:
        return v
    return ""


def _full_article_text(rec: Dict[str, Any], *, fallback: str) -> str:
    v = rec.get("full_article_text")
    if isinstance(v, str) and v:
        return v
    v = rec.get("article_full")
    if isinstance(v, str) and v:
        return v
    return fallback


def _build_sample_id(rec: Dict[str, Any]) -> str:
    rid = (rec.get("rule_id") or "").strip()
    if not rid:
        return ""
    raw_id = rid

    raw_bytes = raw_id.encode("utf-8", errors="ignore")
    if len(raw_bytes) <= 200:
        return raw_id
    prefix = raw_bytes[:160].decode("utf-8", errors="ignore")
    import hashlib as _hashlib

    h = _hashlib.md5(raw_bytes).hexdigest()[:8]
    return f"{prefix}|{h}"


def _build_unit_sample_id(rule_id: str, unit_id: str) -> str:
    base = f"{rule_id}|{unit_id}"
    raw_id = base

    raw_bytes = raw_id.encode("utf-8", errors="ignore")
    if len(raw_bytes) <= 220:
        return raw_id
    prefix = raw_bytes[:170].decode("utf-8", errors="ignore")
    import hashlib as _hashlib

    h = _hashlib.md5(raw_bytes).hexdigest()[:8]
    return f"{prefix}|{h}"


def _parse_final_json_array(raw: str) -> List[Dict[str, Any]]:
    content = (extract_final_block(raw) or raw).strip()
    # Some models wrap JSON in fenced code blocks: ```json ... ```
    if content.startswith("```"):
        parts = content.split("```")
        if len(parts) >= 3:
            content = parts[1].strip()
            if content.lower().startswith("json"):
                content = content[4:].strip()
    try:
        obj = json.loads(content)
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
        # Some models may output a single object instead of an array (equivalent to 1 unit).
        if isinstance(obj, dict):
            return [obj]
        return []
    except Exception:
        # Best-effort salvage for truncated JSON arrays, e.g. when completion_tokens hits the cap
        # and the model output is cut off mid-array. We try to recover as many complete dict items
        # as possible by incrementally decoding objects after a `[` that looks like a list of dicts.
        decoder = json.JSONDecoder()

        def looks_like_unit_or_struct(obj: Dict[str, Any]) -> bool:
            # One-call output commonly contains either:
            # - Unit+Structure wrapper: {unit_id, unit_text, unit_reason, structure:{...}}
            # - Direct st2.v3 object: {schema_version, rule_id, unit_id, branches, ...}
            if isinstance(obj.get("structure"), dict) and isinstance(obj.get("unit_id"), str):
                return True
            if isinstance(obj.get("schema_version"), str) and isinstance(obj.get("branches"), list):
                return True
            return False

        best: List[Dict[str, Any]] = []
        best_score = -1
        best_len = -1
        for m in re.finditer(r"\[\s*\{", content):
            start = m.start()
            i = start + 1
            items: List[Dict[str, Any]] = []
            while i < len(content):
                # Skip whitespace / commas between items.
                while i < len(content) and content[i] in " \t\r\n,":
                    i += 1
                if i >= len(content) or content[i] == "]":
                    break
                try:
                    val, j = decoder.raw_decode(content, i)
                except Exception:
                    break
                if isinstance(val, dict):
                    items.append(val)
                i = j
            score = sum(1 for it in items if looks_like_unit_or_struct(it))
            if score > best_score or (score == best_score and len(items) > best_len):
                best = items
                best_score = score
                best_len = len(items)

        if best_score > 0 and best:
            return best

        start = content.rfind("[")
        end = content.rfind("]")
        if start != -1 and end != -1 and end > start:
            try:
                obj = json.loads(content[start : end + 1])
                if isinstance(obj, list):
                    return [x for x in obj if isinstance(x, dict)]
            except Exception:
                # The last [] may belong to a nested field (e.g., effects/items). Keep falling back.
                pass
        # Final fallback: try to slice a complete {...} object (for truncated arrays or missing brackets).
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                obj = json.loads(content[start : end + 1])
                if isinstance(obj, dict):
                    return [obj]
            except Exception:
                return []
    return []


def _strict_parse_json_array(raw: str) -> Optional[List[Dict[str, Any]]]:
    """Strict JSON parsing without salvage.

    Returns None if JSON is invalid (e.g. truncated / extra trailing text).
    """

    content = (extract_final_block(raw) or raw).strip()
    if content.startswith("```"):
        parts = content.split("```")
        if len(parts) >= 3:
            content = parts[1].strip()
            if content.lower().startswith("json"):
                content = content[4:].strip()
    try:
        obj = json.loads(content)
    except Exception:
        return None
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        return [obj]
    return []


def _maybe_system_prompt(model_alias: str, *, enable_thinking: bool) -> Optional[str]:
    # 部分本地推理模型会默认输出 `<think>` 长推理，导致输出被 max_tokens 截断而拿不到 `<final>`。
    # 这里对已知模型做最小化约束：禁止输出思考过程，保证输出可被解析。
    alias = (model_alias or "").lower()
    if "qwen3" in alias and not enable_thinking:
        # Qwen3 supports thinking / non-thinking switching. When running the evaluation
        # pipeline we prefer chat mode for stability and to avoid truncation.
        return (
            "请使用非思考模式回答。/no_think\n"
            "你最终必须只输出且仅输出 1 个 `<final>...</final>` 块。\n"
            "`<final>` 内只能是完整、可解析的 JSON 数组，不要混入任何解释文本。\n"
            "禁止输出 `<think>...</think>`。\n"
        )
    return None


def _maybe_generation_overrides(*, provider: str = "") -> Dict[str, Any]:
    # For OpenAI-compatible vLLM servers, request a large completion budget so the
    # server can generate up to the remaining context window (avoids `<final>` truncation).
    #
    # NOTE: Some gateways reject over-large `max_tokens` (HTTP 400) instead of clamping.
    # Keep it large-but-reasonable; users can override via CLI `--max-tokens`.
    if str(provider or "").strip().lower() == "vllm":
        return {"max_tokens": 20000}
    return {}


def _merge_extra_params(*parts: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    merged: Dict[str, Any] = {}
    merged_extra_body: Dict[str, Any] = {}
    for p in parts:
        if not p:
            continue
        for k, v in p.items():
            if k == "extra_body" and isinstance(v, dict):
                merged_extra_body.update(v)
            else:
                merged[k] = v
    if merged_extra_body:
        merged["extra_body"] = merged_extra_body
    return merged or None


def _normalize_to_st2_objects(parsed: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Accept either:
    - st2.v3 objects directly
    - Unit+Structure wrapper: {unit_id, unit_text, unit_reason, structure:{...}}
    and normalize to a list of st2.v3 objects.
    """

    normalized: List[Dict[str, Any]] = []
    for obj in parsed:
        if not isinstance(obj, dict):
            continue
        inner = obj.get("structure")
        if isinstance(inner, dict):
            st2_obj = dict(inner)
            # Fill missing fields from wrapper if present (some models may omit them inside `structure`).
            for k in (
                "schema_version",
                "rule_id",
                "law_title",
                "article_number",
                "rule_text",
                "unit_id",
                "unit_text",
                "unit_reason",
            ):
                if k not in st2_obj and isinstance(obj.get(k), (str, bool, int, float, list, dict)):
                    st2_obj[k] = obj[k]
            normalized.append(st2_obj)
        else:
            normalized.append(obj)
    return normalized


def run(
    *,
    batch_id: str,
    runs_dir: Path,
    input_path: Path,
    limit: Optional[int],
    resume: bool,
    model_alias: str,
    model_config_path: Optional[str] = None,
    subsets: Optional[List[str]] = None,
    languages: Optional[List[str]] = None,
    temperature: float = 0.0,
    max_concurrency: int = 2,
    enable_thinking: bool = False,
    request_timeout: Optional[float] = 600.0,
    max_tokens: Optional[int] = None,
    num_shards: int = 1,
    shard_id: int = 0,
    progress: Optional[Progress] = None,
    invocation: Optional[Dict[str, Any]] = None,
) -> Path:
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在：{input_path}")

    all_records = _load_input(input_path)
    want_sub = {s for s in (subsets or []) if isinstance(s, str) and s.strip()}
    want_lang = {s for s in (languages or []) if isinstance(s, str) and s.strip()}
    if want_sub:
        all_records = [r for r in all_records if str(r.get("subset") or "") in want_sub]
    if want_lang:
        all_records = [r for r in all_records if str(r.get("language") or "") in want_lang]
    records = all_records[:limit] if limit else all_records
    if not records:
        raise ValueError(f"输入为空：{input_path}")

    batch_dir = runs_dir / batch_id

    # 单次调用 => 单 stage 目录
    stage_dir = batch_dir / "stage1"
    stage_dir.mkdir(parents=True, exist_ok=True)
    units_out = stage_dir / "units.json"
    structured_out = stage_dir / "structured_units.json"
    summary_path = stage_dir / "summary.json"

    manager = BatchStateManager(stage_dir)
    manager.ensure_structure()

    if manager.progress_path.exists() and not resume:
        raise FileExistsError(
            f"Run already exists: {stage_dir} (pass --resume to continue, or choose a new --batch)"
        )

    prompt_file = _default_prompt_path()
    if not prompt_file.is_absolute():
        prompt_file = (Path.cwd() / prompt_file).resolve()
    if not prompt_file.exists():
        raise FileNotFoundError(f"prompt 文件不存在：{prompt_file}")

    # Write a run-level meta file (used by the evaluator to infer generation settings).
    run_root = stage_dir.parent
    run_meta_path = run_root / "run_meta.json"
    if not run_meta_path.exists():
        base_url = ""
        provider = ""
        request_model = ""
        try:
            defaults, models = load_model_registry(Path(model_config_path) if model_config_path else None)
            cfg = resolve_model_config(model_alias, defaults=defaults, models=models)
            base_url = cfg.api_base
            provider = cfg.provider
            request_model = cfg.model
        except Exception:
            # Best-effort: evaluation does not require these fields.
            base_url = ""
            provider = ""
            request_model = ""

        run_meta = {
            "run_id": batch_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "task": "article2unit2structure",
            "model": model_alias,
            "request_model": request_model,
            "base_url": base_url,
            "provider": provider,
            "generation": {
                # NOTE: this is the article-level cap (not unit-level).
                # Use an explicit name to avoid ambiguity in evaluators.
                "article_limit": limit,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "request_timeout": request_timeout,
                "max_concurrency": max_concurrency,
                "enable_thinking": bool(enable_thinking),
                "prompt_path": str(prompt_file),
                "num_shards": int(num_shards),
                "shard_id": int(shard_id),
            },
            "dataset": {
                "path": str(input_path.resolve()),
            },
        }
        write_json(run_meta_path, run_meta)

    # 初始化 progress（样本粒度：article / rule_id）
    if not manager.progress_path.exists():
        items: List[BatchItem] = []
        for rec in records:
            sample_id = _build_sample_id(rec)
            if not sample_id:
                continue
            items.append(
                BatchItem(
                    sample_id=sample_id,
                    payload={
                        "rule_id": rec.get("rule_id") or "",
                    },
                    metadata={
                        "law_title": rec.get("law_title"),
                        "article_number": rec.get("article_number"),
                    },
                )
            )
        manager.init_progress(
            batch_id=batch_id,
            stage="normbench:article2unit2structure:oneshot",
            items=items,
            manifest_path=str(input_path.resolve()),
            extra_meta={
                "model_alias": model_alias,
                "prompt_path": str(prompt_file),
                **(
                    {
                        "invocation": invocation,
                        "initial_invocation": invocation,
                        "last_invocation": invocation,
                        "invocations": [invocation],
                    }
                    if invocation is not None
                    else {}
                ),
            },
            write_meta=True,
        )

    tmpl = _load_prompt(prompt_file)
    sample_ids_all = list(manager.iter_samples(("pending", "error", "running"), limit=limit))
    ns = max(1, int(num_shards))
    sid = int(shard_id)
    if sid < 0 or sid >= ns:
        raise ValueError(f"Invalid shard_id={shard_id}, must be within [0, {ns})")

    def _pick(sample_id: str) -> bool:
        h = hashlib.md5(sample_id.encode("utf-8", errors="ignore")).hexdigest()  # noqa: S324 - deterministic sharding
        return (int(h[:8], 16) % ns) == sid

    sample_ids = [s for s in sample_ids_all if _pick(s)] if ns > 1 else sample_ids_all
    if not sample_ids:
        logger.info("No pending samples (shard=%s/%s). Reusing existing outputs.", sid, ns)
        return structured_out

    # Build a full map to keep `--resume` robust even if the caller changes `--limit`.
    def _norm_rid(v: Any) -> str:
        return str(v or "").rstrip("|").strip()

    rec_map = {rec.get("rule_id"): rec for rec in all_records if isinstance(rec, dict)}
    existing_units = {r.get("rule_id"): r for r in (read_json(units_out) or [])} if units_out.exists() else {}
    existing_structured = (
        {r.get("unit_key"): r for r in (read_json(structured_out) or [])} if structured_out.exists() else {}
    )

    total_task = None
    if progress is not None:
        total_task = progress.add_task("Article→Unit→Structure (one-call)", total=len(sample_ids))

    thinking_params = _maybe_extra_params(model_alias, enable_thinking)

    async def process_one(client: AsyncLLMClient, sample_id: str, *, persist_lock: asyncio.Lock) -> None:
        checkpoint = manager.read_checkpoint(sample_id)
        if checkpoint.get("status") == "done":
            if progress is not None and total_task is not None:
                progress.advance(total_task)
            return

        manager.update_status(sample_id=sample_id, new_status="running")

        rid = (checkpoint.get("payload") or {}).get("rule_id") if isinstance(checkpoint.get("payload"), dict) else ""
        rid = (rid or "").strip()
        rec = rec_map.get(rid) or {}
        rule_text = _rule_text(rec)
        full_article_text = _full_article_text(rec, fallback=rule_text)
        if not rid or not rule_text:
            manager.update_status(sample_id=sample_id, new_status="error")
            manager.write_checkpoint(
                sample_id,
                {
                    **checkpoint,
                    "status": "error",
                    "error": "missing rule_id or rule_text",
                },
            )
            if progress is not None and total_task is not None:
                progress.advance(total_task)
            return

        input_obj = {
            "rule_id": rid,
            "law_title": rec.get("law_title") or "",
            "article_number": rec.get("article_number") or "",
            "rule_text": rule_text,
            "full_article_text": full_article_text,
        }
        prompt = tmpl.rstrip() + "\n\n" + json.dumps(input_obj, ensure_ascii=False, indent=2)
        messages = []
        system_prompt = _maybe_system_prompt(model_alias, enable_thinking=enable_thinking)
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            user_max_tokens = {"max_tokens": int(max_tokens)} if max_tokens is not None else None
            resp = await client.acomplete(
                messages=messages,
                temperature=temperature,
                extra_params=_merge_extra_params(
                    thinking_params,
                    _maybe_generation_overrides(provider=getattr(client, "provider", "")),
                    user_max_tokens,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            manager.update_status(sample_id=sample_id, new_status="error")
            manager.write_checkpoint(
                sample_id,
                {
                    **checkpoint,
                    "status": "error",
                    "error": str(exc),
                    "prompt": prompt,
                },
            )
            if progress is not None and total_task is not None:
                progress.advance(total_task)
            return

        used_resp = resp
        raw_content = resp.raw_content
        parse_source = resp.final if resp.final else raw_content
        strict_list = _strict_parse_json_array(parse_source)
        structured_list = _normalize_to_st2_objects(strict_list if strict_list is not None else _parse_final_json_array(parse_source))
        if not structured_list:
            manager.update_status(sample_id=sample_id, new_status="error")
            manager.write_checkpoint(
                sample_id,
                {
                    **checkpoint,
                    "status": "error",
                    "error": "empty/invalid JSON array parsed from model output",
                    "prompt": prompt,
                    "model_raw": {
                        "content": resp.raw_content,
                        "final": resp.final,
                        "reasoning_content": getattr(resp, "reasoning_content", None),
                        "model": resp.model,
                        "usage": resp.usage,
                    },
                },
            )
            if progress is not None and total_task is not None:
                progress.advance(total_task)
            return

        resp_meta = used_resp
        raw_content = resp_meta.raw_content

        # Derive units from the st2.v3 objects
        units: List[Dict[str, str]] = []
        for obj in structured_list:
            unit_id = obj.get("unit_id") if isinstance(obj.get("unit_id"), str) else ""
            unit_text = obj.get("unit_text") if isinstance(obj.get("unit_text"), str) else ""
            unit_reason = obj.get("unit_reason") if isinstance(obj.get("unit_reason"), str) else ""
            if not unit_id or not unit_text:
                continue
            units.append({"unit_id": unit_id, "unit_text": unit_text, "unit_reason": unit_reason})

        if not units:
            manager.update_status(sample_id=sample_id, new_status="error")
            manager.write_checkpoint(
                sample_id,
                {
                    **checkpoint,
                    "status": "error",
                    "error": "no valid units derived from parsed st2 array",
                    "prompt": prompt,
                    "model_raw": {
                        "content": raw_content,
                        "final": resp_meta.final,
                        "reasoning_content": getattr(resp_meta, "reasoning_content", None),
                        "model": resp_meta.model,
                        "usage": resp_meta.usage,
                    },
                    "parsed": structured_list,
                },
            )
            if progress is not None and total_task is not None:
                progress.advance(total_task)
            return

        stage1_record = {
            "rule_id": rid,
            "law_title": rec.get("law_title"),
            "law_title_normalized": rec.get("law_title_normalized"),
            "article_number": rec.get("article_number"),
            "clause_number": rec.get("clause_number"),
            "item_number": rec.get("item_number"),
            "rule_text": rule_text,
            "full_article_text": full_article_text,
            "units": units,
            "llm_meta": {
                "model_alias": model_alias,
                "latency_seconds": resp_meta.latency_seconds,
                "usage": resp_meta.usage,
                "model": resp_meta.model,
                "prompt_path": str(prompt_file),
                "call_mode": "one_call",
            },
        }

        # 逐 unit 的结构化结果（与参考两步流程的 unit-level 输出形态一致：unit_key + structured + llm_meta）
        unit_count = len(structured_list)
        structured_records_local: Dict[str, Dict[str, Any]] = {}
        for st2_obj in structured_list:
            unit_id = st2_obj.get("unit_id") if isinstance(st2_obj.get("unit_id"), str) else ""
            if not unit_id:
                continue
            unit_key = f"{rid}#{unit_id}"
            structured_records_local[unit_key] = {
                "unit_key": unit_key,
                "full_article_text": full_article_text,
                "structured": st2_obj,
                "llm_meta": {
                    "model_alias": model_alias,
                    "latency_seconds": resp_meta.latency_seconds,
                    "usage": resp_meta.usage,
                    "model": resp_meta.model,
                    "prompt_path": str(prompt_file),
                    "call_mode": "one_call",
                    "units_in_response": unit_count,
                },
            }

        manager.update_status(sample_id=sample_id, new_status="done")
        manager.write_checkpoint(
            sample_id,
            {
                **checkpoint,
                "status": "done",
                # Clear any previous error payload from earlier failed attempts.
                "error": None,
                "prompt": prompt,
                "model_raw": {
                    "content": raw_content,
                    "final": resp_meta.final,
                    "reasoning_content": getattr(resp_meta, "reasoning_content", None),
                    "model": resp_meta.model,
                    "usage": resp_meta.usage,
                },
                "parsed": structured_list,
                "result": {
                    "units_record": stage1_record,
                    "structured_units": list(structured_records_local.values()),
                },
            },
        )

        async with persist_lock:
            existing_units[rid] = stage1_record
            for k, v in structured_records_local.items():
                existing_structured[k] = v
            write_json(units_out, list(existing_units.values()))
            write_json(structured_out, list(existing_structured.values()))

        if progress is not None and total_task is not None:
            progress.advance(total_task)

    async def runner() -> None:
        client = AsyncLLMClient(
            model_alias,
            model_config_path=model_config_path,
            max_concurrency=max_concurrency,
            request_timeout=request_timeout,
            retries=2,
        )
        persist_lock = asyncio.Lock()
        sem = asyncio.Semaphore(max(1, max_concurrency))

        async def _task(sid: str) -> None:
            async with sem:
                await process_one(client, sid, persist_lock=persist_lock)

        try:
            await asyncio.gather(*[asyncio.create_task(_task(sid)) for sid in sample_ids])
        finally:
            await client.aclose()

    asyncio.run(runner())

    # Finalize outputs and summaries
    write_json(units_out, list(existing_units.values()))
    write_json(structured_out, list(existing_structured.values()))

    p_state = manager.load_progress() or {}
    totals = p_state.get("totals") if isinstance(p_state, dict) else {}
    summary_obj = {
        "batch_id": batch_id,
        "laws_total": len(records),
        "articles_done": int((totals or {}).get("done") or 0),
        "articles_error": int((totals or {}).get("error") or 0),
        "units_total": len(existing_structured),
        "units_path": str(units_out),
        "structured_units_path": str(structured_out),
        "updated_at": utc_now(),
    }
    write_json(summary_path, summary_obj)

    logger.info("Run complete: stage_dir=%s", stage_dir)
    return structured_out
