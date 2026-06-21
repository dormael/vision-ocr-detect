"""End-to-end tests for /api/models and /api/providers/{name}/models.

The FakeProvider fixture exposes two models (one vision, one text-only) by
default; specific tests build a fresh registry with a custom model list
via the `models_registry` fixture.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vision_ocr_detect.providers.base import ModelInfo


@pytest.fixture
def models_registry(client_with_fake):
    """Replace the default fake registry with one whose models are explicit."""
    client, default_fake = client_with_fake
    from vision_ocr_detect import deps as deps_mod
    from vision_ocr_detect.providers.registry import ProviderRegistry

    fake = default_fake.__class__(
        "local-ollama",
        text=default_fake.text,
        models=[
            ModelInfo(
                name="qwen2.5vl:7b",
                family="qwen25vl",
                parameter_size="7B",
                quantization_level="Q4_0",
                vision_capable=True,
                source="capabilities",
            ),
            ModelInfo(
                name="gemma2:latest",
                family="gemma2",
                parameter_size="9B",
                vision_capable=False,
                source="capabilities",
            ),
            ModelInfo(
                name="deepseek-ocr:3b",
                family="deepseekocr",
                vision_capable=True,
                source="heuristic",
            ),
        ],
    )
    registry = ProviderRegistry()
    registry.register("local-ollama", fake)
    client.app.dependency_overrides[deps_mod.get_provider_registry] = lambda: registry
    return client


def test_models_lists_all(models_registry):
    r = models_registry.get("/api/models")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "local-ollama" in body["providers"]
    names = {m["name"] for m in body["providers"]["local-ollama"]["models"]}
    assert names == {"qwen2.5vl:7b", "gemma2:latest", "deepseek-ocr:3b"}


def test_models_response_includes_metadata_and_source(models_registry):
    r = models_registry.get("/api/models")
    body = r.json()
    qwen = next(
        m for m in body["providers"]["local-ollama"]["models"]
        if m["name"] == "qwen2.5vl:7b"
    )
    assert qwen["vision_capable"] is True
    assert qwen["source"] == "capabilities"
    assert qwen["family"] == "qwen25vl"
    assert qwen["parameter_size"] == "7B"


def test_models_vision_only_filter(models_registry):
    r = models_registry.get("/api/models?vision_only=true")
    assert r.status_code == 200
    names = {m["name"] for m in r.json()["providers"]["local-ollama"]["models"]}
    assert names == {"qwen2.5vl:7b", "deepseek-ocr:3b"}


def test_models_sorted_by_name(models_registry):
    r = models_registry.get("/api/models")
    names = [m["name"] for m in r.json()["providers"]["local-ollama"]["models"]]
    assert names == sorted(names)


def test_models_provider_specific(models_registry):
    r = models_registry.get("/api/providers/local-ollama/models")
    assert r.status_code == 200
    names = {m["name"] for m in r.json()["models"]}
    assert names == {"qwen2.5vl:7b", "gemma2:latest", "deepseek-ocr:3b"}


def test_models_provider_specific_with_vision_only(models_registry):
    r = models_registry.get("/api/providers/local-ollama/models?vision_only=true")
    assert r.status_code == 200
    names = {m["name"] for m in r.json()["models"]}
    assert names == {"qwen2.5vl:7b", "deepseek-ocr:3b"}


def test_models_unknown_provider_returns_404(models_registry):
    r = models_registry.get("/api/providers/ghost/models")
    assert r.status_code == 404
    assert "ghost" in r.json()["detail"]


def test_health_includes_vision_models():
    """The /health endpoint surfaces vision model names per provider.

    /health reads from app.state.provider_registry (the real registry built
    by lifespan, not the FastAPI dependency override), so this test hits
    the real ollama instance. It's skipped if ollama is unreachable.
    """
    import asyncio
    import httpx
    from vision_ocr_detect.config import load_settings
    from vision_ocr_detect.main import create_app
    from vision_ocr_detect.providers.registry import ProviderRegistry

    # Skip if ollama isn't actually running.
    try:
        with httpx.Client(timeout=1.0) as c:
            r = c.get("http://localhost:11434/api/tags")
            if r.status_code != 200:
                pytest.skip("ollama not reachable")
    except Exception:
        pytest.skip("ollama not reachable")

    settings = load_settings()
    app = create_app(settings=settings)
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert "vision_models" in body
        assert "local-ollama" in body["vision_models"]
        # Real ollama has at least these vision-capable models installed.
        names = body["vision_models"]["local-ollama"]
        # qwen2.5vl is reliably tagged as vision by ollama.
        assert "qwen2.5vl:7b" in names
        # Pure-text models (no `vision` capability) must not appear.
        assert "gemma2:latest" not in names
        assert "qwen2.5:14b-instruct-q2_K" not in names


def test_models_provider_failure_returns_502(models_registry, monkeypatch):
    """When a provider's list_models() raises, that endpoint returns 502,
    but other providers' results stay accessible via /api/models."""
    from vision_ocr_detect import deps as deps_mod
    from vision_ocr_detect.providers.registry import ProviderRegistry

    class BrokenProvider:
        name = "broken"

        async def list_models(self):
            raise RuntimeError("upstream down")

        async def detect(self, *args, **kwargs):
            raise NotImplementedError

        async def aclose(self):
            pass

    # We replace the existing override with one whose `local-ollama` raises
    # on list_models — the registry helper reports an error placeholder
    # in /api/models, and the per-provider endpoint returns 502.
    broken = BrokenProvider()
    ollama_fake = models_registry.app.dependency_overrides[deps_mod.get_provider_registry]()
    registry = ProviderRegistry()
    registry.register("local-ollama", ollama_fake)
    registry.register("broken", broken)
    models_registry.app.dependency_overrides[deps_mod.get_provider_registry] = lambda: registry

    r_all = models_registry.get("/api/models")
    assert r_all.status_code == 200
    providers = r_all.json()["providers"]
    assert "local-ollama" in providers
    assert "broken" in providers
    # The broken provider surfaces an error placeholder, not a 5xx.
    assert any("unavailable" in m["name"] for m in providers["broken"]["models"])

    r_one = models_registry.get("/api/providers/broken/models")
    assert r_one.status_code == 502
    assert "broken" in r_one.json()["detail"]


