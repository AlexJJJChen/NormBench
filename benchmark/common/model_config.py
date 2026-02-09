"""Model config loader for NormBench.

NormBench loads model routing from a JSON file plus environment variables.
Secrets (API keys) should live in `.env` (or your shell env), not in the JSON.

Environment:
  - NORMBENCH_MODEL_CONFIG: path to a JSON config file (preferred)
  - Env vars referenced by `api_base_env` / `api_key_env` in the model JSON

Config file format (recommended):
{
  "defaults": {
    "temperature": 0.0
  },
  "models": {
    "qwen3_local": {
      "type": "llm_api",
      "provider": "vllm",
      "model": "qwen3-14b",
      "api_base_env": "LOCAL_VLLM_BASE_URL",
      "api_key_env": "LOCAL_VLLM_API_KEY"
    }
  }
}

Backward compatibility:
  - If the JSON top-level is a dict of aliases -> config, we also accept it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple


DEFAULT_CHAT_PARAMS: Dict[str, Any] = {
    # Keep conservative defaults; benchmark scripts may override per-run.
    "temperature": 0.0,
}


@dataclass(frozen=True)
class ModelConfig:
    alias: str
    model: str
    api_base: str
    api_key: str
    provider: str = ""
    raw: Mapping[str, Any] = None  # type: ignore[assignment]


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def load_model_registry(path: Optional[Path] = None) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Load (defaults, models) from a JSON config file.

    Returns:
      (defaults, models) where:
        - defaults: chat completion defaults (temperature, etc.)
        - models: alias -> model config dict
    """

    if path is None:
        env_path = (os.environ.get("NORMBENCH_MODEL_CONFIG") or "").strip()
        path = Path(env_path) if env_path else None

    if path is None:
        # No config file provided; still allow pure env-based routing (OPENAI_BASE_URL/KEY).
        return dict(DEFAULT_CHAT_PARAMS), {}

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Model config must be a JSON object: {path}")

    # Preferred schema: {"defaults": {...}, "models": {...}}
    if "models" in payload and isinstance(payload.get("models"), dict):
        defaults = _as_dict(payload.get("defaults")) or dict(DEFAULT_CHAT_PARAMS)
        models = {str(k): _as_dict(v) for k, v in _as_dict(payload.get("models")).items()}
        return defaults, models

    # Backward compat: top-level mapping of alias -> config.
    defaults = dict(DEFAULT_CHAT_PARAMS)
    models = {str(k): _as_dict(v) for k, v in payload.items()}
    return defaults, models


def _resolve_field_from_env(cfg: Mapping[str, Any], *, field: str, env_field: str) -> str:
    """Resolve a config field with an optional `*_env` indirection.

    This is the open-source-friendly equivalent of the internal pattern:
      alias -> {api_base, api_key, provider, ...}

    We keep the same *shape* (api_base/api_key exist conceptually), but allow
    moving secrets and endpoints into `.env`:
      - api_base_env / api_key_env: environment variable names
      - api_base / api_key: direct literal values (optional, not recommended for keys)
    """

    v = str(cfg.get(field) or "").strip()
    if v:
        return v
    env_name = str(cfg.get(env_field) or "").strip()
    if not env_name:
        return ""
    return str(os.environ.get(env_name) or "").strip()


def resolve_model_config(alias: str, *, defaults: Dict[str, Any], models: Dict[str, Dict[str, Any]]) -> ModelConfig:
    """Resolve one model alias to a concrete routing config."""

    a = (alias or "").strip()
    if a not in models:
        raise KeyError(f"Model alias not found: `{a}`.")
    cfg = models.get(a) or {}

    cfg_type = str(cfg.get("type") or "").strip()
    if cfg_type and cfg_type != "llm_api":
        raise ValueError(f"Model `{a}` is not a chat-capable LLM (type={cfg_type!r}).")

    model = str(cfg.get("model") or "").strip() or a
    provider = str(cfg.get("provider") or "").strip()

    api_base = _resolve_field_from_env(cfg, field="api_base", env_field="api_base_env")
    api_key = _resolve_field_from_env(cfg, field="api_key", env_field="api_key_env")

    if not api_base:
        raise ValueError(
            f"Missing api_base for model alias `{a}`. Configure `api_base`/`api_base_env` (and ensure the env var is set)."
        )
    if not api_key:
        raise ValueError(
            f"Missing api_key for model alias `{a}`. Configure `api_key`/`api_key_env` (and ensure the env var is set)."
        )

    return ModelConfig(alias=a, model=model, api_base=api_base, api_key=api_key, provider=provider, raw=cfg)
