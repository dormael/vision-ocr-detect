"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from vision_ocr_detect.api.detect import router as detect_router
from vision_ocr_detect.api.profiles import router as profiles_router
from vision_ocr_detect.config import Settings, load_settings
from vision_ocr_detect.deps import get_profiles_path
from vision_ocr_detect.providers.registry import ProviderRegistry
from vision_ocr_detect.services.profile_store import ProfileStore


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Boot/shutdown hooks.

    Loads Settings, opens the ProfileStore + ProviderRegistry, and builds
    the concurrency-capping Semaphore for /api/detect. On shutdown, registry
    clients are closed; the ProfileStore flushes synchronously on every
    write so nothing extra is needed at exit.
    """
    import asyncio

    settings = load_settings()
    app.state.settings = settings

    profiles_path = get_profiles_path()
    store = ProfileStore(profiles_path)
    store.reload()  # eager load so /api/profiles works on first request
    app.state.profile_store = store

    registry = ProviderRegistry.from_settings(settings)
    app.state.provider_registry = registry

    app.state.detect_semaphore = asyncio.Semaphore(
        settings.server.max_concurrent_requests
    )

    try:
        yield
    finally:
        app.state.detect_semaphore = None
        await registry.aclose()
        app.state.provider_registry = None
        app.state.profile_store = None
        app.state.settings = None


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app. `settings` lets tests inject a fixture."""
    app = FastAPI(
        title="vision-ocr-detect",
        version="0.1.0",
        description="Local ollama vision/OCR HTTP API",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict[str, object]:
        s = settings or app.state.settings
        return {
            "status": "ok",
            "providers": list(s.providers.keys()) if s else [],
            "profiles_loaded": len(app.state.profile_store.list())
            if getattr(app.state, "profile_store", None)
            else 0,
        }

    app.include_router(profiles_router)
    app.include_router(detect_router)

    return app


# Module-level app for `uvicorn vision_ocr_detect.main:app`
app = create_app()


def main() -> None:
    """Console entry: `uv run vision-ocr-detect`."""
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        "vision_ocr_detect.main:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
