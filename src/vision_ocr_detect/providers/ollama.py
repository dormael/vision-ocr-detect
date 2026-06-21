"""Ollama provider via the OpenAI-compatible `/v1/chat/completions` endpoint.

Using the OpenAI-compatible surface (rather than ollama's native `/api/chat`)
keeps this class close to the shape of any future OpenAI/Anthropic/vLLM
adapter — the same payload structure works.

Model listing goes through ollama's native `/api/tags` (not the OpenAI-
compat surface at /v1), which exposes `capabilities` — we use it to
classify vision-capable models and fall back to a name-based heuristic
when the capability signal is absent.
"""

from __future__ import annotations

import base64
import re
from typing import Any

import httpx

from vision_ocr_detect.config import ProviderConfig
from vision_ocr_detect.providers.base import CapabilitySource, ModelInfo


# Name-based fallback for vision detection. Matched case-insensitively
# against the model name. Conservative patterns only — false positives
# (advertising vision for a text-only model) waste user time; false
# negatives (missing a vision model) are easy to report and patch.
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
    # OCR-specific models that handle images even when ollama doesn't tag
    # the `vision` capability (observed with deepseek-ocr on some ollama
    # builds). Match "-ocr" preceded by a dash (or at start) so we don't
    # catch unrelated "ocr" substrings in unrelated names.
    r"(^|-)ocr(-|$|:)",
)
_VISION_NAME_RES = tuple(re.compile(p, re.IGNORECASE) for p in _VISION_NAME_PATTERNS)


def _classify_vision(
    name: str, capabilities: list[str] | None
) -> tuple[bool, CapabilitySource]:
    """Return (vision_capable, source).

    `capabilities` is the authoritative signal when present; we only fall
    back to name heuristics when the provider didn't say anything useful.
    """
    if capabilities is not None:
        verdict: bool = "vision" in capabilities
        return verdict, "capabilities"
    for pat in _VISION_NAME_RES:
        if pat.search(name):
            return True, "heuristic"
    return False, "unknown"


class OllamaProvider:
    """Async client for a local ollama instance.

    One instance is shared across all requests (it owns a single
    `httpx.AsyncClient` with a connection pool). `aclose()` should be
    called at shutdown.
    """

    def __init__(self, name: str, config: ProviderConfig) -> None:
        self.name = name
        self._config = config
        # ollama's OpenAI-compat surface is mounted at /v1; we keep a
        # reference to the bare base URL so /api/tags (native) can be hit
        # by list_models() with an absolute URL.
        self._base_url = config.base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url + "/v1",
            timeout=httpx.Timeout(config.timeout_seconds),
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
        response_format: str | None = None,
    ) -> str:
        headers: dict[str, str] = {}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        data_uri = f"data:{mime_type};base64,{base64.b64encode(image).decode('ascii')}"
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
        }
        if response_format is not None:
            payload["format"] = response_format
        if max_tokens is not None or temperature is not None or seed is not None:
            options: dict[str, Any] = {}
            if max_tokens is not None:
                options["num_predict"] = max_tokens
            if temperature is not None:
                options["temperature"] = temperature
            if seed is not None:
                options["seed"] = seed
            payload["options"] = options

        resp = await self._client.post(
            "/chat/completions", json=payload, headers=headers
        )
        resp.raise_for_status()
        body = resp.json()
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(
                f"unexpected ollama response shape: {body!r}"
            ) from e

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_models(self) -> list[ModelInfo]:
        """GET /api/tags and return ModelInfo per installed model.

        Uses the native ollama surface (not /v1) because capability
        metadata is only exposed there.
        """
        # httpx honors absolute URLs even when the client has a base_url,
        # so we can reuse the existing client.
        resp = await self._client.get(f"{self._base_url}/api/tags")
        resp.raise_for_status()
        body = resp.json()

        out: list[ModelInfo] = []
        for m in body.get("models", []):
            details = m.get("details") or {}
            name = m.get("name") or m.get("model") or ""
            if not name:
                continue
            vision, source = _classify_vision(name, m.get("capabilities"))
            out.append(
                ModelInfo(
                    name=name,
                    family=details.get("family"),
                    parameter_size=details.get("parameter_size"),
                    quantization_level=details.get("quantization_level"),
                    context_length=details.get("context_length"),
                    vision_capable=vision,
                    source=source,
                )
            )
        return out
