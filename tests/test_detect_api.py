"""End-to-end tests for /api/detect with a fake provider."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image


def _png(color=(255, 0, 0), size=64) -> bytes:
    img = Image.new("RGB", (size, size), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _create_profile(client, name="ocr", **overrides) -> None:
    body = {
        "name": name,
        "provider": "local-ollama",
        "model": "test-model",
        "prompt": "Extract text.",
    }
    body.update(overrides)
    r = client.post("/api/profiles", json=body)
    assert r.status_code == 201, r.text


def test_detect_returns_extracted_text(client_with_fake) -> None:
    client, fake = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={"profile": "ocr"},
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == "extracted text"
    assert body["profile"] == "ocr"
    assert body["model"] == "test-model"
    assert body["provider"] == "local-ollama"
    assert body["elapsed_ms"] >= 0
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["model"] == "test-model"
    assert call["prompt"] == "Extract text."
    assert call["mime_type"] == "image/png"
    assert call["max_tokens"] is None
    assert call["temperature"] is None


def test_detect_with_options_passes_through(client_with_fake) -> None:
    client, fake = client_with_fake
    _create_profile(client)
    options = json.dumps({
        "image": {"format": "jpeg", "scale": 0.5},
        "max_tokens": 64,
        "temperature": 0.0,
    })
    r = client.post(
        "/api/detect",
        data={"profile": "ocr", "options": options},
        files={"image": ("img.png", _png(size=200), "image/png")},
    )
    assert r.status_code == 200, r.text
    call = fake.calls[0]
    # After scale=0.5 + format=jpeg, the bytes are smaller and mime is jpeg.
    assert call["mime_type"] == "image/jpeg"
    assert call["max_tokens"] == 64
    assert call["temperature"] == 0.0


def test_detect_profile_not_found(client_with_fake) -> None:
    client, _ = client_with_fake
    r = client.post(
        "/api/detect",
        data={"profile": "ghost"},
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 404
    assert "ghost" in r.json()["detail"]


def test_detect_invalid_image(client_with_fake) -> None:
    client, _ = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={"profile": "ocr"},
        files={"image": ("bad.png", b"not an image", "image/png")},
    )
    assert r.status_code == 422


def test_detect_invalid_options_json(client_with_fake) -> None:
    client, _ = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={"profile": "ocr", "options": "{not-json}"},
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 422
    assert "JSON" in r.json()["detail"]


def test_detect_invalid_options_content(client_with_fake) -> None:
    client, _ = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={"profile": "ocr", "options": json.dumps({"max_tokens": -1})},
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 422


def test_detect_missing_profile_field(client_with_fake) -> None:
    client, _ = client_with_fake
    r = client.post(
        "/api/detect",
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 422


def test_detect_missing_image_field(client_with_fake) -> None:
    client, _ = client_with_fake
    _create_profile(client)
    r = client.post("/api/detect", data={"profile": "ocr"})
    assert r.status_code == 422


def test_detect_provider_failure_returns_502(client_with_fake) -> None:
    client, fake = client_with_fake

    class BoomProvider:
        name = "local-ollama"

        async def detect(self, *args, **kwargs):
            raise RuntimeError("upstream down")

    # Swap the fake registry via the same override mechanism.
    from vision_ocr_detect import deps as deps_mod
    from vision_ocr_detect.providers.registry import ProviderRegistry

    new_registry = ProviderRegistry()
    new_registry.register("local-ollama", BoomProvider())
    client.app.dependency_overrides[deps_mod.get_provider_registry] = lambda: new_registry

    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={"profile": "ocr"},
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 502
    assert "upstream down" in r.json()["detail"]


# ----------------------------------------------------------------------
# profile_override
# ----------------------------------------------------------------------


def test_profile_override_changes_model_and_prompt(client_with_fake) -> None:
    client, fake = client_with_fake
    _create_profile(client, name="ocr", model="orig-model", prompt="orig prompt")
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({
                "profile_override": {"model": "exp-model", "prompt": "exp prompt"}
            }),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "exp-model"
    call = fake.calls[0]
    assert call["model"] == "exp-model"
    assert call["prompt"] == "exp prompt"


def test_profile_override_temperature_and_seed(client_with_fake) -> None:
    client, fake = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({
                "profile_override": {"temperature": 0.0, "seed": 42}
            }),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text
    call = fake.calls[0]
    assert call["temperature"] == 0.0
    assert call["seed"] == 42


def test_request_level_temperature_beats_override(client_with_fake) -> None:
    client, fake = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({
                "temperature": 0.7,
                "profile_override": {"temperature": 0.0, "seed": 1},
            }),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200
    call = fake.calls[0]
    assert call["temperature"] == 0.7  # request wins
    assert call["seed"] == 1          # override-only


def test_profile_override_unknown_provider_returns_400(client_with_fake) -> None:
    client, _ = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({"profile_override": {"provider": "ghost"}}),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 400
    assert "ghost" in r.json()["detail"]


def test_profile_override_validation(client_with_fake) -> None:
    """Bad types in override → 422 (caught by Pydantic)."""
    client, _ = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({"profile_override": {"seed": "not-an-int"}}),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 422


# ----------------------------------------------------------------------
# response_format / parsed
# ----------------------------------------------------------------------


def test_response_format_json_parses_dict(client_with_fake) -> None:
    client, fake = client_with_fake
    fake.text = '{"stage_location": "TOP", "sections": []}'
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({"response_format": "json"}),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["text"] == '{"stage_location": "TOP", "sections": []}'
    assert body["parsed"] == {"stage_location": "TOP", "sections": []}
    call = fake.calls[0]
    assert call["response_format"] == "json"


def test_response_format_invalid_json_returns_null(client_with_fake) -> None:
    client, fake = client_with_fake
    fake.text = "not even json {"
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({"response_format": "json"}),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["parsed"] is None
    # raw text is preserved for the client to handle.
    assert body["text"] == "not even json {"


def test_response_format_non_object_returns_null(client_with_fake) -> None:
    """Valid JSON but not an object (e.g. array, scalar) → parsed is null."""
    client, fake = client_with_fake
    fake.text = "[1, 2, 3]"
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({"response_format": "json"}),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200
    assert r.json()["parsed"] is None


def test_response_format_default_returns_null(client_with_fake) -> None:
    """Without response_format, parsed is always null (regardless of text)."""
    client, fake = client_with_fake
    fake.text = '{"a": 1}'  # looks like JSON but the call didn't ask for it.
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={"profile": "ocr"},
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["parsed"] is None
    assert body["text"] == '{"a": 1}'
    assert fake.calls[0]["response_format"] is None
