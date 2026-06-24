"""FastAPI application entry point."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request

from vision_ocr_detect.api.detect import router as detect_router
from vision_ocr_detect.api.models import router as models_router
from vision_ocr_detect.api.profiles import router as profiles_router
from vision_ocr_detect.config import Settings, load_settings
from vision_ocr_detect.deps import get_profiles_path
from vision_ocr_detect.providers.registry import ProviderRegistry
from vision_ocr_detect.services.profile_store import ProfileStore

# Logger for per-request telemetry emitted by the middleware below.
# Goes through the standard logging pipeline so it can be filtered /
# redirected by the same config that handles uvicorn's loggers.
request_logger = logging.getLogger("vision_ocr_detect.request")

# Uvicorn log config: extends the default access format with `duration`
# (request time in seconds, %.3f) and `size` (response bytes). Defaults
# are kept for everything else so the format stays close to vanilla
# uvicorn — easy to grep, easy to read.
#
# The source of truth is `logging.json` at the repo root, applied via
# uvicorn's `--log-config` flag at startup. This dict mirrors the file
# so `python -m vision_ocr_detect.main` (which calls uvicorn.run with
# `log_config=LOG_CONFIG`) produces the same setup. Keep them in sync
# when adding new loggers or handlers.
LOG_CONFIG: dict[str, object] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(levelname)s: %(message)s",
        },
        "default_with_time": {
            "format": "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": (
                '%(client_addr)s - "%(request_line)s" %(status_code)s'
            ),
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "default_with_time": {
            "formatter": "default_with_time",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO"},
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {
            "handlers": ["access"],
            "level": "INFO",
            "propagate": False,
        },
        # Application-level request telemetry emitted by the
        # middleware below. Goes to stderr with timestamps so a
        # grep on /tmp/ocr-server-logs/server.log can correlate
        # application logs against uvicorn access lines.
        "vision_ocr_detect.request": {
            "handlers": ["default_with_time"],
            "level": "INFO",
            "propagate": False,
        },
    },
}


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

    @app.middleware("http")
    async def _log_request(request: Request, call_next):
        """Log total request duration and attach `X-Process-Time` header.

        Adds a structured application log line per request so a grep
        over `/tmp/ocr-server-logs/server.log` can answer "how long did
        request X take?" without parsing the access-log format. Also
        exposes the timing to clients via the response header.
        """
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Process-Time"] = f"{elapsed_ms}ms"
        request_logger.info(
            "method=%s path=%s status=%d elapsed_ms=%d",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    @app.get("/health")
    async def health() -> dict[str, object]:
        s = settings or app.state.settings
        # Best-effort: enumerate vision-capable model names per provider.
        # Failures here must not 500 the health check.
        vision_by_provider: dict[str, list[str]] = {}
        registry = getattr(app.state, "provider_registry", None)
        if registry is not None:
            try:
                models_all = await registry.list_models_all()
                for pname, infos in models_all.items():
                    vision_by_provider[pname] = sorted(
                        m.name for m in infos if m.vision_capable
                    )
            except Exception:
                pass
        return {
            "status": "ok",
            "providers": list(s.providers.keys()) if s else [],
            "profiles_loaded": len(app.state.profile_store.list())
            if getattr(app.state, "profile_store", None)
            else 0,
            "vision_models": vision_by_provider,
        }

    app.include_router(profiles_router)
    app.include_router(detect_router)
    app.include_router(models_router)

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
        log_config=LOG_CONFIG,
    )


if __name__ == "__main__":
    main()
