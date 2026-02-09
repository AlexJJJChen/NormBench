"""Parsing and validation for st2.v3 structured outputs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

FINAL_PATTERN = re.compile(r"<final>([\s\S]*?)</final>", re.IGNORECASE)

ST2_TOP_KEYS = {
    "schema_version",
    "rule_id",
    "law_title",
    "article_number",
    "rule_text",
    "unit_id",
    "unit_text",
    "unit_reason",
    "branches",
    "meta",
}

ST2_BRANCH_KEYS = {
    "branch_id",
    "anchor",
    "norm_kind",
    "conditions",
    "effects",
    "depends_on_units",
    "depends_on_article_ref",
    "unresolved_reference",
    "notes",
}


def extract_final_block(text: str) -> Optional[str]:
    matches = FINAL_PATTERN.findall(text or "")
    if not matches:
        return None
    return matches[-1].strip()


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences if present."""

    t = (text or "").strip()
    if not t.startswith("```"):
        return t
    # Drop first fence line
    lines = t.splitlines()
    if not lines:
        return t
    # Find last fence
    last = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip().startswith("```"):
            last = i
            break
    if last is None or last == 0:
        return "\n".join(lines[1:]).strip()
    return "\n".join(lines[1:last]).strip()


@dataclass(frozen=True)
class ParsedOutput:
    raw_content: str
    final_text: Optional[str]
    parsed_obj: Optional[Any]
    parse_error: Optional[str]


def parse_stage2_output(raw_content: str) -> ParsedOutput:
    """Extract `<final>` and parse JSON inside it."""

    final_text = extract_final_block(raw_content)
    if final_text is None:
        return ParsedOutput(
            raw_content=raw_content,
            final_text=None,
            parsed_obj=None,
            parse_error="missing_final_block",
        )

    candidate = _strip_code_fences(final_text)
    try:
        obj = json.loads(candidate)
    except Exception as e:  # noqa: BLE001
        return ParsedOutput(
            raw_content=raw_content,
            final_text=final_text,
            parsed_obj=None,
            parse_error=f"json_parse_error: {e}",
        )
    return ParsedOutput(
        raw_content=raw_content,
        final_text=final_text,
        parsed_obj=obj,
        parse_error=None,
    )


def _is_str(x: Any) -> bool:
    return isinstance(x, str)


def _require_keys(obj: Dict[str, Any], required: set[str], *, strict: bool) -> List[str]:
    errors: List[str] = []
    missing = required - set(obj.keys())
    if missing:
        errors.append(f"missing_keys: {sorted(missing)}")
    if strict:
        extra = set(obj.keys()) - required
        if extra:
            errors.append(f"extra_keys: {sorted(extra)}")
    return errors


