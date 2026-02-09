"""
batching.py
===========
State management utilities for batched runs (progress, checkpoints, resume).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence
import re

from . import io

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
BATCH_SUFFIX_PATTERN = re.compile(r".*_\d{8}_\d{6}$")


def utc_now() -> str:
    """Return current UTC time string."""

    return datetime.now(timezone.utc).strftime(ISO_FORMAT)


def ensure_timestamp_suffix(label: str) -> str:
    """Ensure batch/task id ends with `_YYYYMMDD_HHMMSS`."""

    base = (label or "batch").strip().replace(" ", "-")
    if BATCH_SUFFIX_PATTERN.match(base):
        return base
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base}_{timestamp}"


def require_timestamp_suffix(label: str) -> None:
    """Validate that batch/task id already contains the timestamp suffix."""

    if not BATCH_SUFFIX_PATTERN.match((label or "").strip()):
        raise ValueError("batch_id must end with `_YYYYMMDD_HHMMSS`.")


@dataclass
class BatchItem:
    """One work item in a batch."""

    sample_id: str
    payload: Dict[str, object]
    metadata: Dict[str, object] = field(default_factory=dict)


class BatchStateManager:
    """Manage batch state and support resume via checkpoints."""

    def __init__(self, batch_dir: Path, *, meta_path: Optional[Path] = None):
        self.batch_dir = batch_dir
        self.checkpoint_dir = batch_dir / "checkpoints"
        self.progress_path = batch_dir / "progress.json"
        self.meta_path = meta_path or (batch_dir / "meta.json")

    def ensure_structure(self) -> None:
        """Ensure batch directory structure exists."""

        self.batch_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def init_progress(
        self,
        batch_id: str,
        stage: str,
        items: Sequence[BatchItem],
        *,
        manifest_path: str,
        extra_meta: Optional[Dict[str, object]] = None,
        write_meta: bool = True,
    ) -> None:
        """Initialize progress.json/meta.json and per-sample checkpoints."""

        self.ensure_structure()
        samples = {item.sample_id: "pending" for item in items}
        progress = {
            "batch_id": batch_id,
            "stage": stage,
            "manifest": manifest_path,
            "totals": {
                "pending": len(samples),
                "running": 0,
                "done": 0,
                "error": 0,
            },
            "samples": samples,
            "updated_at": utc_now(),
        }
        io.write_json(self.progress_path, progress)

        if write_meta:
            meta = {
                "batch_id": batch_id,
                "stage": stage,
                "manifest": manifest_path,
                "created_at": utc_now(),
            }
            if extra_meta:
                meta.update(extra_meta)
            io.write_json(self.meta_path, meta)

        for item in items:
            self.write_checkpoint(
                item.sample_id,
                {
                    "status": "pending",
                    "payload": item.payload,
                    "metadata": item.metadata,
                },
            )

    def load_meta(self) -> Dict[str, object]:
        """Load meta.json."""

        return io.read_json(self.meta_path)

    def load_progress(self) -> Dict[str, object]:
        """Load progress.json."""

        return io.read_json(self.progress_path)

    def update_status(
        self,
        sample_id: str,
        *,
        old_status: Optional[str] = None,
        new_status: str,
    ) -> None:
        """Update a sample status and adjust aggregate counters."""

        progress = self.load_progress()
        samples = progress["samples"]
        totals = progress["totals"]

        current = old_status or samples.get(sample_id)
        if current and current in totals:
            totals[current] = max(0, totals[current] - 1)
        totals.setdefault(new_status, 0)
        totals[new_status] += 1

        samples[sample_id] = new_status
        progress["updated_at"] = utc_now()
        io.write_json(self.progress_path, progress)

    def get_status(self, sample_id: str) -> Optional[str]:
        """Return current status for a sample."""

        progress = self.load_progress()
        return progress["samples"].get(sample_id)

    def write_checkpoint(self, sample_id: str, payload: Dict[str, object]) -> None:
        """Write one per-sample checkpoint JSON."""

        path = self.checkpoint_dir / f"{sample_id}.json"
        payload["updated_at"] = utc_now()
        io.write_json(path, payload)

    def read_checkpoint(self, sample_id: str) -> Dict[str, object]:
        """Read one per-sample checkpoint; return a default structure if missing."""

        path = self.checkpoint_dir / f"{sample_id}.json"
        if path.exists():
            return io.read_json(path)
        return {"status": "pending", "updated_at": utc_now()}

    def iter_samples(
        self,
        statuses: Iterable[str],
        *,
        limit: Optional[int] = None,
    ) -> Iterator[str]:
        """Iterate sample ids filtered by status."""

        progress = self.load_progress()
        samples = progress["samples"]
        wanted = set(statuses)
        count = 0
        for sample_id, status in samples.items():
            if status in wanted:
                yield sample_id
                count += 1
                if limit is not None and count >= limit:
                    break


class ConcurrencyLimiter:
    """A tiny concurrency limiter based on asyncio.Semaphore."""

    def __init__(self, max_concurrency: int):
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def __aenter__(self):
        await self._semaphore.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._semaphore.release()
