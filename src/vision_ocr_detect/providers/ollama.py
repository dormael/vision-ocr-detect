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
from vision_ocr_detect.providers.base import (
    CapabilitySource,
    ModelInfo,
    ProviderResult,
)


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


class _ShouldFallbackToOpenAICompat(Exception):
    """Internal signal: the native /api/generate path can't serve this
    model (404 or model-not-found). The caller should try the OpenAI-
    compat surface once before giving up.
    """
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
        response_format: str | dict | None = None,
    ) -> ProviderResult:
        """Run the model with native-first / OpenAI-compat fallback.

        Strategy (Option C, agreed with the requester):
          1. Try ollama's native /api/generate. All current ollama
             models — including vision-only ones like granite-vision
             and minicpm-v that the OpenAI-compat surface rejects with
             'illegal base64 data' — work here.
          2. On a 404 (or model-not-found in the body), fall back to
             the OpenAI-compat /v1/chat/completions surface. This
             covers edge cases where a future ollama version or a
             non-ollama server speaks only OpenAI-compat.
          3. Anything else re-raises; the API layer maps to 502.

        Records which endpoint succeeded in `result.endpoint_used`
        for downstream observability.
        """
        try:
            return await self._detect_native(
                image, mime_type, model, prompt,
                max_tokens=max_tokens, temperature=temperature,
                seed=seed, response_format=response_format,
            )
        except _ShouldFallbackToOpenAICompat:
            return await self._detect_openai_compat(
                image, mime_type, model, prompt,
                max_tokens=max_tokens, temperature=temperature,
                seed=seed, response_format=response_format,
            )

    async def _detect_native(
        self,
        image: bytes,
        mime_type: str,
        model: str,
        prompt: str,
        *,
        max_tokens: int | None,
        temperature: float | None,
        seed: int | None,
        response_format: str | dict | None,
    ) -> ProviderResult:
        """Call ollama's native /api/generate (single-prompt shape)."""
        image_b64 = base64.b64encode(image).decode("ascii")
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
        }
        # Note: native ollama doesn't accept the OpenAI-style
        # `format` key for json_schema. The OpenAI-compat surface does.
        # For native we only forward "json" (not full schema objects);
        # structured-output guarantees are stricter on /v1/chat/completions.
        if response_format == "json":
            payload["format"] = "json"
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
            f"{self._base_url}/api/generate", json=payload
        )
        # 404 / model_not_found → ask the caller to try OpenAI-compat.
        if resp.status_code == 404:
            raise _ShouldFallbackToOpenAICompat(
                f"native /api/generate returned 404 for model {model!r}"
            )
        # ollama surfaces model-not-found as 200 + body.error in some
        # builds. Detect that case too.
        if resp.status_code == 400:
            try:
                body = resp.json()
            except Exception:
                body = None
            if isinstance(body, dict) and "model" in str(body.get("error", "")).lower():
                raise _ShouldFallbackToOpenAICompat(
                    f"native /api/generate: model not found: {body}"
                )
        resp.raise_for_status()
        body = resp.json()
        if isinstance(body, dict) and body.get("error"):
            # Some ollama versions return 200 + body.error for unsupported
            # operations. Treat as a hard failure rather than a fallback
            # trigger — this isn't a 'model not found' case.
            raise RuntimeError(f"ollama native error: {body['error']}")

        text = body.get("response", "")
        if not isinstance(text, str):
            raise RuntimeError(
                f"unexpected ollama native response shape: {body!r}"
            )

        # Usage: native ollama reports prompt_eval_count / eval_count.
        return ProviderResult(
            text=text,
            tokens_in=body.get("prompt_eval_count"),
            tokens_out=body.get("eval_count"),
            seed_used=seed,
            endpoint_used="native",
        )

    async def _detect_openai_compat(
        self,
        image: bytes,
        mime_type: str,
        model: str,
        prompt: str,
        *,
        max_tokens: int | None,
        temperature: float | None,
        seed: int | None,
        response_format: str | dict | None,
    ) -> ProviderResult:
        """Call ollama's OpenAI-compatible /v1/chat/completions surface."""
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
            # ollama accepts either a string ("json") or a JSON Schema
            # dict directly under `format`. Pass through unchanged so
            # callers can use either of:
            #   response_format="json"
            #   response_format={"type": "json_schema", ...}
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
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(
                f"unexpected ollama response shape: {body!r}"
            ) from e

        usage = body.get("usage") or {}
        return ProviderResult(
            text=text,
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            seed_used=seed,
            endpoint_used="openai",
        )

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
