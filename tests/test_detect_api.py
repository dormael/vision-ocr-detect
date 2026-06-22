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


def test_max_tokens_upper_bound(client_with_fake) -> None:
    """max_tokens must be 1..16384. The cap was raised from 8192 → 16384
    after the requester hit it while measuring recall across 4 venues."""
    client, _ = client_with_fake
    _create_profile(client)

    # Below the cap: accepted (we don't care about the model's output for
    # this test; the FakeProvider is configured to return text unconditionally).
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({"max_tokens": 16384}),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text

    # Above the cap: 422.
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({"max_tokens": 16385}),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["detail"][0]["loc"] == ["max_tokens"]
    assert body["detail"][0]["ctx"]["le"] == 16384


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

        async def list_models(self):
            raise RuntimeError("upstream down")

        async def aclose(self):
            pass

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


# ----------------------------------------------------------------------
# markdown fence stripping in lenient parse (Bug 7)
# ----------------------------------------------------------------------


def test_response_format_strips_markdown_fence(client_with_fake) -> None:
    """VLMs often wrap JSON in ```json ... ``` fences. The server strips
    the fence before parsing so `parsed` is populated; the raw `text`
    field is preserved unchanged."""
    client, fake = client_with_fake
    fake.text = '```json\n{"stage_location": "TOP", "sections": []}\n```'
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
    assert body["parsed"] == {"stage_location": "TOP", "sections": []}
    # raw text must NOT be mutated — clients can still see the fence.
    assert body["text"] == '```json\n{"stage_location": "TOP", "sections": []}\n```'


def test_response_format_strips_bare_fence(client_with_fake) -> None:
    """Bare ``` (no language tag) must also be stripped."""
    client, fake = client_with_fake
    fake.text = '```\n{"a": 1}\n```'
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
    assert r.json()["parsed"] == {"a": 1}


# ----------------------------------------------------------------------
# top-level seed (Bug 6)
# ----------------------------------------------------------------------


def test_top_level_seed_forwarded_to_provider(client_with_fake) -> None:
    client, fake = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({"seed": 42}),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text
    assert fake.calls[0]["seed"] == 42


def test_request_seed_beats_override_seed(client_with_fake) -> None:
    """Request-level seed wins over profile_override.seed, like temperature."""
    client, fake = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({
                "seed": 7,
                "profile_override": {"seed": 99},
            }),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200
    assert fake.calls[0]["seed"] == 7


def test_override_seed_fills_when_request_omits(client_with_fake) -> None:
    """Without top-level seed, profile_override.seed fills in."""
    client, fake = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({"profile_override": {"seed": 99}}),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200
    assert fake.calls[0]["seed"] == 99


# ----------------------------------------------------------------------
# response_format = json_schema (full OpenAI-style structured output)
# ----------------------------------------------------------------------


def test_response_format_json_schema_validates_payload(client_with_fake) -> None:
    """Schema-conformant output → parsed populated, provider sees dict form."""
    client, fake = client_with_fake
    schema = {
        "type": "object",
        "properties": {
            "stage_location": {"type": "string", "enum": ["TOP", "BOTTOM"]},
            "sections": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["stage_location", "sections"],
    }
    fake.text = '{"stage_location": "TOP", "sections": []}'
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "layout", "schema": schema},
                }
            }),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parsed"] == {"stage_location": "TOP", "sections": []}
    # raw text preserved
    assert body["text"] == '{"stage_location": "TOP", "sections": []}'
    # Provider received the dict form (not a string), so ollama can use
    # it as a structured-output constraint.
    rf = fake.calls[0]["response_format"]
    assert isinstance(rf, dict)
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "layout"


def test_response_format_json_schema_validation_failure_returns_422(client_with_fake) -> None:
    """Output that doesn't match the schema → 422 with raw text in detail."""
    client, fake = client_with_fake
    schema = {
        "type": "object",
        "properties": {"stage_location": {"type": "string"}},
        "required": ["stage_location"],
    }
    # Missing required field "stage_location" AND extra unknown field.
    fake.text = '{"unrelated": "value"}'
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "layout", "schema": schema},
                }
            }),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert "raw" in body["detail"]  # raw text included for debugging
    assert "unrelated" in body["detail"]


def test_response_format_json_schema_strips_markdown_fence(client_with_fake) -> None:
    """```json ... ``` wrappers are stripped before schema validation."""
    client, fake = client_with_fake
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
    }
    fake.text = '```json\n{"ok": true}\n```'
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "x", "schema": schema},
                }
            }),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["parsed"] == {"ok": True}


