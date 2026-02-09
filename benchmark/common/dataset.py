"""Dataset loaders for released NormBench datasets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class Article2Unit2StructureItem:
    item_id: str
    language: str
    subset: str
    source_type: str
    input: Dict[str, Any]
    gold: Dict[str, Any]


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def load_article2unit2structure_dataset(
    path: Path,
    *,
    subsets: Optional[Sequence[str]] = None,
    languages: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
) -> List[Article2Unit2StructureItem]:
    """Load released dataset JSON for the Article->Unit->Structure experiment.

    Expected release format:
      {"items": [ {item_id, language, subset, source_type, input, gold}, ... ], ...}
    """

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or "items" not in payload:
        raise ValueError(f"Unsupported dataset format (missing top-level 'items'): {path}")

    want_sub = {s for s in (subsets or []) if isinstance(s, str) and s.strip()}
    want_lang = {s for s in (languages or []) if isinstance(s, str) and s.strip()}

    out: List[Article2Unit2StructureItem] = []
    for it in _as_list(payload.get("items")):
        if not isinstance(it, dict):
            continue
        item_id = str(it.get("item_id") or "").strip()
        if not item_id:
            continue
        language = str(it.get("language") or "").strip()
        subset = str(it.get("subset") or "").strip()
        source_type = str(it.get("source_type") or "").strip()
        if want_sub and subset not in want_sub:
            continue
        if want_lang and language not in want_lang:
            continue
        out.append(
            Article2Unit2StructureItem(
                item_id=item_id,
                language=language,
                subset=subset,
                source_type=source_type,
                input=_as_dict(it.get("input")),
                gold=_as_dict(it.get("gold")),
            )
        )
        if limit is not None and len(out) >= int(limit):
            break
    return out


def input_record(item: Article2Unit2StructureItem) -> Dict[str, Any]:
    """Return a normalized record dict used by the inference pipeline."""

    inp = _as_dict(item.input)
    return {
        "item_id": item.item_id,
        "language": item.language,
        "subset": item.subset,
        "source_type": item.source_type,
        "rule_id": str(inp.get("rule_id") or ""),
        "law_title": str(inp.get("law_title") or ""),
        "article_number": str(inp.get("article_number") or ""),
        "rule_text": str(inp.get("rule_text") or ""),
        "full_article_text": str(inp.get("full_article_text") or ""),
    }
