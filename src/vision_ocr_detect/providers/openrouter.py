"""OpenRouter provider via its OpenAI-compatible `/api/v1/chat/completions`.

OpenRouter (https://openrouter.ai) exposes a unified OpenAI-shaped gateway
over many hosted vision models — `qwen/qwen3-vl-32b-instruct`,
`qwen/qwen2.5-vl-72b-instruct`, etc. Useful when a model isn't available
locally (no GPU, no local ollama install) or when the requester wants to
A/B against a larger hosted variant.

The auth model is `Authorization: Bearer <api_key>`. Set the key via
the `OPENROUTER_API_KEY` environment variable (preferred) or hardcode in
`config.json` for self-hosted single-tenant deployments.

Model listing goes through OpenRouter's `/api/v1/models` (public, no
auth required for the model catalog). Vision-capable classification is
name-based — OpenRouter's catalog doesn't carry capability flags, so
we fall back to the same regex set used for ollama.
"""

from __future__ import annotations

import base64
import os
import re
from typing import Any

import httpx

from vision_ocr_detect.config import ProviderConfig
from vision_ocr_detect.providers.base import (
    CapabilitySource,
    ModelInfo,
    ProviderResult,
)


# Same conservative name-based patterns as the ollama provider. Matched
# case-insensitively against the model id (e.g. "qwen/qwen3-vl-32b-instruct"
# matches the `qwen.*vl` pattern). False positives waste user time; false
# negatives are easy to spot and report.
_VISION_NAME_PATTERNS: tuple[str, ...] = (
    r"^llava",
    r"-vl",
    r"vl-",
    r"vision",
    r"moondream",
    r"cogvlm",
    r"internvl",
    r"minicpm-v",
    r"bakllava",
    r"yi-vl",
    r"qwen.*vl",
    r"(^|-)ocr(-|$|:)",
)
_VISION_NAME_RES = tuple(re.compile(p, re.IGNORECASE) for p in _VISION_NAME_PATTERNS)


def _classify_vision(name: str) -> tuple[bool, CapabilitySource]:
    """Name-only vision classification. OpenRouter's catalog doesn't
    expose capability metadata, so we always record `source='heuristic'`."""
    for pat in _VISION_NAME_RES:
        if pat.search(name):
            return True, "heuristic"
    return False, "unknown"


class OpenRouterProvider:
    """Async client for OpenRouter.

    One instance is shared across all requests (it owns a single
    `httpx.AsyncClient` with a connection pool). `aclose()` should
    be called at shutdown.

    API key resolution order:
      1. `config.api_key` (explicit in config.json — discouraged)
      2. `OPENROUTER_API_KEY` environment variable
    If neither is set, `__init__` raises — fail fast at boot, not
    at first request.
    """

    def __init__(self, name: str, config: ProviderConfig) -> None:
        self.name = name
        self._config = config
        api_key = config.api_key or os.environ.get("OPENROUTER_API_KEY")
        self._api_key = api_key
        # OpenRouter's OpenAI-compat surface — strip a trailing slash
        # so we don't end up with `//chat/completions` in the path.
        self._base_url = config.base_url.rstrip("/")
        # Always build the client — even without a key — so lifespan
        # startup doesn't fail. detect() raises a clear error if
        # called without a key. The startup-time warning (if any) is
        # the lifespan's responsibility (see main.py).
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(config.timeout_seconds),
            headers=headers,
        )

    async def detect(
        self,
        image: bytes,
        mime_type: str,
        model: str,
        prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        response_format: str | dict | None = None,
    ) -> ProviderResult:
        """Call OpenRouter's OpenAI-compatible chat-completions endpoint.

        OpenRouter is OpenAI-shaped: the same payload structure that
        `ollama._detect_openai_compat` builds works here, modulo the
        `Authorization` header (handled in `__init__`).

        OpenRouter recommends sending `HTTP-Referer` and `X-Title` so
        the request shows up in the OpenRouter dashboard with app
        attribution. We skip these for now — they're optional and add
        little value for an internal / server-to-server use case.
        """
        if not self._api_key:
            # Constructor accepts no key so server can boot and
            # surface the warning; the failure surfaces here at call
            # time, which the API layer maps to 502.
            raise RuntimeError(
                "openrouter provider is not configured: set "
                "OPENROUTER_API_KEY env var (or api_key in config.json) "
                "and restart"
            )
        data_uri = (
            f"data:{mime_type};base64,"
            f"{base64.b64encode(image).decode('ascii')}"
        )
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_uri},
                        },
                    ],
                }
            ],
        }
        if response_format is not None:
            # OpenRouter's gateway accepts the same OpenAI-style
            # response_format as the OpenAI API. Pass through
            # unchanged so callers can use either of:
            #   response_format="json"
            #   response_format={"type": "json_schema", ...}
            payload["response_format"] = response_format
        if max_tokens is not None or temperature is not None or seed is not None:
            payload["max_tokens"] = max_tokens
            payload["temperature"] = temperature
            # OpenRouter (and most OpenAI-compat surfaces) don't accept
            # `seed` for all models; send it anyway and let the upstream
            # gateway either honor it or ignore it.
            if seed is not None:
                payload["seed"] = seed

        resp = await self._client.post(
            "/chat/completions", json=payload
        )
        resp.raise_for_status()
        body = resp.json()
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(
                f"unexpected openrouter response shape: {body!r}"
            ) from e

        usage = body.get("usage") or {}
        # OpenRouter sometimes nests cost under `usage.cost`; some
        # endpoints just return `usage.cost` as a USD float. We surface
        # the per-token counts (the cost itself is computed in
        # detect.py from the provider config's price-per-1k, which
        # keeps a single source of truth for pricing).
        return ProviderResult(
            text=text,
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            seed_used=seed,
            endpoint_used="openai",  # we hit /v1/chat/completions
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_models(self) -> list[ModelInfo]:
        """GET /api/v1/models and return ModelInfo per model.

        OpenRouter's catalog is public — the auth header isn't required
        for the model list, but sending it is harmless and gets us a
        higher rate limit if OpenRouter ever enforces one. We send it.

        Vision-capable classification is name-based (heuristic) since
        OpenRouter doesn't expose capability metadata. Operators who
        want stricter classification should override the model list via
        a local catalog at the registry layer.
        """
        resp = await self._client.get("/models")
        resp.raise_for_status()
        body = resp.json()

        out: list[ModelInfo] = []
        # OpenRouter returns `{"data": [{"id": ..., ...}, ...]}`.
        for m in body.get("data", []):
            name = m.get("id") or m.get("name") or ""
            if not name:
                continue
            vision, source = _classify_vision(name)
            out.append(
                ModelInfo(
                    name=name,
                    family=m.get("architecture", {}).get("family")
                    if isinstance(m.get("architecture"), dict)
                    else None,
                    parameter_size=None,  # OpenRouter doesn't expose
                    quantization_level=None,
                    context_length=m.get("context_length"),
                    vision_capable=vision,
                    source=source,
                )
            )
        return out