def test_response_format_json_schema_invalid_json_returns_422(client_with_fake) -> None:
    """JSON parse failure with json_schema → 422 (not silent null)."""
    client, fake = client_with_fake
    fake.text = "not even json {"
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "x", "schema": {"type": "object"}},
                }
            }),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 422, r.text


def test_response_format_json_schema_accepts_complex_schema(client_with_fake) -> None:
    """Realistic seat_layout schema from the feature request."""
    client, fake = client_with_fake
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "stage_location": {
                "type": "string",
                "enum": ["TOP", "BOTTOM", "LEFT", "RIGHT", "CENTER"],
            },
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "distance_tier": {"type": "integer", "minimum": 1, "maximum": 5},
                        "horizontal_alignment": {"type": "integer"},
                        "floor": {"type": "string", "enum": ["FLOOR", "2F", "3F"]},
                        "diagonal_tier": {"type": "integer", "minimum": 0, "maximum": 3},
                    },
                    "required": ["name", "distance_tier", "horizontal_alignment", "floor"],
                },
            },
        },
        "required": ["stage_location", "sections"],
    }
    fake.text = json.dumps({
        "stage_location": "TOP",
        "sections": [
            {"name": "S1", "distance_tier": 1, "horizontal_alignment": -1, "floor": "FLOOR"},
            {"name": "211", "distance_tier": 2, "horizontal_alignment": 0, "floor": "2F"},
        ],
    })
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "seat_layout", "schema": schema},
                }
            }),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parsed"]["stage_location"] == "TOP"
    assert len(body["parsed"]["sections"]) == 2


def test_response_format_json_schema_invalid_schema_falls_back(client_with_fake) -> None:
    """A malformed $schema object → server accepts the dict as best-effort
    rather than rejecting the request outright. The 'strict' validation
    is best-effort by design."""
    client, fake = client_with_fake
    fake.text = '{"anything": "goes"}'
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "x", "schema": {"type": "invalid-type"}},
                }
            }),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    # Malformed schema → server returns 200 with parsed populated
    # (we treat 'invalid schema' as 'no validation applied' to avoid
    # blocking the request on a server-side config issue).
    assert r.status_code == 200, r.text
    assert r.json()["parsed"] == {"anything": "goes"}


# ----------------------------------------------------------------------
# lenient JSON parser — production-grade quirk tolerance
# ----------------------------------------------------------------------


def test_response_format_json_normalizes_plus_signed_int(client_with_fake) -> None:
    """': +N' is rejected by json.loads per RFC 8259, but VLMs emit it
    from coordinate math. The lenient parser must drop the leading plus."""
    client, fake = client_with_fake
    fake.text = '{"stage_location": "TOP", "alignment": +2, "offset": +0}'
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
    assert body["parsed"] == {"stage_location": "TOP", "alignment": 2, "offset": 0}
    # raw text untouched
    assert body["text"] == fake.text


def test_response_format_json_normalizes_trailing_comma(client_with_fake) -> None:
    client, fake = client_with_fake
    fake.text = '{"a": 1, "b": [1, 2, 3,],}'
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
    assert r.json()["parsed"] == {"a": 1, "b": [1, 2, 3]}


def test_response_format_json_normalizes_double_comma(client_with_fake) -> None:
    client, fake = client_with_fake
    fake.text = '{"a": 1,, "b": 2}'
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
    assert r.json()["parsed"] == {"a": 1, "b": 2}


def test_response_format_json_fence_plus_combo(client_with_fake) -> None:
    """Realistic VLM output: fence + signed ints + trailing comma.

    This is the case the requester reported as 'Bug 7 not working'
    in feature-bugs-followup.md — the actual root cause is the signed
    integer, not the fence strip (which works)."""
    client, fake = client_with_fake
    fake.text = (
        '```json\n'
        '{"stage_location": "TOP", "sections": [\n'
        '  {"name": "S1", "alignment": +2, "tier": 1,},\n'
        '  {"name": "S2", "alignment": -1, "tier": 1,}\n'
        ']}\n'
        '```'
    )
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
    assert body["parsed"]["stage_location"] == "TOP"
    assert body["parsed"]["sections"][0]["alignment"] == 2
    assert body["parsed"]["sections"][1]["alignment"] == -1
    # raw text still preserves the fence and quirks
    assert body["text"] == fake.text


def test_response_format_json_schema_uses_lenient_parse_too(client_with_fake) -> None:
    """json_schema mode also benefits from lenient quirks — a model that
    emits ': +N' should still trigger schema validation, not a hard 422."""
    client, fake = client_with_fake
    schema = {
        "type": "object",
        "properties": {"alignment": {"type": "integer"}},
        "required": ["alignment"],
    }
    fake.text = '{"alignment": +2,}'
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "x", "schema": schema},
                }
            }),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["parsed"] == {"alignment": 2}


