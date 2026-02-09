"""Small IO helpers for NormBench.

We keep JSON/JSONL read/write behavior consistent across the repository and
provide an atomic write utility to avoid partially-written files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Sequence


def read_json(path: Path) -> Any:
    """Read a JSON file and return the decoded Python object."""

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any, *, indent: int = 2) -> None:
    """Write a JSON file (pretty-printed by default)."""

    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=indent))


def read_jsonl(path: Path) -> Iterator[Any]:
    """Read a JSONL file line-by-line."""

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def write_jsonl(path: Path, records: Sequence[Any]) -> None:
    """Write a JSONL file in one shot."""

    payload = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
    if payload:
        payload += "\n"
    _atomic_write(path, payload)


def append_jsonl(path: Path, records: Iterable[Any]) -> None:
    """Append records to a JSONL file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _atomic_write(path: Path, payload: str) -> None:
    """Write via a temp file to avoid corrupting outputs on partial writes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        f.write(payload)
    tmp_path.replace(path)
