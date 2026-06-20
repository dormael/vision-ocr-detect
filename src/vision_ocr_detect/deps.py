"""FastAPI dependencies.

Stateful singletons live on `app.state` and are created during the
`lifespan` startup. Endpoints grab them via `Depends(get_xxx)` so tests can
swap them with `app.dependency_overrides`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Depends, Request

from vision_ocr_detect.config import Settings
from vision_ocr_detect.providers.base import VisionProvider
from vision_ocr_detect.providers.registry import ProviderRegistry
from vision_ocr_detect.services.profile_store import ProfileStore


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:  # pragma: no cover - lifespan enforces this
        raise RuntimeError("settings not initialized; lifespan did not run")
    return settings


def get_profile_store(request: Request) -> ProfileStore:
    store = getattr(request.app.state, "profile_store", None)
    if store is None:  # pragma: no cover - lifespan enforces this
        raise RuntimeError("profile_store not initialized; lifespan did not run")
    return store


def get_provider_registry(request: Request) -> ProviderRegistry:
    reg = getattr(request.app.state, "provider_registry", None)
    if reg is None:  # pragma: no cover - lifespan enforces this
        raise RuntimeError("provider_registry not initialized; lifespan did not run")
    return reg


def get_provider(name: str, registry: ProviderRegistry) -> VisionProvider:
    """Lookup helper. Raises ProviderNotFound → caller maps to 404/400."""
    from vision_ocr_detect.providers.base import ProviderNotFound

    try:
        return registry.get(name)
    except ProviderNotFound as e:
        raise ProviderNotFound(name) from e


def get_profiles_path() -> Path:
    """Path to the on-disk profiles.json.

    Lives outside `get_profile_store` because tests want to manipulate the
    path before lifespan creates the store. Returns the env var or default
    `profiles.json` next to config.json.
    """

    import os

    env = os.environ.get("VISION_OCR_PROFILES")
    if env:
        return Path(env).expanduser().resolve()
    return Path("profiles.json").resolve()


def get_provider_names(settings: Settings = Depends(get_settings)) -> set[str]:
    """Helper: set of configured provider names (used by profile validation)."""
    return set(settings.providers.keys())