def test_response_format_json_schema_drops_explicit_null_for_optional_field(
    client_with_fake,
) -> None:
    """A model that emits `\"field\": null` for an optional field (instead
    of omitting it) should not trigger 422. The retry step drops the null
    and revalidates against the schema — null and missing are treated as
    equivalent for non-required fields."""
    client, fake = client_with_fake
    schema = {
        "type": "object",
        "properties": {
            "stage_location": {"type": "string", "enum": ["TOP", "BOTTOM"]},
            "special": {"type": "string", "enum": ["wheelchair", "obstructed"]},
        },
        "required": ["stage_location"],
    }
    # `special: null` violates the enum, but `special` is not required —
    # dropping it should make validation pass.
    fake.text = '{"stage_location": "TOP", "special": null}'
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "layout", "schema": schema},
                }
            }),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # null is dropped from parsed
    assert body["parsed"] == {"stage_location": "TOP"}
    # raw text still preserves the original model output for debugging
    assert body["text"] == '{"stage_location": "TOP", "special": null}'


def test_response_format_json_schema_required_null_still_returns_422(
    client_with_fake,
) -> None:
    """If a required field is null, dropping it doesn't help → 422."""
    client, fake = client_with_fake
    schema = {
        "type": "object",
        "properties": {"stage_location": {"type": "string"}},
        "required": ["stage_location"],
    }
    fake.text = '{"stage_location": null}'
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "layout", "schema": schema},
                }
            }),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 422, r.text
    assert "raw" in r.json()["detail"]


def test_response_format_json_schema_null_in_array_item_is_dropped(
    client_with_fake,
) -> None:
    """The null-drop retry walks into nested arrays — null inside an
    `items` array gets dropped alongside null values at the top level."""
    client, fake = client_with_fake
    schema = {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
        "required": ["sections"],
    }
    # outer-level null: fails schema; cleaned dict has no top-level nulls
    # because the outer-level field already passes. inner null in items[1]:
    # after dropping, the array item has no `name` → required violation
    # stays in items[1]. To verify the array walk we instead use a schema
    # where the offending null is in an optional inner field.
    schema_optional = {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "tag": {"type": "string", "enum": ["A"]},
                    },
                    "required": ["name"],
                },
            },
        },
        "required": ["sections"],
    }
    fake.text = (
        '{"sections": ['
        '{"name": "S1", "tag": "A"},'
        '{"name": "S2", "tag": null}'
        ']}'
    )
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": "layout", "schema": schema_optional},
                }
            }),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # S1's tag is non-null ("A"), preserved as-is.
    # S2's tag is null and dropped from the parsed output.
    assert body["parsed"] == {
        "sections": [
            {"name": "S1", "tag": "A"},
            {"name": "S2"},
        ]
    }


def test_response_format_json_preserves_raw_text(client_with_fake) -> None:
    """The lenient parser must NEVER mutate the text field — clients may
    rely on raw output for debugging or their own re-parse."""
    client, fake = client_with_fake
    raw_text = '```json\n{"alignment": +2}\n```'
    fake.text = raw_text
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({"response_format": "json"}),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.json()["text"] == raw_text


# ----------------------------------------------------------------------
# response metadata (#7): tokens_in/out, cost_usd, seed_used
# ----------------------------------------------------------------------


def _client_with_usage(client_with_fake, *, tokens_in: int | None, tokens_out: int | None):
    """Re-bind the dependency override to a FakeProvider that reports usage."""
    client, default_fake = client_with_fake
    from vision_ocr_detect import deps as deps_mod
    from vision_ocr_detect.providers.registry import ProviderRegistry

    fake = default_fake.__class__(
        default_fake.name,
        text=default_fake.text,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    registry = ProviderRegistry()
    registry.register(default_fake.name, fake)
    client.app.dependency_overrides[deps_mod.get_provider_registry] = lambda: registry
    return client


def test_response_includes_seed_used_echoed(client_with_fake) -> None:
    """seed_used reflects what we forwarded to the provider (or None)."""
    client, fake = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({"seed": 42}),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["seed_used"] == 42


def test_response_includes_seed_used_from_override(client_with_fake) -> None:
    client, fake = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={
            "profile": "ocr",
            "options": json.dumps({"profile_override": {"seed": 99}}),
        },
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200
    assert r.json()["seed_used"] == 99


def test_response_seed_used_none_when_no_seed(client_with_fake) -> None:
    client, fake = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={"profile": "ocr"},
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200
    assert r.json()["seed_used"] is None


def test_response_includes_tokens_in_out_when_provider_reports(client_with_fake) -> None:
    client = _client_with_usage(client_with_fake, tokens_in=1024, tokens_out=512)
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={"profile": "ocr"},
        files={"image": ("img.png", _png(), "image/png")},
    )
    body = r.json()
    assert body["tokens_in"] == 1024
    assert body["tokens_out"] == 512


