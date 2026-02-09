"""OpenAI-compatible async LLM client used by NormBench.

Model routing is loaded from a JSON config plus environment variables.
See `benchmark/common/model_config.py`.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

try:
    from openai import AsyncOpenAI  # type: ignore
except ImportError:  # pragma: no cover - provide a delayed error if openai isn't installed
    AsyncOpenAI = None  # type: ignore[assignment]

from .model_config import DEFAULT_CHAT_PARAMS, ModelConfig, load_model_registry, resolve_model_config

FINAL_PATTERN = re.compile(r"<final>([\s\S]*?)</final>", re.IGNORECASE)

FinalParser = Optional[Callable[[str], Optional[str]]]


def extract_final_block(text: str) -> Optional[str]:
    """Extract the content of the last `<final>...</final>` block, if present."""

    matches = FINAL_PATTERN.findall(text)
    if not matches:
        return None
    return matches[-1].strip()


@dataclass
class LLMResponse:
    """A minimal, uniform response container for chat completions."""

    prompt: str
    final: Optional[str]
    raw_content: str
    usage: Dict[str, Any]
    latency_seconds: float
    model: str


class AsyncLLMClient:
    """Async chat client for benchmark code."""

    def __init__(
        self,
        model_alias: str,
        *,
        model_config_path: Optional[str] = None,
        max_concurrency: int = 5,
        request_timeout: Optional[float] = None,
        retries: int = 3,
        retry_backoff_sec: float = 0.8,
        sdk_max_retries: int = 0,
        final_parser: FinalParser = extract_final_block,
    ):
        if AsyncOpenAI is None:
            raise ImportError("openai SDK is not installed. Please run `pip install openai`.")

        defaults, models = load_model_registry(Path(model_config_path) if model_config_path else None)
        self._defaults = dict(DEFAULT_CHAT_PARAMS)
        self._defaults.update(defaults or {})

        self._model_cfg: ModelConfig = resolve_model_config(model_alias, defaults=self._defaults, models=models)
        self._model = self._model_cfg.model

        # Disable SDK retries; we handle retries at the application layer.
        self._client = AsyncOpenAI(
            api_key=self._model_cfg.api_key,
            base_url=self._model_cfg.api_base,
            max_retries=sdk_max_retries,
        )
        self._timeout = request_timeout
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._retries = max(1, int(retries))
        self._retry_backoff_sec = float(retry_backoff_sec)
        self._default_final_parser: FinalParser = final_parser
        self.provider: str = self._model_cfg.provider
        self.model_alias: str = self._model_cfg.alias

    def generation_defaults(self) -> Dict[str, Any]:
        """Defaults merged from config file + hard-coded safe defaults."""

        return dict(self._defaults)

    async def acomplete(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        temperature: Optional[float] = None,
        extra_params: Optional[Dict[str, Any]] = None,
        retries: Optional[int] = None,
        retry_backoff_sec: Optional[float] = None,
        final_parser: FinalParser = None,
    ) -> LLMResponse:
        """Run one chat completion request and parse `<final>` if present."""

        params = dict(self._defaults)
        if temperature is not None:
            params["temperature"] = temperature
        if extra_params:
            params.update(extra_params)

        # Application-layer retry control.
        max_attempts = max(1, int(retries if retries is not None else self._retries))
        backoff = float(retry_backoff_sec if retry_backoff_sec is not None else self._retry_backoff_sec)
        last_err: Optional[BaseException] = None
        start_ts = time.perf_counter()
        response = None
        for attempt in range(1, max_attempts + 1):
            try:
                async with self._semaphore:
                    response = await self._client.chat.completions.create(
                        model=self._model,
                        messages=list(messages),
                        timeout=self._timeout,
                        **params,
                    )
                break
            except Exception as e:  # noqa: BLE001 - network/service errors trigger retries
                last_err = e
                if attempt >= max_attempts:
                    raise
                # Linear backoff (could be exponential) to avoid retry storms under high concurrency.
                await asyncio.sleep(backoff * attempt)
        latency = time.perf_counter() - start_ts

        content = response.choices[0].message.content or ""
        parser = final_parser if final_parser is not None else self._default_final_parser
        if parser is None:
            final = content.strip()
        else:
            final = parser(content)
        return LLMResponse(
            prompt=messages[-1]["content"],
            final=final,
            raw_content=content,
            usage=_usage_to_dict(response.usage),
            latency_seconds=latency,
            model=self._model,
        )

    async def aclose(self) -> None:
        """Close underlying HTTP connections."""

        await self._client.close()


def _usage_to_dict(usage) -> Dict[str, Any]:
    """Convert OpenAI SDK usage object into a plain dict."""

    if usage is None:
        return {}
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }
