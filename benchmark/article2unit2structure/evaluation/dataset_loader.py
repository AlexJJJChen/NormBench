"""Stage2 dataset loader used by evaluation.

This is a minimal, self-contained loader that provides the same in-memory
objects expected by the evaluation runner:
  - Stage2Dataset
  - Stage2Sample

It supports the released NormBench dataset format:
  {
    "format_version": "...",
    "created_at": "...",
    "dataset_id": "...",
    "items": [
      {
        "input": {rule_id, law_title, article_number, rule_text, full_article_text},
        "gold": {"units": [ {unit_id, unit_text, unit_reason, branches, meta}, ... ] }
      },
      ...
    ]
  }
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Stage2Sample:
    sample_id: str
    unit_key: str
    rule_id: str
    unit_id: str
    input_prompt: str
    input_messages: List[Dict[str, str]]
    gold_obj: Dict[str, Any]
    gold_quality: Dict[str, Any]
    meta: Dict[str, Any]


@dataclass(frozen=True)
class Stage2Dataset:
    dataset_path: Path
    dataset_format_version: str
    generated_at: str
    batch_id: str
    source_run_dir: str
    prompt_template: Dict[str, Any]
    samples: List[Stage2Sample]


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def _normalize_rule_id(rule_id: str) -> str:
    return (rule_id or "").rstrip("|").strip()


def _select_fraction(samples: List[Stage2Sample], *, frac: float, seed: str) -> List[Stage2Sample]:
    if frac >= 1.0:
        return samples
    if frac <= 0.0:
        return []

    n = int(round(len(samples) * frac))
    if n <= 0:
        return []
    if n >= len(samples):
        return samples

    def score(s: Stage2Sample) -> str:
        return hashlib.sha256(f"{seed}|{s.sample_id}".encode("utf-8")).hexdigest()

    ranked = sorted(samples, key=score)
    return ranked[:n]


def load_stage2_dataset(
    path: Path,
    *,
    limit: Optional[int] = None,
    usable_only: bool = True,
    sample_frac: Optional[float] = None,
    sample_seed: str = "0",
) -> Stage2Dataset:
    dataset_path = path if path.is_absolute() else Path.cwd() / path
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))

    if not isinstance(payload, dict) or "items" not in payload:
        raise ValueError(f"Unsupported dataset format (missing top-level 'items'): {dataset_path}")

    dataset_format_version = str(payload.get("format_version") or "")
    generated_at = str(payload.get("created_at") or "")
    batch_id = str(payload.get("dataset_id") or "")

    samples: List[Stage2Sample] = []
    for it in _as_list(payload.get("items")):
        if not isinstance(it, dict):
            continue
        inp = _as_dict(it.get("input"))
        gold = _as_dict(it.get("gold"))

        rule_id = str(inp.get("rule_id") or "")
        rid_norm = _normalize_rule_id(rule_id)
        law_title = str(inp.get("law_title") or "")
        article_number = str(inp.get("article_number") or "")
        rule_text = str(inp.get("rule_text") or "")
        full_article_text = str(inp.get("full_article_text") or "")

        for u in _as_list(gold.get("units")):
            if not isinstance(u, dict):
                continue
            unit_id = str(u.get("unit_id") or "")
            unit_key = f"{rid_norm}#{unit_id}" if rid_norm and unit_id else ""
            sample_id = unit_key or f"{rid_norm}|{unit_id}"

            # Released dataset does not include a "quality" field; treat as usable.
            usable = True
            if usable_only and not usable:
                continue

            gold_obj: Dict[str, Any] = {
                "schema_version": "st2.v3",
                "rule_id": rid_norm,
                "law_title": law_title,
                "article_number": article_number,
                "rule_text": rule_text,
                "unit_id": unit_id,
                "unit_text": str(u.get("unit_text") or ""),
                "unit_reason": str(u.get("unit_reason") or ""),
                "branches": u.get("branches") if isinstance(u.get("branches"), list) else [],
                "meta": u.get("meta") if isinstance(u.get("meta"), dict) else {},
            }

            meta: Dict[str, Any] = {
                "full_article_text": full_article_text,
                "language": it.get("language"),
                "subset": it.get("subset"),
                "source_type": it.get("source_type"),
            }

            # The evaluator does not require prompt reconstruction; keep placeholders for compatibility.
            input_obj = {
                "rule_id": rid_norm,
                "law_title": law_title,
                "article_number": article_number,
                "rule_text": rule_text,
                "full_article_text": full_article_text,
                "unit_id": unit_id,
                "unit_text": gold_obj["unit_text"],
                "unit_reason": gold_obj["unit_reason"],
            }
            input_prompt = json.dumps(input_obj, ensure_ascii=False, indent=2)
            input_messages = [{"role": "user", "content": input_prompt}]

            samples.append(
                Stage2Sample(
                    sample_id=sample_id,
                    unit_key=unit_key,
                    rule_id=rid_norm,
                    unit_id=unit_id,
                    input_prompt=input_prompt,
                    input_messages=input_messages,
                    gold_obj=gold_obj,
                    gold_quality={"usable": True},
                    meta=meta,
                )
            )

    if sample_frac is not None:
        samples = _select_fraction(samples, frac=float(sample_frac), seed=str(sample_seed))
    if limit is not None:
        samples = samples[: int(limit)]

    return Stage2Dataset(
        dataset_path=dataset_path,
        dataset_format_version=dataset_format_version,
        generated_at=generated_at,
        batch_id=batch_id,
        source_run_dir="",
        prompt_template={},
        samples=samples,
    )