def test_response_tokens_null_when_provider_does_not_report(client_with_fake) -> None:
    client = _client_with_usage(client_with_fake, tokens_in=None, tokens_out=None)
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={"profile": "ocr"},
        files={"image": ("img.png", _png(), "image/png")},
    )
    body = r.json()
    assert body["tokens_in"] is None
    assert body["tokens_out"] is None
    assert body["cost_usd"] is None  # can't compute without token counts


def test_response_cost_usd_zero_for_local_ollama(client_with_fake) -> None:
    """Ollama is free; with usage reported, cost_usd must be exactly 0.0."""
    client = _client_with_usage(client_with_fake, tokens_in=1000, tokens_out=500)
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={"profile": "ocr"},
        files={"image": ("img.png", _png(), "image/png")},
    )
    body = r.json()
    assert body["tokens_in"] == 1000
    assert body["tokens_out"] == 500
    assert body["cost_usd"] == 0.0


def test_response_metadata_does_not_break_existing_response_shape(client_with_fake) -> None:
    """All previous fields still present; new fields are additive optionals."""
    client, fake = client_with_fake
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={"profile": "ocr", "options": json.dumps({"response_format": "json"})},
        files={"image": ("img.png", _png(), "image/png")},
    )
    body = r.json()
    # Existing fields (regression check)
    assert set(body.keys()) >= {
        "text", "profile", "model", "provider",
        "elapsed_ms", "parsed",
    }
    # New fields exist (may be None)
    for k in ("tokens_in", "tokens_out", "cost_usd", "seed_used"):
        assert k in body


