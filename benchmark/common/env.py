"""Tiny .env loader (no external dependency).

NormBench is meant to be runnable via CLI with minimal setup. We support loading
environment variables from a `.env` file located at the repo root.

Rules:
  - Lines: KEY=VALUE
  - Ignore empty lines and comments starting with '#'
  - Optional leading 'export '
  - Surrounding single/double quotes are stripped
  - By default we do NOT override existing environment variables
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional


def _strip_quotes(v: str) -> str:
    s = (v or "").strip()
    if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1]
    return s


def load_env_file(path: Path, *, override: bool = False) -> Dict[str, str]:
    """Load env vars from a file and return the parsed mapping."""

    out: Dict[str, str] = {}
    if not path.exists():
        return out

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        if not key:
            continue
        val = _strip_quotes(v)
        out[key] = val
        if override or key not in os.environ:
            os.environ[key] = val
    return out


def load_repo_dotenv(*, repo_root: Path, filename: str = ".env", override: bool = False) -> Dict[str, str]:
    """Load `.env` under repo_root (if exists)."""

    return load_env_file(repo_root / filename, override=override)

