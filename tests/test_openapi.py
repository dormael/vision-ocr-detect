"""OpenAPI schema regression tests.

These guard the documentation metadata added in the
"API documentation hardening" work. They don't test runtime
behavior — that's covered elsewhere. A failure here means a
regression in the /docs / /redoc surface.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _schema(client: TestClient) -> dict:
    return client.get("/openapi.json").json()


def test_openapi_title_and_version(client_with_fake) -> None:
    client, _ = client_with_fake
    schema = _schema(client)
    assert schema["info"]["title"] == "vision-ocr-detect"
    assert schema["info"]["version"] == "0.1.0"


def test_openapi_description_non_empty_markdown(client_with_fake) -> None:
    client, _ = client_with_fake
    schema = _schema(client)
    desc = schema["info"].get("description", "")
    assert desc.strip(), "app description must not be empty"
    # Must mention a key concept so /docs readers get oriented.
    assert "profile" in desc.lower()
    assert "provider" in desc.lower()


def test_openapi_tags_have_descriptions(client_with_fake) -> None:
    client, _ = client_with_fake
    schema = _schema(client)
    tags_by_name = {t["name"]: t for t in schema.get("tags", [])}
    for name in ("detect", "profiles", "models"):
        assert name in tags_by_name, f"missing tag {name!r}"
        desc = tags_by_name[name].get("description", "")
        assert desc.strip(), f"tag {name!r} description must not be empty"


def test_openapi_contact_present(client_with_fake) -> None:
    client, _ = client_with_fake
    schema = _schema(client)
    contact = schema["info"].get("contact") or {}
    assert contact.get("name") or contact.get("url"), "contact info missing"