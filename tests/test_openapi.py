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