def test_cost_usd_computed_for_paid_provider(tmp_path, monkeypatch):
    """A provider with non-zero per-token pricing produces non-zero cost.

    Uses a custom config.json + dependency override to inject a paid
    provider config without changing the default ollama setup.
    """
    import json

    from vision_ocr_detect.config import ProviderConfig, Settings
    from vision_ocr_detect import deps as deps_mod
    from vision_ocr_detect import main as main_mod
    from vision_ocr_detect.providers.registry import ProviderRegistry
    from fastapi.testclient import TestClient

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "server": {"host": "127.0.0.1", "port": 8765, "max_concurrent_requests": 2},
        "providers": {
            "paid": {
                "type": "ollama",
                "base_url": "http://localhost:11434",
                "timeout_seconds": 30,
                # $0.001 per 1k input, $0.002 per 1k output
                "cost_per_1k_input_tokens": 0.001,
                "cost_per_1k_output_tokens": 0.002,
            }
        },
    }), encoding="utf-8")
    profiles_path = tmp_path / "profiles.json"
    profiles_path.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("VISION_OCR_CONFIG", str(config_path))
    monkeypatch.setenv("VISION_OCR_PROFILES", str(profiles_path))

    settings = Settings.model_validate(json.loads(config_path.read_text()))

    from vision_ocr_detect.providers.ollama import OllamaProvider
    from tests.conftest import FakeProvider

    fake = FakeProvider(
        "paid",
        text="ok",
        tokens_in=2000,
        tokens_out=1000,
    )
    registry = ProviderRegistry()
    registry.register("paid", fake)

    app = main_mod.create_app(settings=settings)
    app.dependency_overrides[deps_mod.get_provider_registry] = lambda: registry

    with TestClient(app) as c:
        # Profile + call
        c.post("/api/profiles", json={
            "name": "p", "provider": "paid", "model": "m", "prompt": "p",
        })
        r = c.post(
            "/api/detect",
            data={"profile": "p"},
            files={"image": ("i.png", _png(), "image/png")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # 2000/1000 * 0.001 = 0.002
        # 1000/1000 * 0.002 = 0.002
        # Total = 0.004
        assert body["cost_usd"] == 0.004


# ----------------------------------------------------------------------
# OllamaProvider native-first / OpenAI-compat fallback (Option C)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_provider_uses_native_endpoint_by_default(respx_mock):
    """When /api/generate returns 200, we use it and report native."""
    from vision_ocr_detect.config import ProviderConfig
    from vision_ocr_detect.providers.ollama import OllamaProvider

    respx_mock.post("http://localhost:11434/api/generate").respond(
        json={
            "response": "hello",
            "prompt_eval_count": 100,
            "eval_count": 10,
        }
    )
    p = OllamaProvider("local-ollama", ProviderConfig(
        type="ollama", base_url="http://localhost:11434", timeout_seconds=5
    ))
    try:
        result = await p.detect(b"img", "image/png", "m", "p")
    finally:
        await p.aclose()
    assert result.text == "hello"
    assert result.endpoint_used == "native"
    assert result.tokens_in == 100
    assert result.tokens_out == 10


@pytest.mark.asyncio
async def test_ollama_provider_falls_back_to_openai_compat_on_404(respx_mock):
    """Native 404 → OpenAI-compat succeeds. result.endpoint_used='openai'."""
    from vision_ocr_detect.config import ProviderConfig
    from vision_ocr_detect.providers.ollama import OllamaProvider

    respx_mock.post("http://localhost:11434/api/generate").respond(404)
    openai = respx_mock.post(
        "http://localhost:11434/v1/chat/completions"
    ).respond(
        json={
            "choices": [{"message": {"content": "fallback ok"}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 5},
        }
    )
    p = OllamaProvider("local-ollama", ProviderConfig(
        type="ollama", base_url="http://localhost:11434", timeout_seconds=5
    ))
    try:
        result = await p.detect(b"img", "image/png", "m", "p")
    finally:
        await p.aclose()
    assert result.text == "fallback ok"
    assert result.endpoint_used == "openai"
    assert result.tokens_in == 50
    assert result.tokens_out == 5
    assert openai.call_count == 1


@pytest.mark.asyncio
async def test_ollama_provider_falls_back_on_model_not_found_body(respx_mock):
    """Some ollama builds return 200 + body.error='model \"x\" not found'.
    Detect that and fall back to OpenAI-compat."""
    from vision_ocr_detect.config import ProviderConfig
    from vision_ocr_detect.providers.ollama import OllamaProvider

    respx_mock.post("http://localhost:11434/api/generate").respond(
        400, json={"error": 'model "missing" not found, try pulling it first'}
    )
    respx_mock.post("http://localhost:11434/v1/chat/completions").respond(
        json={"choices": [{"message": {"content": "from openai"}}]}
    )
    p = OllamaProvider("local-ollama", ProviderConfig(
        type="ollama", base_url="http://localhost:11434", timeout_seconds=5
    ))
    try:
        result = await p.detect(b"img", "image/png", "m", "p")
    finally:
        await p.aclose()
    assert result.endpoint_used == "openai"


@pytest.mark.asyncio
async def test_ollama_provider_native_error_500_does_not_fallback(respx_mock):
    """A non-404 / non-model-not-found error on native should NOT trigger
    the fallback — it gets re-raised so the API layer returns 502."""
    from vision_ocr_detect.config import ProviderConfig
    from vision_ocr_detect.providers.ollama import OllamaProvider

    respx_mock.post("http://localhost:11434/api/generate").respond(500)
    respx_mock.post("http://localhost:11434/v1/chat/completions").respond(200)
    p = OllamaProvider("local-ollama", ProviderConfig(
        type="ollama", base_url="http://localhost:11434", timeout_seconds=5
    ))
    try:
        import httpx
        with pytest.raises(httpx.HTTPStatusError):
            await p.detect(b"img", "image/png", "m", "p")
    finally:
        await p.aclose()


@pytest.mark.asyncio
async def test_ollama_provider_native_body_error_is_runtimeerror(respx_mock):
    """A 200 + body.error='out of memory' should bubble up as RuntimeError,
    NOT silently fall back to OpenAI-compat."""
    from vision_ocr_detect.config import ProviderConfig
    from vision_ocr_detect.providers.ollama import OllamaProvider

    respx_mock.post("http://localhost:11434/api/generate").respond(
        200, json={"error": "out of memory", "response": ""}
    )
    respx_mock.post("http://localhost:11434/v1/chat/completions").respond(200)
    p = OllamaProvider("local-ollama", ProviderConfig(
        type="ollama", base_url="http://localhost:11434", timeout_seconds=5
    ))
    try:
        with pytest.raises(RuntimeError, match="out of memory"):
            await p.detect(b"img", "image/png", "m", "p")
    finally:
        await p.aclose()


def test_response_includes_endpoint_used(client_with_fake):
    client, _ = client_with_fake
    # client_with_fake's FakeProvider defaults to endpoint_used="fake"
    _create_profile(client)
    r = client.post(
        "/api/detect",
        data={"profile": "ocr"},
        files={"image": ("img.png", _png(), "image/png")},
    )
    assert r.status_code == 200
    assert r.json()["endpoint_used"] == "fake"