# ----------------------------------------------------------------------
# ollama provider — capabilities vs heuristic classification
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_provider_classifies_with_capabilities(respx_mock):
    """When /api/tags returns a capabilities field, we use it directly."""
    from vision_ocr_detect.config import ProviderConfig
    from vision_ocr_detect.providers.ollama import OllamaProvider

    respx_mock.get("http://localhost:11434/api/tags").respond(
        json={
            "models": [
                {
                    "name": "qwen2.5vl:7b",
                    "details": {"family": "qwen25vl"},
                    "capabilities": ["completion", "vision"],
                },
                {
                    "name": "gemma2:latest",
                    "details": {"family": "gemma2"},
                    "capabilities": ["completion"],
                },
            ]
        }
    )
    p = OllamaProvider("local-ollama", ProviderConfig(
        type="ollama", base_url="http://localhost:11434", timeout_seconds=5
    ))
    try:
        infos = await p.list_models()
    finally:
        await p.aclose()

    by_name = {m.name: m for m in infos}
    assert by_name["qwen2.5vl:7b"].vision_capable is True
    assert by_name["qwen2.5vl:7b"].source == "capabilities"
    assert by_name["gemma2:latest"].vision_capable is False
    assert by_name["gemma2:latest"].source == "capabilities"


@pytest.mark.asyncio
async def test_ollama_provider_heuristic_fallback_when_no_capabilities(respx_mock):
    """Older ollama builds may not return `capabilities` — fall back to
    name matching for vision candidates."""
    from vision_ocr_detect.config import ProviderConfig
    from vision_ocr_detect.providers.ollama import OllamaProvider

    respx_mock.get("http://localhost:11434/api/tags").respond(
        json={
            "models": [
                {"name": "deepseek-ocr:3b"},  # OCR-specific, no capabilities
                {"name": "qwen2.5vl:7b"},
                {"name": "mistral:7b"},
            ]
        }
    )
    p = OllamaProvider("local-ollama", ProviderConfig(
        type="ollama", base_url="http://localhost:11434", timeout_seconds=5
    ))
    try:
        infos = await p.list_models()
    finally:
        await p.aclose()

    by_name = {m.name: m for m in infos}
    assert by_name["deepseek-ocr:3b"].vision_capable is True
    assert by_name["deepseek-ocr:3b"].source == "heuristic"
    assert by_name["qwen2.5vl:7b"].vision_capable is True
    assert by_name["qwen2.5vl:7b"].source == "heuristic"
    assert by_name["mistral:7b"].vision_capable is False
    assert by_name["mistral:7b"].source == "unknown"