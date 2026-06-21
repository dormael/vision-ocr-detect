"""Shared test fixtures.

Each test gets its own temp directory with a fresh `config.json` +
`profiles.json`. The FastAPI app is built via `create_app()` and the
real `ProviderRegistry` is replaced with a mock via `app.dependency_overrides`
for endpoints that need to bypass the network.
"""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import AsyncIterator, Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from vision_ocr_detect.config import ProviderConfig, ServerConfig, Settings
from vision_ocr_detect.providers.base import (
    ModelInfo,
    ProviderNotFound,
    ProviderResult,
    VisionProvider,
)
from vision_ocr_detect.providers.registry import ProviderRegistry
from vision_ocr_detect.services.profile_store import ProfileStore


class FakeProvider:
    """In-memory VisionProvider for tests. Records every call."""

    def __init__(
        self,
        name: str,
        text: str = "fake-ocr-output",
        models: list[ModelInfo] | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
    ) -> None:
        self.name = name
        self.text = text
        self.calls: list[dict[str, object]] = []
        self.closed = False
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        # Default fixture: one vision + one non-vision model so tests can
        # exercise both code paths without setting up an explicit list.
        self.models: list[ModelInfo] = models if models is not None else [
            ModelInfo(name="fake-vision:1b", vision_capable=True, source="heuristic"),
            ModelInfo(name="fake-text:7b", vision_capable=False, source="heuristic"),
        ]


    async def list_models(self) -> list[ModelInfo]:  # type: ignore[override]
        return list(self.models)

    async def detect(  # type: ignore[override]
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
        self.calls.append(
            {
                "image_bytes": len(image),
                "mime_type": mime_type,
                "model": model,
                "prompt": prompt,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "seed": seed,
                "response_format": response_format,
            }
        )
        return ProviderResult(
            text=self.text,
            tokens_in=self._tokens_in,
            tokens_out=self._tokens_out,
            seed_used=seed,
        )

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def tmp_paths(tmp_path: Path) -> tuple[Path, Path]:
    config = tmp_path / "config.json"
    profiles = tmp_path / "profiles.json"
    profiles.write_text("{}", encoding="utf-8")
    config.write_text(
        json.dumps(
            {
                "server": {"host": "127.0.0.1", "port": 8765, "max_concurrent_requests": 2},
                "providers": {
                    "local-ollama": {
                        "type": "ollama",
                        "base_url": "http://localhost:11434",
                        "timeout_seconds": 30,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return config, profiles


@pytest.fixture
def monkeypatch_env(
    monkeypatch: pytest.MonkeyPatch, tmp_paths: tuple[Path, Path]
) -> Iterator[tuple[Path, Path]]:
    config, profiles = tmp_paths
    monkeypatch.setenv("VISION_OCR_CONFIG", str(config))
    monkeypatch.setenv("VISION_OCR_PROFILES", str(profiles))
    yield config, profiles


@pytest.fixture
def client_with_fake(
    monkeypatch_env: tuple[Path, Path],
) -> Iterator[tuple[TestClient, FakeProvider]]:
    """Build the app with a real lifespan but inject FakeProvider in place
    of OllamaProvider. Returns (client, provider)."""
    from vision_ocr_detect import deps as deps_mod
    from vision_ocr_detect import main as main_mod

    # Build settings using the env-pointed config (also captures providers).
    settings = Settings.model_validate(json.loads(monkeypatch_env[0].read_text()))

    fake = FakeProvider("local-ollama", text="extracted text")
    fake_registry = ProviderRegistry()
    fake_registry.register("local-ollama", fake)

    app = main_mod.create_app(settings=settings)
    app.dependency_overrides[deps_mod.get_provider_registry] = lambda: fake_registry

    with TestClient(app) as client:
        yield client, fake


def make_png(color: tuple[int, int, int] = (255, 0, 0), size: int = 64) -> bytes:
    img = Image.new("RGB", (size, size), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
