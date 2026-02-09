"""Article->Unit->Structure experiment CLI (inference + evaluation)."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from ..common.env import load_repo_dotenv
from ..common.batching import ensure_timestamp_suffix, utc_now
from ..common.logging import setup_logging
from .evaluation.run_evaluation import run_evaluation as run_evaluation_impl
from .pipeline.oneshot import run as run_oneshot


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = REPO_ROOT / "dataset" / "article2unit2structure" / "normbench_v1.json"
DEFAULT_RUNS_ROOT = Path(__file__).resolve().parent / "runs"


def _progress() -> Progress:
    return Progress(
        TextColumn("{task.description}", justify="left"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("ETA"),
        TimeRemainingColumn(),
    )


def _sanitize_for_json(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_for_json(v) for v in obj]
    return str(obj)


def _build_invocation(args: argparse.Namespace, *, effective_args: Dict[str, Any]) -> Dict[str, Any]:
    parsed = {k: v for k, v in vars(args).items() if k != "func"}
    cmd = " ".join([shlex.quote(sys.executable), *[shlex.quote(a) for a in sys.argv]])
    cmd_module = " ".join(
        [
            shlex.quote(sys.executable),
            "-m",
            "benchmark.article2unit2structure",
            *[shlex.quote(a) for a in sys.argv[1:]],
        ]
    )
    return {
        "at": utc_now(),
        "cwd": str(Path.cwd()),
        "sys_executable": sys.executable,
        "argv": list(sys.argv),
        "command": cmd,
        "command_module": cmd_module,
        "cmd": getattr(args, "cmd", None),
        "parsed_args": _sanitize_for_json(parsed),
        "effective_args": _sanitize_for_json(effective_args),
    }


def _resolve_runs_dir(path: Optional[str]) -> Path:
    return Path(path) if path else DEFAULT_RUNS_ROOT


def cmd_run(args: argparse.Namespace) -> None:
    batch_id = ensure_timestamp_suffix(args.batch)
    runs_dir = _resolve_runs_dir(args.runs_dir)

    log_dir = runs_dir / batch_id / "logs"
    setup_logging(log_dir)

    dataset_path = Path(args.input_path).resolve()

    invocation = _build_invocation(
        args,
        effective_args={
            "batch_id": batch_id,
            "runs_dir": str(runs_dir),
            "input_path": str(dataset_path),
            "subsets": args.subset,
            "languages": args.language,
            "limit": args.limit,
            "resume": args.resume,
            "model_alias": args.model_alias,
            "model_config": args.model_config,
            "temperature": args.temperature,
            "max_concurrency": args.max_concurrency,
            "request_timeout": args.request_timeout,
            "enable_thinking": args.enable_thinking,
            "max_tokens": args.max_tokens,
            "num_shards": args.num_shards,
            "shard_id": args.shard_id,
        },
    )

    with _progress() as progress:
        run_oneshot(
            batch_id=batch_id,
            runs_dir=runs_dir,
            input_path=dataset_path,
            subsets=args.subset,
            languages=args.language,
            limit=args.limit,
            resume=args.resume,
            model_alias=args.model_alias,
            model_config_path=args.model_config,
            temperature=args.temperature,
            max_concurrency=args.max_concurrency,
            enable_thinking=args.enable_thinking,
            request_timeout=args.request_timeout,
            max_tokens=args.max_tokens,
            num_shards=args.num_shards,
            shard_id=args.shard_id,
            progress=progress,
            invocation=invocation,
        )


def _resolve_predictions_from_run_dir(run_dir: Path) -> Path:
    for p in [run_dir / "stage1" / "structured_units.json", run_dir / "stage2" / "structured_units.json"]:
        if p.exists():
            return p
    raise FileNotFoundError(f"structured_units.json not found under: {run_dir}")


def _load_rule_ids_from_units_json(units_path: Path) -> list[str]:
    if not units_path.exists():
        return []
    payload = json.loads(units_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    out: list[str] = []
    for r in payload:
        if not isinstance(r, dict):
            continue
        rid = r.get("rule_id")
        if isinstance(rid, str) and rid.strip():
            out.append(rid.rstrip("|").strip())
    return out


def _load_rule_ids_from_predictions(predictions_path: Path) -> list[str]:
    payload = json.loads(predictions_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    out: list[str] = []
    for r in payload:
        if not isinstance(r, dict):
            continue
        rid = r.get("rule_id")
        if not (isinstance(rid, str) and rid.strip()):
            uk = r.get("unit_key")
            if isinstance(uk, str) and "#" in uk:
                rid = uk.split("#", 1)[0]
        if isinstance(rid, str) and rid.strip():
            out.append(rid.rstrip("|").strip())
    # De-dup while keeping order (small lists anyway).
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        uniq.append(x)
    return uniq


def cmd_evaluate(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir).resolve()
    dataset_path = Path(args.dataset).resolve()

    # Match the internal runner: output under run_dir/<eval_subdir>/.
    setup_logging(run_dir / str(args.eval_subdir) / "logs")

    run_evaluation_impl(
        run_root=run_dir,
        dataset_path=dataset_path,
        stage=args.stage,
        structured_path=Path(args.structured_path).resolve() if args.structured_path else None,
        limit=args.limit,
        sample_frac=args.sample_frac,
        sample_seed=args.sample_seed,
        include_nonusable=bool(args.include_nonusable),
        strict_schema=bool(args.strict_schema),
        iou_threshold=float(args.iou_threshold),
        auto_fix_structured=bool(args.auto_fix_structured),
        fixed_structured_path=Path(args.fixed_structured_path).resolve() if args.fixed_structured_path else None,
        eval_subdir=str(args.eval_subdir),
        subset_mode=str(args.subset_mode),
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="normbench-article2unit2structure")
    sub = p.add_subparsers(dest="cmd", required=True)

    prun = sub.add_parser("run", help="Run one-call inference")
    prun.add_argument("--batch", required=True, help="run id prefix (a timestamp suffix will be appended)")
    prun.add_argument("--input-path", dest="input_path", default=str(DEFAULT_DATASET), help="input JSON path")
    prun.add_argument("--dataset", dest="input_path", help="alias for --input-path", default=None)
    prun.add_argument("--subset", action="append", default=None, help="filter dataset by subset (repeatable)")
    prun.add_argument("--language", action="append", default=None, help="filter dataset by language (repeatable)")
    prun.add_argument("--limit", type=int, default=None, help="limit number of articles (after filtering)")
    prun.add_argument("--model-alias", required=True, help="model alias in your model config")
    prun.add_argument("--model-config", default=None, help="path to model config JSON (or set NORMBENCH_MODEL_CONFIG)")
    prun.add_argument("--temperature", type=float, default=0.0)
    prun.add_argument("--max-concurrency", type=int, default=2)
    prun.add_argument("--request-timeout", type=float, default=600.0)
    prun.add_argument("--resume", action="store_true")
    prun.add_argument("--runs-dir", default=None)
    prun.add_argument("--enable-thinking", action="store_true")
    prun.add_argument("--max-tokens", type=int, default=None, help="override max_tokens for completion")
    prun.add_argument("--num-shards", type=int, default=1, help="split dataset into N shards (run one shard per process)")
    prun.add_argument("--shard-id", type=int, default=0, help="which shard to run: [0, N)")
    prun.set_defaults(func=cmd_run)

    peval = sub.add_parser("evaluate", help="Gold-based evaluation (aligned export format)")
    peval.add_argument("--run-dir", required=True, help="run directory (contains stage1/ or stage2/)")
    peval.add_argument("--dataset", default=str(DEFAULT_DATASET), help="gold dataset JSON path")
    peval.add_argument("--stage", choices=["stage1", "stage2"], default=None, help="which stage contains structured_units.json")
    peval.add_argument("--structured-path", default=None, help="override structured_units.json path")
    peval.add_argument("--limit", type=int, default=None, help="evaluate first N samples (dataset order)")
    peval.add_argument("--sample-frac", type=float, default=None, help="evaluate a deterministic fraction (0..1)")
    peval.add_argument("--sample-seed", type=str, default="0", help="seed for --sample-frac")
    peval.add_argument("--include-nonusable", action="store_true", help="include usable=false samples (if present)")
    peval.add_argument("--strict-schema", action="store_true", help="strict schema validation (disallow extra keys)")
    peval.add_argument("--iou-threshold", type=float, default=0.8, help="IoU threshold for SoftF1/DefeaterRecall (default 0.8)")
    peval.add_argument("--auto-fix-structured", action="store_true", default=True, help="auto-fix structured_units.json before scoring")
    peval.add_argument("--fixed-structured-path", default=None, help="path for auto-fix output (default: structured_units_fixed.json)")
    peval.add_argument("--eval-subdir", default="evaluation", help="evaluation output subdir under run_dir")
    peval.add_argument(
        "--subset-mode",
        choices=["auto", "units", "manifest", "none"],
        default="auto",
        help="filter gold to run subset (auto uses units.json then manifest)",
    )
    peval.set_defaults(func=cmd_evaluate)

    return p


def main(argv: Optional[list[str]] = None) -> None:
    # Load repo-root `.env` if present (does not override existing env by default).
    load_repo_dotenv(repo_root=REPO_ROOT, override=False)
    args = build_parser().parse_args(argv)
    args.func(args)
