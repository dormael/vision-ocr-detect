"""FastAPI application entry point."""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

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

# Path to the canonical uvicorn log config. Direct `uvicorn ...` CLI
# invocations pass `--log-config logging.json`; `python -m
# vision_ocr_detect.main` calls `load_log_config()` so both paths
# share the single source of truth (no drift between a Python dict
# and a JSON file).
_LOG_CONFIG_PATH = Path("logging.json")


def load_log_config(path: Path | None = None) -> dict[str, Any]:
    """Load uvicorn's logging config from `logging.json` (single source).

    Returns an empty dict when the file is missing or malformed —
    uvicorn treats that as "use defaults", which is the behavior we
    want for misconfigured self-hosted deployments.

    The format keys `()...` (factories) survive the JSON round-trip
    because logging.config.dictConfig reads them from the parsed dict,
    not from a re-serialization step.
    """
    config_path = path or _LOG_CONFIG_PATH
    if not config_path.exists():
        return {}
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


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

    # Pre-flight warning: any profile that points at the `openrouter`
    # provider needs OPENROUTER_API_KEY (env var or .env). Surface a
    # clear warning at startup so operators don't have to wait for a
    # 502 at first call to learn their config is incomplete. The
    # OpenRouterProvider constructor itself raises ValueError on
    # missing key, which would still crash the registry build below —
    # this warning only softens the diagnostic for the case where
    # profiles reference openrouter but the key isn't set.
    import os
    openrouter_profiles = [
        p.name for p in store.list() if p.provider == "openrouter"
    ]
    if openrouter_profiles and not os.environ.get("OPENROUTER_API_KEY"):
        request_logger.warning(
            "OPENROUTER_API_KEY is not set; openrouter profiles will fail "
            "at runtime: %s. Set the env var (or write to .env) and restart.",
            openrouter_profiles,
        )

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

        Endpoints that want extra context (e.g. `/api/detect` with its
        `profile` and `options`) can stash a JSON-serializable dict on
        `request.state.log_params` before returning — the middleware
        appends it as `params={...}` on the same log line. The
        `default=str` on json.dumps keeps non-JSON-native types (e.g.
        enums) from breaking the log.
        """
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        response.headers["X-Process-Time"] = f"{elapsed_ms}ms"

        params = getattr(request.state, "log_params", None)
        if params is not None:
            request_logger.info(
                "method=%s path=%s status=%d elapsed_ms=%d params=%s",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
                json.dumps(params, sort_keys=True, default=str),
            )
        else:
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
        log_config=load_log_config(),
    )


if __name__ == "__main__":
    main()
