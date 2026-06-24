"""Tests for the request-telemetry middleware in main.py.

Covers:
- `X-Process-Time` response header is set on every endpoint
- A structured log line is emitted on every request with method/path/
  status/elapsed_ms fields
"""

from __future__ import annotations

import logging
import re

import pytest
from fastapi import Request


def _make_client():
    """Build a TestClient (context manager) using the real FastAPI app.

    The middleware is registered on the module-level `app`, so we
    import it directly rather than going through `create_app()`. The
    TestClient must run inside its `__enter__` to fire lifespan, which
    initialises the profile_store / provider_registry.
    """
    from fastapi.testclient import TestClient

    from vision_ocr_detect.main import app

    return TestClient(app)


def test_middleware_sets_x_process_time_header() -> None:
    """Every response should carry an `X-Process-Time: <n>ms` header."""
    with _make_client() as client:
        r = client.get("/health")
        assert r.status_code == 200
        header = r.headers.get("x-process-time")
        assert header is not None
        # Header looks like "123ms" — must end with "ms" and start with digits.
        assert re.fullmatch(r"\d+ms", header), f"unexpected header: {header!r}"


def test_middleware_emits_structured_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A log line keyed by `vision_ocr_detect.request` should fire on
    every request, with method, path, status, and elapsed_ms fields."""
    with caplog.at_level(logging.INFO, logger="vision_ocr_detect.request"):
        with _make_client() as client:
            r = client.get("/health")
            assert r.status_code == 200

    records = [r for r in caplog.records if r.name == "vision_ocr_detect.request"]
    assert len(records) >= 1, f"no request log records: {caplog.records}"

    msg = records[-1].getMessage()
    assert "method=GET" in msg
    assert "path=/health" in msg
    assert "status=200" in msg
    # elapsed_ms is an integer; we just check the prefix
    assert re.search(r"elapsed_ms=\d+", msg), f"missing elapsed_ms: {msg}"


def test_middleware_log_includes_status_for_error_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The structured log captures the status code even on errors, so
    a grep on `status=422` finds schema-validation failures without
    needing to parse the uvicorn access-log format."""
    with caplog.at_level(logging.INFO, logger="vision_ocr_detect.request"):
        with _make_client() as client:
            r = client.get("/api/profiles/does-not-exist")
            assert r.status_code == 404

    records = [r for r in caplog.records if r.name == "vision_ocr_detect.request"]
    msg = records[-1].getMessage()
    assert "status=404" in msg
    assert "path=/api/profiles/does-not-exist" in msg


def test_middleware_log_omits_params_when_endpoint_does_not_set_them(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Endpoints that don't populate `request.state.log_params` should
    produce a log line without the `params=` suffix (so non-detect
    routes don't carry empty noise)."""
    with caplog.at_level(logging.INFO, logger="vision_ocr_detect.request"):
        with _make_client() as client:
            r = client.get("/api/profiles/does-not-exist")
            assert r.status_code == 404

    records = [r for r in caplog.records if r.name == "vision_ocr_detect.request"]
    msg = records[-1].getMessage()
    assert "params=" not in msg, f"unexpected params in non-detect log: {msg}"


def test_middleware_log_includes_params_json_when_endpoint_sets_them(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An endpoint that stashes a dict on `request.state.log_params`
    should see it appear as `params=<json>` on the same log line —
    handy for grepping `/api/detect` calls by profile / options."""
    from fastapi.testclient import TestClient

    from vision_ocr_detect.main import create_app

    app = create_app()

    @app.get("/_test_params_echo")
    async def _echo(request: Request) -> dict:
        request.state.log_params = {
            "profile": "interpark-layout",
            "options": {"response_format": "json", "max_tokens": 4096},
        }
        return {"ok": True}

    with TestClient(app) as client:
        with caplog.at_level(logging.INFO, logger="vision_ocr_detect.request"):
            r = client.get("/_test_params_echo")
            assert r.status_code == 200, f"body: {r.text}"

    records = [r for r in caplog.records if r.name == "vision_ocr_detect.request"]
    msg = records[-1].getMessage()
    assert "params=" in msg
    # JSON payload is on the same line — assert both keys appear
    # in order, sorted by `sort_keys=True`.
    assert '"max_tokens": 4096' in msg
    assert '"options"' in msg
    assert '"profile": "interpark-layout"' in msg
    assert '"response_format": "json"' in msg