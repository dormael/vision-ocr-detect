"""Ollama provider via the OpenAI-compatible `/v1/chat/completions` endpoint.

Using the OpenAI-compatible surface (rather than ollama's native `/api/chat`)
keeps this class close to the shape of any future OpenAI/Anthropic/vLLM
adapter — the same payload structure works.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from vision_ocr_detect.config import ProviderConfig


class OllamaProvider:
    """Async client for a local ollama instance.

    One instance is shared across all requests (it owns a single
    `httpx.AsyncClient` with a connection pool). `aclose()` should be
    called at shutdown.
    """

    def __init__(self, name: str, config: ProviderConfig) -> None:
        self.name = name
        self._config = config
        # ollama's OpenAI-compat surface is mounted at /v1.
        self._client = httpx.AsyncClient(
            base_url=config.base_url.rstrip("/") + "/v1",
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
