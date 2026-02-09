"""Gold-based evaluation for article->unit->structure outputs.

This module is aligned with the internal evaluation runner used for the same
st2.v3 schema, including:
  - headline metrics export (metrics.json)
  - full metrics export (metrics_full.json)
  - per-sample records (per_sample.jsonl)
  - strict schema validation option
  - ultimate metrics: TES / SoftF1 / DefeaterRecall
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...common.io import read_json, write_json
from ...common.logging import get_logger, setup_logging
from ..scripts.fix_structured_units import fix_structured_units
from .dataset_loader import load_stage2_dataset
from .metrics import (
    Graph,
    build_graph,
    edge_f1,
    node_span_f1,
    nted,
    span_audit_metrics,
    tree_em,
)
from .schema import validate_stage2_schema
from .ultimate_metrics import (
    compute_defeater_recall,
    compute_soft_span_f1,
    compute_tree_edit_sim,
    structured_to_flat_tree,
)


logger = get_logger("normbench.article2unit2structure.evaluation")


def _empty_graph() -> Graph:
    return Graph(nodes=set(), edges=set())


def _write_jsonl(path: Path, records: List[Dict[str, Any]]) -> None:
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")


def _load_structured_units(path: Path) -> List[Dict[str, Any]]:
    payload = read_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"structured_units.json must be a list: {path}")
    return [r for r in payload if isinstance(r, dict)]


def _load_rule_ids_from_units(path: Path) -> List[str]:
    if not path.exists():
        return []
    payload = read_json(path)
    if not isinstance(payload, list):
        return []
    rule_ids: List[str] = []
    for rec in payload:
        if not isinstance(rec, dict):
            continue
        rid = rec.get("rule_id")
        if isinstance(rid, str):
            rid_norm = rid.rstrip("|").strip()
            if rid_norm:
                rule_ids.append(rid_norm)
    return rule_ids


def _load_rule_ids_from_manifest(path: Path) -> List[str]:
    if not path.exists():
        return []
    payload = read_json(path)
    if not isinstance(payload, list):
        return []
    rule_ids: List[str] = []
    for rec in payload:
        if not isinstance(rec, dict):
            continue
        rid = rec.get("rule_id")
        if isinstance(rid, str):
            rid_norm = rid.rstrip("|").strip()
            if rid_norm:
                rule_ids.append(rid_norm)
    return rule_ids


def _normalize_rule_id(rule_id: str) -> str:
    return rule_id.rstrip("|").strip()


def _resolve_manifest_path(run_root: Path) -> Optional[Path]:
    meta_path = run_root / "stage1" / "meta.json"
    if not meta_path.exists():
        return None
    meta = read_json(meta_path)
    if not isinstance(meta, dict):
        return None
    manifest = meta.get("manifest")
    if isinstance(manifest, str) and manifest.strip():
        return Path(manifest)
    return None


def _fallback_unit_key(rule_id: Optional[str], unit_id: Optional[str]) -> Optional[str]:
    if not rule_id or not unit_id:
        return None
    return f"{rule_id}#{unit_id}"


def _normalize_unit_key(unit_key: str) -> str:
    key = unit_key.strip()
    if "#" not in key:
        return key
    rid, uid = key.split("#", 1)
    rid_norm = _normalize_rule_id(rid)
    return f"{rid_norm}#{uid}" if rid_norm else key


def _pred_key(record: Dict[str, Any]) -> Optional[str]:
    unit_key = record.get("unit_key")
    if isinstance(unit_key, str) and unit_key.strip():
        return _normalize_unit_key(unit_key)
    structured = record.get("structured") if isinstance(record.get("structured"), dict) else {}
    rule_id = structured.get("rule_id") or record.get("rule_id")
    unit_id = structured.get("unit_id") or record.get("unit_id")
    fallback = _fallback_unit_key(str(rule_id) if rule_id else None, str(unit_id) if unit_id else None)
    return _normalize_unit_key(fallback) if fallback else None


def _index_predictions(records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    for r in records:
        key = _pred_key(r)
        if not key:
            continue
        if key not in mapping:
            mapping[key] = r
    return mapping


def _write_readme(
    path: Path,
    *,
    run_root: Path,
    structured_path: Path,
    dataset_path: Path,
    metrics: Dict[str, Any],
    missing_samples: List[Dict[str, Any]],
) -> None:
    counts = (metrics.get("counts") or {}) if isinstance(metrics.get("counts"), dict) else {}
    rates = (metrics.get("rates") or {}) if isinstance(metrics.get("rates"), dict) else {}
    t1 = (metrics.get("t1") or {}) if isinstance(metrics.get("t1"), dict) else {}

    lines: List[str] = []
    lines.append("# Run Summary (Gold-based)")
    lines.append("")
    lines.append("## Run")
    lines.append("")
    lines.append(f"- run_dir: `{run_root}`")
    lines.append(f"- structured_units: `{structured_path}`")
    lines.append("")
    lines.append("## Dataset")
    lines.append("")
    lines.append(f"- path: `{dataset_path}`")
    lines.append("")
    lines.append("## Results (headline)")
    lines.append("")
    for k in ["NodeSpan-F1", "Edge-F1", "Tree-EM", "nTED", "SpanFaith", "Halluc", "TES", "SoftF1", "DefeaterRecall"]:
        if k in t1:
            lines.append(f"- {k}: `{t1.get(k)}`")
    lines.append("")
    lines.append("Artifacts:")
    lines.append(f"- metrics: `{run_root / (path.parent.name) / 'metrics.json'}` (slim)")
    lines.append(f"- metrics_full: `{run_root / (path.parent.name) / 'metrics_full.json'}`")
    lines.append(f"- per-sample: `{run_root / (path.parent.name) / 'per_sample.jsonl'}`")
    if counts or rates:
        lines.append("")
        lines.append("## Debug (optional)")
        lines.append("")
        if counts:
            lines.append("Counts:")
            for k in ["total", "done", "parse_ok", "schema_ok"]:
                if k in counts:
                    lines.append(f"- {k}: `{counts.get(k)}`")
        if rates:
            lines.append("")
            lines.append("Rates:")
            for k in ["done_rate", "parse_ok_rate", "schema_ok_rate"]:
                if k in rates:
                    lines.append(f"- {k}: `{rates.get(k)}`")
    lines.append("")
    lines.append("## Missing Samples")
    lines.append("")
    if not missing_samples:
        lines.append("- (none)")
    else:
        for r in missing_samples:
            lines.append(f"- `{r.get('sample_id')}` (unit_key={r.get('unit_key')})")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _resolve_structured_path(run_root: Path, *, stage: Optional[str], structured_path: Optional[Path]) -> Path:
    if structured_path is not None:
        return structured_path

    if stage == "stage1":
        p = run_root / "stage1" / "structured_units.json"
        if p.exists():
            return p
    if stage == "stage2":
        p = run_root / "stage2" / "structured_units.json"
        if p.exists():
            return p

    for p in [run_root / "stage1" / "structured_units.json", run_root / "stage2" / "structured_units.json"]:
        if p.exists():
            return p
    raise FileNotFoundError(f"structured_units.json not found under: {run_root}")


def run_evaluation(
    *,
    run_root: Path,
    dataset_path: Path,
    stage: Optional[str] = None,
    structured_path: Optional[Path] = None,
    limit: Optional[int] = None,
    sample_frac: Optional[float] = None,
    sample_seed: str = "0",
    include_nonusable: bool = False,
    strict_schema: bool = False,
    iou_threshold: float = 0.8,
    auto_fix_structured: bool = True,
    fixed_structured_path: Optional[Path] = None,
    eval_subdir: str = "evaluation",
    subset_mode: str = "auto",
) -> Path:
    structured_path = _resolve_structured_path(run_root, stage=stage, structured_path=structured_path)

    eval_dir = run_root / str(eval_subdir)
    eval_dir.mkdir(parents=True, exist_ok=True)

    # Prefer generation-time settings (run_meta.json) when user didn't override.
    meta: Dict[str, Any] = {}
    meta_path = run_root / "run_meta.json"
    if meta_path.exists():
        try:
            meta = read_json(meta_path)
        except Exception:  # noqa: BLE001 - best-effort
            meta = {}
        if not isinstance(meta, dict):
            meta = {}

    gen_settings = (meta.get("generation") or {}) if isinstance(meta.get("generation"), dict) else {}
    effective_limit = limit
    if effective_limit is None:
        # Only infer unit-level limits here. Article-level caps (e.g. one-call runs)
        # are applied via subset filtering (units.json / manifest), not by slicing units.
        if isinstance(gen_settings.get("limit"), int):
            effective_limit = int(gen_settings["limit"])

    effective_sample_frac = sample_frac
    if effective_sample_frac is None and isinstance(gen_settings.get("sample_frac"), (int, float)):
        effective_sample_frac = float(gen_settings["sample_frac"])

    effective_sample_seed = sample_seed
    if sample_seed == "0":
        ss = gen_settings.get("sample_seed")
        if isinstance(ss, str) and ss.strip():
            effective_sample_seed = ss

    if auto_fix_structured:
        units_path = run_root / "stage1" / "units.json"
        if fixed_structured_path is None:
            fixed_structured_path = structured_path.parent / "structured_units_fixed.json"
        structured_path = fix_structured_units(structured_path, units_path, fixed_structured_path)

    # Load dataset and optionally filter to this run's subset.
    dataset = load_stage2_dataset(
        dataset_path,
        limit=None,
        usable_only=not include_nonusable,
        sample_frac=effective_sample_frac,
        sample_seed=effective_sample_seed,
    )
    if effective_limit is not None:
        dataset = type(dataset)(
            dataset_path=dataset.dataset_path,
            dataset_format_version=dataset.dataset_format_version,
            generated_at=dataset.generated_at,
            batch_id=dataset.batch_id,
            source_run_dir=dataset.source_run_dir,
            prompt_template=dataset.prompt_template,
            samples=dataset.samples[: int(effective_limit)],
        )

    if subset_mode != "none":
        rule_ids: List[str] = []
        if subset_mode in {"auto", "units"}:
            rule_ids = _load_rule_ids_from_units(run_root / "stage1" / "units.json")
        if not rule_ids and subset_mode in {"auto", "manifest"}:
            manifest = _resolve_manifest_path(run_root)
            if manifest:
                rule_ids = _load_rule_ids_from_manifest(manifest)
        want = set(rule_ids)
        if want:
            dataset = type(dataset)(
                dataset_path=dataset.dataset_path,
                dataset_format_version=dataset.dataset_format_version,
                generated_at=dataset.generated_at,
                batch_id=dataset.batch_id,
                source_run_dir=dataset.source_run_dir,
                prompt_template=dataset.prompt_template,
                samples=[s for s in dataset.samples if _normalize_rule_id(s.rule_id) in want],
            )

    # Predictions
    pred_records = _load_structured_units(structured_path)
    pred_index = _index_predictions(pred_records)

    per_sample: List[Dict[str, Any]] = []

    total = 0
    done = 0
    parse_ok_cnt = 0
    schema_ok_cnt = 0
    tree_em_sum = 0.0
    f1_sum = 0.0
    prec_sum = 0.0
    recall_sum = 0.0

    micro_tp = 0
    micro_pred_edges = 0
    micro_gold_edges = 0

    node_tp = 0
    node_pred = 0
    node_gold = 0
    node_f1_sum = 0.0

    nted_sum = 0.0
    span_faith_sum = 0.0
    halluc_sum = 0.0

    tes_sum = 0.0
    soft_f1_sum = 0.0
    defeater_recall_sum = 0.0
    defeater_recall_goldpos_sum = 0.0
    defeater_goldpos_cnt = 0

    for sample in dataset.samples:
        total += 1
        gold_graph = build_graph(sample.gold_obj)
        pred_record = pred_index.get(_normalize_unit_key(sample.unit_key))
        match_key = "unit_key"
        if pred_record is None:
            fallback_key = _fallback_unit_key(sample.rule_id, sample.unit_id)
            if fallback_key:
                pred_record = pred_index.get(_normalize_unit_key(fallback_key))
                match_key = "rule_id+unit_id"

        if pred_record is not None:
            done += 1

        pred_obj = None
        parse_error = None
        if pred_record is not None:
            pred_obj = pred_record.get("structured")
            if not isinstance(pred_obj, dict):
                parse_error = "structured_not_object"
                pred_obj = None

        parse_ok = pred_obj is not None
        if parse_ok:
            parse_ok_cnt += 1

        schema_ok = False
        schema_errors: List[str] = []
        if pred_obj is not None:
            schema_ok, schema_errors = validate_stage2_schema(
                pred_obj,
                expected_fields=None,
                strict=bool(strict_schema),
            )
        if schema_ok:
            schema_ok_cnt += 1

        invalid = (pred_obj is None) or (not schema_ok)
        if invalid:
            pred_graph = _empty_graph()
            ef1 = 0.0
            ep = 0.0
            er = 0.0
            em = 0.0
            tp = 0
            pe = 0
            ge = len(gold_graph.edges)
            nf1 = 0.0
            nt = 1.0
            span_faith = 0.0
            halluc = 1.0
            tes = 0.0
            soft_f1 = 0.0
            defeater_recall = 0.0
            gold_defeater_cnt = 0
            pred_defeater_cnt = 0
        else:
            pred_graph = build_graph(pred_obj)
            e = edge_f1(gold_graph.edges, pred_graph.edges)
            ef1 = e.f1
            ep = e.precision
            er = e.recall
            tp = e.tp
            pe = e.pred_edges
            ge = e.gold_edges
            em = tree_em(gold_graph, pred_graph)
            n = node_span_f1(gold_graph.nodes, pred_graph.nodes)
            nf1 = n.f1
            node_tp += n.tp
            node_pred += n.pred
            node_gold += n.gold
            nt = nted(gold_graph, pred_graph)
            input_text = "\n".join(
                [
                    str(sample.gold_obj.get("rule_text") or ""),
                    str(sample.gold_obj.get("unit_text") or ""),
                ]
            )
            span_faith, halluc = span_audit_metrics(pred_obj, input_text=input_text)

            gold_flat = structured_to_flat_tree(sample.gold_obj, input_text=input_text)
            pred_flat = structured_to_flat_tree(pred_obj, input_text=input_text)
            tes = compute_tree_edit_sim(pred_flat.tree, gold_flat.tree, ignore_spans=False)
            soft_f1 = compute_soft_span_f1(
                pred_flat.span_nodes,
                gold_flat.span_nodes,
                iou_threshold=float(iou_threshold),
            )
            defeater_recall = compute_defeater_recall(
                pred_flat.span_nodes,
                gold_flat.span_nodes,
                iou_threshold=float(iou_threshold),
            )
            gold_defeater_cnt = len(gold_flat.defeater_nodes)
            pred_defeater_cnt = len(pred_flat.defeater_nodes)
            if gold_defeater_cnt > 0:
                defeater_recall_goldpos_sum += defeater_recall
                defeater_goldpos_cnt += 1

        tree_em_sum += em
        f1_sum += ef1
        prec_sum += ep
        recall_sum += er
        node_f1_sum += nf1
        nted_sum += nt
        span_faith_sum += span_faith
        halluc_sum += halluc

        tes_sum += tes
        soft_f1_sum += soft_f1
        defeater_recall_sum += defeater_recall

        micro_tp += tp
        micro_pred_edges += pe
        micro_gold_edges += ge

        per_sample.append(
            {
                "sample_id": sample.sample_id,
                "unit_key": sample.unit_key,
                "matched": pred_record is not None,
                "matched_by": match_key if pred_record is not None else None,
                "parse_ok": parse_ok,
                "parse_error": parse_error,
                "schema_ok": schema_ok,
                "schema_errors": schema_errors,
                "edge_f1": ef1,
                "edge_precision": ep,
                "edge_recall": er,
                "tree_em": em,
                "node_span_f1": nf1,
                "nted": nt,
                "span_faith": span_faith,
                "halluc": halluc,
                "tes": tes,
                "soft_f1": soft_f1,
                "defeater_recall": defeater_recall,
                "gold_defeater_cnt": gold_defeater_cnt,
                "pred_defeater_cnt": pred_defeater_cnt,
                "gold_edges": len(gold_graph.edges),
                "pred_edges": len(pred_graph.edges),
                "tp": tp,
            }
        )

    missing_samples = [r for r in per_sample if not r.get("matched")]

    # Edge micro.
    if micro_pred_edges == 0:
        micro_p = 1.0 if micro_gold_edges == 0 else 0.0
    else:
        micro_p = micro_tp / micro_pred_edges
    micro_r = 1.0 if micro_gold_edges == 0 else (micro_tp / micro_gold_edges)
    micro_f1 = 0.0 if (micro_p + micro_r == 0) else (2 * micro_p * micro_r / (micro_p + micro_r))

    # Node micro.
    if node_pred == 0:
        node_micro_p = 1.0 if node_gold == 0 else 0.0
    else:
        node_micro_p = node_tp / node_pred
    node_micro_r = 1.0 if node_gold == 0 else (node_tp / node_gold)
    node_micro_f1 = (
        0.0 if (node_micro_p + node_micro_r == 0) else (2 * node_micro_p * node_micro_r / (node_micro_p + node_micro_r))
    )

    metrics: Dict[str, Any] = {
        "task": "article2unit2structure",
        "mode": "gold",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_root),
        "dataset": {
            "path": str(dataset.dataset_path),
            "batch_id": dataset.batch_id,
            "generated_at": dataset.generated_at,
            "format_version": dataset.dataset_format_version,
        },
        "counts": {
            "total": total,
            "done": done,
            "parse_ok": parse_ok_cnt,
            "schema_ok": schema_ok_cnt,
        },
        "rates": {
            "done_rate": done / total if total else 0.0,
            "parse_ok_rate": parse_ok_cnt / total if total else 0.0,
            "schema_ok_rate": schema_ok_cnt / total if total else 0.0,
            "tree_em_rate": tree_em_sum / total if total else 0.0,
            "node_span_f1_macro": node_f1_sum / total if total else 0.0,
            "node_span_f1_micro": node_micro_f1,
            "edge_f1_macro": f1_sum / total if total else 0.0,
            "edge_precision_macro": prec_sum / total if total else 0.0,
            "edge_recall_macro": recall_sum / total if total else 0.0,
            "edge_f1_micro": micro_f1,
            "edge_precision_micro": micro_p,
            "edge_recall_micro": micro_r,
            "nted": nted_sum / total if total else 0.0,
            "span_faith": span_faith_sum / total if total else 0.0,
            "halluc": halluc_sum / total if total else 0.0,
            "tes": tes_sum / total if total else 0.0,
            "soft_f1": soft_f1_sum / total if total else 0.0,
            "defeater_recall": defeater_recall_sum / total if total else 0.0,
            "defeater_recall_goldpos": (
                defeater_recall_goldpos_sum / defeater_goldpos_cnt if defeater_goldpos_cnt else 0.0
            ),
            "defeater_goldpos_frac": defeater_goldpos_cnt / total if total else 0.0,
        },
        "t1": {
            "NodeSpan-F1": node_f1_sum / total if total else 0.0,
            "Edge-F1": f1_sum / total if total else 0.0,
            "Tree-EM": tree_em_sum / total if total else 0.0,
            "nTED": nted_sum / total if total else 0.0,
            "SpanFaith": span_faith_sum / total if total else 0.0,
            "Halluc": halluc_sum / total if total else 0.0,
            "TES": tes_sum / total if total else 0.0,
            "SoftF1": soft_f1_sum / total if total else 0.0,
            "DefeaterRecall": defeater_recall_sum / total if total else 0.0,
            "DefeaterRecall@hasGold": (
                defeater_recall_goldpos_sum / defeater_goldpos_cnt if defeater_goldpos_cnt else 0.0
            ),
        },
        "micro": {
            "tp": micro_tp,
            "pred_edges": micro_pred_edges,
            "gold_edges": micro_gold_edges,
        },
        "settings": {
            "structured_units_path": str(structured_path),
            "strict_schema": strict_schema,
            "include_nonusable": bool(include_nonusable),
            "limit": effective_limit,
            "sample_frac": effective_sample_frac,
            "sample_seed": effective_sample_seed,
            "iou_threshold": float(iou_threshold),
        },
    }

    write_json(eval_dir / "metrics_full.json", metrics)
    write_json(eval_dir / "metrics.json", metrics.get("t1") or {})
    _write_jsonl(eval_dir / "per_sample.jsonl", per_sample)
    _write_readme(
        eval_dir / "README.md",
        run_root=run_root,
        structured_path=structured_path,
        dataset_path=dataset.dataset_path,
        metrics=metrics,
        missing_samples=missing_samples,
    )
    logger.info("Evaluation finished. metrics=%s", metrics["rates"])
    return eval_dir


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    default_dataset = repo_root / "dataset" / "article2unit2structure" / "normbench_v1.json"

    parser = argparse.ArgumentParser(description="Gold-based evaluation runner")
    parser.add_argument("--run-dir", type=Path, required=True, help="run directory (contains stage1/ or stage2/)")
    parser.add_argument("--dataset", type=Path, default=default_dataset, help="gold dataset JSON path")
    parser.add_argument("--stage", choices=["stage1", "stage2"], default=None, help="which stage contains structured_units.json")
    parser.add_argument("--structured-path", type=Path, default=None, help="override structured_units.json path")
    parser.add_argument("--limit", type=int, default=None, help="evaluate first N samples (dataset order)")
    parser.add_argument("--sample-frac", type=float, default=None, help="evaluate a deterministic fraction (0..1)")
    parser.add_argument("--sample-seed", type=str, default="0", help="seed used with --sample-frac")
    parser.add_argument("--include-nonusable", action="store_true", help="include usable=false samples (if present)")
    parser.add_argument("--strict-schema", action="store_true", help="strict schema validation (disallow extra keys)")
    parser.add_argument("--iou-threshold", type=float, default=0.8, help="IoU threshold for SoftF1/DefeaterRecall (default: 0.8)")
    parser.add_argument(
        "--auto-fix-structured",
        action="store_true",
        default=True,
        help="auto-fix structured_units.json before scoring (fill schema-required fields)",
    )
    parser.add_argument(
        "--fixed-structured-path",
        type=Path,
        default=None,
        help="auto-fix output path (default: structured_units_fixed.json next to structured_units.json)",
    )
    parser.add_argument("--eval-subdir", type=str, default="evaluation", help="evaluation output subdir name (default: evaluation)")
    parser.add_argument(
        "--subset-mode",
        choices=["auto", "units", "manifest", "none"],
        default="auto",
        help="filter gold to run subset (auto: prefer units.json, then manifest)",
    )
    args = parser.parse_args()

    if not args.run_dir.exists():
        raise FileNotFoundError(f"run directory does not exist: {args.run_dir}")
    setup_logging(args.run_dir / str(args.eval_subdir) / "logs")

    run_evaluation(
        run_root=args.run_dir,
        dataset_path=args.dataset,
        stage=args.stage,
        structured_path=args.structured_path,
        limit=args.limit,
        sample_frac=args.sample_frac,
        sample_seed=args.sample_seed,
        include_nonusable=bool(args.include_nonusable),
        strict_schema=bool(args.strict_schema),
        iou_threshold=float(args.iou_threshold),
        auto_fix_structured=bool(args.auto_fix_structured),
        fixed_structured_path=args.fixed_structured_path,
        eval_subdir=str(args.eval_subdir),
        subset_mode=str(args.subset_mode),
    )


if __name__ == "__main__":
    main()
