"""OpenAPI schema regression tests.

These guard the documentation metadata added in the
"API documentation hardening" work. They don't test runtime
behavior — that's covered elsewhere. A failure here means a
regression in the /docs / /redoc surface.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from vision_ocr_detect.models.detect import (
    DetectResponse,
    JsonSchemaResponseFormat,
    JsonSchemaSpec,
)
from vision_ocr_detect.models.models import ModelsResponse, ProviderModels
from vision_ocr_detect.models.profile import Profile, ProfileCreate, ProfileUpdate


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


@pytest.mark.parametrize(
    "model_cls",
    [
        DetectResponse,
        JsonSchemaSpec,
        JsonSchemaResponseFormat,
        Profile,
        ProfileCreate,
        ProfileUpdate,
        ProviderModels,
        ModelsResponse,
    ],
)
def test_model_has_examples(model_cls) -> None:
    schema = model_cls.model_json_schema()
    examples = schema.get("examples")
    assert examples, f"{model_cls.__name__} missing examples in JSON schema"
    assert isinstance(examples, list) and examples, (
        f"{model_cls.__name__} examples must be a non-empty list"
    )


def test_detect_response_example_validates() -> None:
    schema = DetectResponse.model_json_schema()
    example = schema["examples"][0]
    # Pydantic must accept its own documented example.
    DetectResponse.model_validate(example)


def test_profile_create_example_validates() -> None:
    schema = ProfileCreate.model_json_schema()
    example = schema["examples"][0]
    ProfileCreate.model_validate(example)


def test_profile_update_example_validates() -> None:
    schema = ProfileUpdate.model_json_schema()
    ProfileUpdate.model_validate(schema["examples"][0])


EXPECTED_SUMMARIES: dict[str, str] = {
    "/health": "Liveness + capability snapshot",
    "/api/profiles": "List profiles (optional ?tag= filter)",
    "/api/profiles/{name}": "Get one profile by name",
    "/api/models": "List models per provider (optional vision_only filter)",
    "/api/providers/{name}/models": "List models for one provider",
}


def _routes_by_path(client: TestClient) -> dict[str, dict]:
    schema = _schema(client)
    return {path: route for path, route in schema["paths"].items()}


@pytest.mark.parametrize("path,expected_substring", list(EXPECTED_SUMMARIES.items()))
def test_route_summary_present(
    client_with_fake, path: str, expected_substring: str
) -> None:
    client, _ = client_with_fake
    routes = _routes_by_path(client)
    assert path in routes, f"missing route {path}"
    # Each path can have multiple methods; at least one must carry the summary.
    methods = routes[path]
    summaries = [
        method_meta.get("summary", "")
        for method_meta in methods.values()
        if isinstance(method_meta, dict)
    ]
    assert any(expected_substring in s for s in summaries), (
        f"route {path}: expected summary containing {expected_substring!r}, "
        f"got {summaries}"
    )


def test_detect_route_description_mentions_json_modes(client_with_fake) -> None:
    client, _ = client_with_fake
    routes = _routes_by_path(client)
    post = routes["/api/detect"]["post"]
    desc = (post.get("description") or "").lower()
    assert "json" in desc, "detect description should mention JSON modes"
    assert "schema" in desc, "detect description should mention json_schema"


def test_detect_route_documents_422_truncation_signature(client_with_fake) -> None:
    client, _ = client_with_fake
    routes = _routes_by_path(client)
    post = routes["/api/detect"]["post"]
    # The 422 response description or summary should reference truncation.
    blob = " ".join(
        [
            post.get("summary", "") or "",
            post.get("description", "") or "",
            (post.get("responses", {}).get("422", {}) or {}).get("description", "") or "",
        ]
    ).lower()
    assert "truncation" in blob or "text_length" in blob, (
        "detect route must surface the 422 truncation signature in some field"
    )