"""Tests for the OpenRouter provider.

OpenRouter is OpenAI-compat, so we mock the HTTP layer with `respx`
and assert the request payload / response mapping. The auth path
(env var fallback, missing-key error) is tested directly without
HTTP.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest
import respx

from vision_ocr_detect.config import ProviderConfig
from vision_ocr_detect.providers.openrouter import (
    OpenRouterProvider,
    _classify_vision,
)


def _make_config(**overrides: Any) -> ProviderConfig:
    """Build a ProviderConfig with sensible OpenRouter defaults.

    `overrides` lets each test swap a single field (e.g. `api_key=None`
    to exercise the env-var fallback path).
    """
    base: dict[str, Any] = {
        "type": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sk-or-test-key",
        "timeout_seconds": 10.0,
    }
    base.update(overrides)
    return ProviderConfig(**base)


# --- API key resolution -----------------------------------------------


def test_openrouter_uses_explicit_api_key_when_set(monkeypatch) -> None:
    """Explicit `api_key` in config wins — env var is ignored when set."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env-key")
    p = OpenRouterProvider("openrouter", _make_config(api_key="sk-or-config-key"))
    # Authorization header should use the config value, not the env var.
    assert p._client.headers["Authorization"] == "Bearer sk-or-config-key"
    assert p._api_key == "sk-or-config-key"


def test_openrouter_falls_back_to_env_var(monkeypatch) -> None:
    """When `api_key` is None, the provider reads `OPENROUTER_API_KEY`."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env-key")
    p = OpenRouterProvider("openrouter", _make_config(api_key=None))
    assert p._api_key == "sk-or-env-key"
    assert p._client.headers["Authorization"] == "Bearer sk-or-env-key"


def test_openrouter_raises_when_no_key_available(monkeypatch) -> None:
    """No config key, no env var → fail fast at __init__, not at first call."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        OpenRouterProvider("openrouter", _make_config(api_key=None))


# --- vision classification ---------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("qwen/qwen3-vl-32b-instruct", True),
        ("qwen/qwen2.5-vl-72b-instruct", True),
        ("anthropic/claude-3.5-sonnet", False),
        ("meta-llama/llama-3.1-70b-instruct", False),
    ],
)
def test_classify_vision_heuristic(name: str, expected: bool) -> None:
    vision, source = _classify_vision(name)
    assert vision is expected
    assert source == "heuristic" if vision else "unknown"


# --- list_models --------------------------------------------------------


@pytest.mark.asyncio
async def test_list_models_parses_openrouter_catalog() -> None:
    """`/models` returns `{"data": [{id, ...}, ...]}`; we extract id
    and run the vision heuristic on each."""
    config = _make_config()
    provider = OpenRouterProvider("openrouter", config)
    try:
        with respx.mock(base_url=config.base_url) as router:
            router.get("/models").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "data": [
                            {"id": "qwen/qwen3-vl-32b-instruct", "context_length": 32768},
                            {"id": "qwen/qwen2.5-vl-72b-instruct", "context_length": 32768},
                            {"id": "meta-llama/llama-3.1-70b-instruct"},
                        ]
                    },
                )
            )
            models = await provider.list_models()
    finally:
        await provider.aclose()

    names = [m.name for m in models]
    assert "qwen/qwen3-vl-32b-instruct" in names
    assert "qwen/qwen2.5-vl-72b-instruct" in names
    # Vision classification distinguishes the qwen-vl models.
    by_name = {m.name: m for m in models}
    assert by_name["qwen/qwen3-vl-32b-instruct"].vision_capable is True
    assert by_name["qwen/qwen2.5-vl-72b-instruct"].vision_capable is True
    assert by_name["meta-llama/llama-3.1-70b-instruct"].vision_capable is False


# --- detect -------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_sends_correct_payload_and_parses_response() -> None:
    """Verify the request body shape and the response → ProviderResult
    mapping for a vision call."""
    config = _make_config()
    provider = OpenRouterProvider("openrouter", config)
    image_bytes = b"\x89PNG\r\n\x1a\n fake-image-bytes"
    try:
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/chat/completions").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "id": "gen-abc",
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": '{"sections": []}',
                                }
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 50,
                        },
                    },
                )
            )
            result = await provider.detect(
                image_bytes,
                "image/png",
                "qwen/qwen3-vl-32b-instruct",
                "extract the layout",
                max_tokens=2048,
                temperature=0.0,
                seed=42,
                response_format="json",
            )
    finally:
        await provider.aclose()

    assert result.text == '{"sections": []}'
    assert result.tokens_in == 100
    assert result.tokens_out == 50
    assert result.seed_used == 42
    assert result.endpoint_used == "openai"

    # Inspect the request we sent: image as data URI, prompt as text
    # content, response_format passed through.
    sent = route.calls.last.request
    body = sent.read().decode()
    import json as _json
    payload = _json.loads(body)
    assert payload["model"] == "qwen/qwen3-vl-32b-instruct"
    assert payload["max_tokens"] == 2048
    assert payload["temperature"] == 0.0
    assert payload["seed"] == 42
    assert payload["response_format"] == "json"
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "extract the layout"
    assert content[1]["type"] == "image_url"
    expected_b64 = base64.b64encode(image_bytes).decode("ascii")
    assert content[1]["image_url"]["url"] == f"data:image/png;base64,{expected_b64}"


@pytest.mark.asyncio
async def test_detect_propagates_5xx() -> None:
    """An upstream 500 should raise — the API layer maps to 502."""
    config = _make_config()
    provider = OpenRouterProvider("openrouter", config)
    try:
        with respx.mock(base_url=config.base_url) as router:
            router.post("/chat/completions").mock(
                return_value=httpx.Response(500, json={"error": "boom"})
            )
            with pytest.raises(httpx.HTTPStatusError):
                await provider.detect(
                    b"\x89PNG fake",
                    "image/png",
                    "qwen/qwen3-vl-32b-instruct",
                    "prompt",
                )
    finally:
        await provider.aclose()


# --- registry wiring ----------------------------------------------------


def test_registry_builds_openrouter_provider() -> None:
    """`ProviderConfig(type='openrouter')` should resolve to OpenRouterProvider
    via the dispatch table."""
    from vision_ocr_detect.providers.registry import _BUILDERS

    assert "openrouter" in _BUILDERS
    p = _BUILDERS["openrouter"]("openrouter", _make_config())
    assert isinstance(p, OpenRouterProvider)
