"""Fix `structured_units.json` to evaluation-compatible shape.

Some one-call runs store each unit output as a "Unit + Structure" pair:

- record["structured"] = {"unit_id", "unit_text", "unit_reason", "structure": <st2.v3>}

But the gold-based evaluators expect:

- record["structured"] = <st2.v3>

This helper unwraps the nested `structure` object, and ensures `unit_key` exists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...common.io import read_json, write_json


def _as_dict(obj: Any) -> Dict[str, Any]:
    return obj if isinstance(obj, dict) else {}


def _fallback_unit_key(rule_id: Optional[str], unit_id: Optional[str]) -> Optional[str]:
    rid = (rule_id or "").strip()
    uid = (unit_id or "").strip()
    if not rid or not uid:
        return None
    return f"{rid}#{uid}"


def _norm_rule_id(rule_id: Optional[str]) -> Optional[str]:
    if not isinstance(rule_id, str):
        return None
    rid = rule_id.rstrip("|").strip()
    return rid or None


def _unwrap_structured(record: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Return (new_record, changed)."""

    changed = False
    out = dict(record)

    structured = _as_dict(out.get("structured"))
    # Case A: structured is {unit_id, unit_text, unit_reason, structure:<st2.v3>}
    if "structure" in structured and isinstance(structured.get("structure"), dict):
        out["structured"] = structured["structure"]
        changed = True
        structured = out["structured"]

    # Case B: record itself is already the unit+structure pair (legacy exports)
    if "structured" not in out and isinstance(out.get("structure"), dict):
        out["structured"] = out["structure"]
        changed = True
        structured = out["structured"]

    # Normalize rule_id formatting (gold rule_id drops trailing '|')
    st = _as_dict(structured)
    st_rule_id = _norm_rule_id(st.get("rule_id"))
    if st_rule_id and st.get("rule_id") != st_rule_id:
        st["rule_id"] = st_rule_id
        out["structured"] = st
        structured = st
        changed = True

    out_rule_id = _norm_rule_id(out.get("rule_id") if isinstance(out.get("rule_id"), str) else None)
    if out_rule_id and out.get("rule_id") != out_rule_id:
        out["rule_id"] = out_rule_id
        changed = True

    # Ensure unit_key exists (evaluator uses it as primary key)
    unit_key = out.get("unit_key")
    if not (isinstance(unit_key, str) and unit_key.strip()):
        key = _fallback_unit_key(
            _norm_rule_id(st.get("rule_id")) or _norm_rule_id(out.get("rule_id")),
            (st.get("unit_id") if isinstance(st.get("unit_id"), str) else None)
            or (out.get("unit_id") if isinstance(out.get("unit_id"), str) else None),
        )
        if key:
            out["unit_key"] = key
            changed = True
    else:
        # Normalize existing unit_key with normalized rule_id
        if isinstance(unit_key, str) and "#" in unit_key:
            rid, uid = unit_key.split("#", 1)
            rid_norm = _norm_rule_id(rid)
            if rid_norm and rid_norm != rid:
                out["unit_key"] = f"{rid_norm}#{uid}"
                changed = True

    return out, changed


def fix_structured_units(structured_path: Path, units_path: Path, fixed_path: Path) -> Path:
    """Fix/unwrap `structured_units.json` and write to `fixed_path`.

    Args:
        structured_path: original structured_units.json
        units_path: stage1/units.json (currently unused; kept for API compatibility)
        fixed_path: output path

    Returns:
        Path to the fixed structured_units.json (always `fixed_path` when successful).
    """

    payload = read_json(structured_path)
    if not isinstance(payload, list):
        raise ValueError(f"structured_units.json must be a list: {structured_path}")

    fixed: List[Dict[str, Any]] = []
    any_changed = False
    for rec in payload:
        if not isinstance(rec, dict):
            continue
        new_rec, changed = _unwrap_structured(rec)
        fixed.append(new_rec)
        any_changed = any_changed or changed

    # Always write: evaluation code points to fixed_path.
    write_json(fixed_path, fixed)
    return fixed_path