def validate_stage2_schema(
    obj: Any,
    *,
    expected_fields: Optional[Dict[str, str]] = None,
    strict: bool = True,
) -> Tuple[bool, List[str]]:
    """Validate minimal hard constraints of Stage2 schema.

    Args:
        obj: Parsed JSON object.
        expected_fields: If provided, enforce key fields equal to expected (rule_id, unit_id, rule_text, unit_text).
        strict: When true, disallow unknown keys at top-level and branch-level.
    """

    errors: List[str] = []
    if not isinstance(obj, dict):
        return False, ["top_level_not_object"]

    errors.extend(_require_keys(obj, ST2_TOP_KEYS, strict=strict))

    # Basic types
    for k in [
        "schema_version",
        "rule_id",
        "law_title",
        "article_number",
        "rule_text",
        "unit_id",
        "unit_text",
        "unit_reason",
    ]:
        if k in obj and not _is_str(obj[k]):
            errors.append(f"type_error:{k}:expected_str")

    if "schema_version" in obj and _is_str(obj["schema_version"]) and obj["schema_version"] != "st2.v3":
        errors.append("schema_version_not_st2.v3")

    # branches
    branches = obj.get("branches")
    if branches is None or not isinstance(branches, list):
        errors.append("branches_not_list")
        branches = []

    for i, b in enumerate(branches):
        if not isinstance(b, dict):
            errors.append(f"branch[{i}]_not_object")
            continue
        errors.extend([f"branch[{i}].{e}" for e in _require_keys(b, ST2_BRANCH_KEYS, strict=strict)])

        anchor = b.get("anchor")
        if not isinstance(anchor, dict):
            errors.append(f"branch[{i}].anchor_not_object")
        else:
            if "text" in anchor and not _is_str(anchor["text"]):
                errors.append(f"branch[{i}].anchor.text_not_str")
            if "occurrence" in anchor and not isinstance(anchor["occurrence"], int):
                errors.append(f"branch[{i}].anchor.occurrence_not_int")

        if "norm_kind" in b and not _is_str(b["norm_kind"]):
            errors.append(f"branch[{i}].norm_kind_not_str")

        # conditions (tree)
        cond = b.get("conditions")
        ok, cond_errs = _validate_condition_tree(cond, strict=strict)
        if not ok:
            errors.extend([f"branch[{i}].conditions.{ce}" for ce in cond_errs])

        # effects
        effects = b.get("effects")
        if not isinstance(effects, list):
            errors.append(f"branch[{i}].effects_not_list")
        else:
            for j, eff in enumerate(effects):
                if not isinstance(eff, dict):
                    errors.append(f"branch[{i}].effects[{j}]_not_object")
                    continue
                if strict:
                    extra = set(eff.keys()) - {"effect_id", "effect_text"}
                    if extra:
                        errors.append(f"branch[{i}].effects[{j}].extra_keys:{sorted(extra)}")
                if not _is_str(eff.get("effect_id")):
                    errors.append(f"branch[{i}].effects[{j}].effect_id_not_str")
                if not _is_str(eff.get("effect_text")):
                    errors.append(f"branch[{i}].effects[{j}].effect_text_not_str")

        # depends
        for list_key in ["depends_on_units", "depends_on_article_ref"]:
            v = b.get(list_key)
            if not isinstance(v, list) or any(not _is_str(x) for x in v):
                errors.append(f"branch[{i}].{list_key}_not_list_of_str")

        if "unresolved_reference" in b and not isinstance(b["unresolved_reference"], bool):
            errors.append(f"branch[{i}].unresolved_reference_not_bool")
        if "notes" in b and not _is_str(b["notes"]):
            errors.append(f"branch[{i}].notes_not_str")

    # meta (minimal)
    meta = obj.get("meta")
    if not isinstance(meta, dict):
        errors.append("meta_not_object")
    else:
        if strict:
            extra = set(meta.keys()) - {"scope_policy", "compressed_enum", "unresolved_reference", "notes"}
            if extra:
                errors.append(f"meta.extra_keys:{sorted(extra)}")
        if "scope_policy" in meta and not _is_str(meta["scope_policy"]):
            errors.append("meta.scope_policy_not_str")
        if "compressed_enum" in meta and not isinstance(meta["compressed_enum"], bool):
            errors.append("meta.compressed_enum_not_bool")
        if "unresolved_reference" in meta and not isinstance(meta["unresolved_reference"], bool):
            errors.append("meta.unresolved_reference_not_bool")
        if "notes" in meta and not _is_str(meta["notes"]):
            errors.append("meta.notes_not_str")

    # Enforce alignment with expected fields (hard constraints)
    if expected_fields:
        for k, expected in expected_fields.items():
            got = obj.get(k)
            if got is None:
                errors.append(f"expected_field_missing:{k}")
                continue
            if not _is_str(got):
                errors.append(f"expected_field_type_error:{k}")
                continue
            if got != expected:
                errors.append(f"expected_field_mismatch:{k}")

    return len(errors) == 0, errors


def _validate_condition_tree(node: Any, *, strict: bool) -> Tuple[bool, List[str]]:
    """Validate conditions tree node. Node is either leaf or subtree."""

    if not isinstance(node, dict):
        return False, ["not_object"]
    if "op" not in node or "items" not in node:
        return False, ["missing_op_or_items"]
    if not _is_str(node.get("op")) or node["op"] not in {"AND", "OR"}:
        return False, ["op_invalid"]
    items = node.get("items")
    if not isinstance(items, list):
        return False, ["items_not_list"]

    errors: List[str] = []
    for idx, it in enumerate(items):
        if not isinstance(it, dict):
            errors.append(f"item[{idx}]_not_object")
            continue
        if "op" in it and "items" in it:
            ok, sub_errs = _validate_condition_tree(it, strict=strict)
            if not ok:
                errors.extend([f"item[{idx}].{e}" for e in sub_errs])
            continue

        # leaf
        if strict:
            extra = set(it.keys()) - {"leaf_id", "tag", "text"}
            if extra:
                errors.append(f"item[{idx}].extra_keys:{sorted(extra)}")
        if not _is_str(it.get("leaf_id")):
            errors.append(f"item[{idx}].leaf_id_not_str")
        if not _is_str(it.get("tag")):
            errors.append(f"item[{idx}].tag_not_str")
        if not _is_str(it.get("text")):
            errors.append(f"item[{idx}].text_not_str")

    return len(errors) == 0, errors
