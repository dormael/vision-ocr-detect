# API Documentation Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill API-consumer-facing documentation gaps by enriching FastAPI metadata, Pydantic model examples, route descriptions, and a few README sections — without changing any runtime behavior.

**Architecture:** Four-layer, documentation-only PR. Layer 1 (FastAPI app metadata) and Layer 4 (README + `.env.example`) sit at the outermost boundary; Layer 2 (Pydantic examples) and Layer 3 (route descriptions) sit one level inside. Each layer has its own TDD micro-cycle (test → fail → implement → pass → commit) so reviewers see one boundary per commit.

**Tech Stack:** FastAPI 0.138+, Pydantic v2, pydantic-settings, pytest 9+.

---

## File Structure

**Modify:**
- `src/vision_ocr_detect/main.py` — `create_app()` constructor (Layer 1); `/health` route summary/description (Layer 3)
- `src/vision_ocr_detect/models/detect.py` — examples on `DetectResponse`, `JsonSchemaSpec`, `JsonSchemaResponseFormat` (Layer 2)
- `src/vision_ocr_detect/models/profile.py` — examples on `Profile`, `ProfileCreate`, `ProfileUpdate` (Layer 2)
- `src/vision_ocr_detect/models/models.py` — examples on `ProviderModels`, `ModelsResponse` (Layer 2)
- `src/vision_ocr_detect/api/detect.py` — summary/description/response_description on `POST /api/detect` (Layer 3)
- `src/vision_ocr_detect/api/profiles.py` — summary on 5 routes (Layer 3)
- `src/vision_ocr_detect/api/models.py` — summary on 2 routes (Layer 3)
- `README.md` — section extensions for 422 signature, 20 MiB cap, env vars, provider internals, middleware (Layer 4)

**Create:**
- `tests/test_openapi.py` — OpenAPI schema assertions (Layers 1–3 regression coverage)
- `.env.example` — example env file (Layer 4)

**Out of scope (no touch):** `src/vision_ocr_detect/providers/*`, `src/vision_ocr_detect/services/*`, `src/vision_ocr_detect/__init__.py`, `config.example.json`, `profiles.example.json`, `fixtures/`, `collab-log.md`, `continue-prompt.md`.

---

## Global Constraints

- Documentation-only changes. No runtime behavior, no schema validation, no persistence logic, no provider logic changes.
- Pydantic `ConfigDict(extra="forbid")` must be preserved on all models. Add `json_schema_extra={"examples": [...]}` alongside it (do not replace).
- FastAPI route handlers keep their existing signatures, dependencies, and return types. Only add `summary=`, `description=`, `response_description=` keyword arguments.
- README additions must keep the existing markdown structure (no reordered sections, no renamed anchors).
- `.env.example` is committed to git. `.env` stays in `.gitignore` (already excluded at `/.env`).
- Commit messages follow existing repo convention: `<type>(<scope>): <subject>` for code, `docs(...)` for documentation.
- Run `uv run pytest` after each task. Existing 137 unit/integration tests must still pass (`uv run pytest --ignore=tests/test_provider_smoke.py`); the smoke test is exercised separately and is out of scope for this work.
- The `client_with_fake` fixture in `tests/conftest.py` provides a `TestClient` with monkeypatched config/profiles paths and a `FakeProvider` in place of `OllamaProvider`. New tests in `tests/test_openapi.py` MUST use this fixture (or the same `monkeypatch_env` + `create_app(settings=...)` + `dependency_overrides` pattern) — importing the module-level `app` from `vision_ocr_detect.main` would trigger the real lifespan, which expects a reachable ollama instance and a real `config.json`. See `tests/conftest.py:131-151` for the canonical pattern.
- No new dependencies; this work uses stdlib + already-installed packages.

---

## Task 1: Layer 1 — FastAPI App Metadata

**Files:**
- Modify: `src/vision_ocr_detect/main.py:114-121` (the `FastAPI(...)` constructor inside `create_app`)
- Test: `tests/test_openapi.py` (new file)

**Interfaces:**
- Consumes: existing `create_app(settings: Settings | None = None) -> FastAPI` signature (unchanged).
- Produces: `app.title == "vision-ocr-detect"`, `app.version == "0.1.0"`, `app.openapi()["info"]["description"]` non-empty Markdown, `app.openapi()["tags"]` includes `detect`, `profiles`, `models` each with a non-empty description, `app.openapi()["info"]["contact"]` non-empty.

- [ ] **Step 1: Write failing tests for Layer 1**

Create `tests/test_openapi.py`. Use the `client_with_fake` fixture from `tests/conftest.py` — it builds the app with monkeypatched config/profiles paths and a `FakeProvider` so the lifespan runs without touching the real network. **Do not import the module-level `app`** (that triggers the real lifespan with real providers).

```python
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
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `uv run pytest tests/test_openapi.py -v`
Expected: 4 failures (the existing `create_app()` lacks the description, tags, and contact fields).

- [ ] **Step 3: Enrich the FastAPI app constructor**

In `src/vision_ocr_detect/main.py`, replace the `FastAPI(...)` call inside `create_app()` (currently lines 116-121) with:

```python
        app = FastAPI(
            title="vision-ocr-detect",
            version="0.1.0",
            summary="Vision/OCR HTTP API wrapping local & hosted vision models",
            description=(
                "## Overview\n\n"
                "Run vision/OCR models over HTTP. Manage named profiles "
                "(provider + model + prompt) at runtime, then call "
                "`POST /api/detect` with an image to get extracted text back.\n\n"
                "## Quick start\n\n"
                "1. `uv sync && cp config.example.json config.json && "
                "cp profiles.example.json profiles.json`\n"
                "2. Edit `config.json` to point at your ollama instance\n"
                "3. `uv run vision-ocr-detect`\n"
                "4. OpenAPI/Swagger UI at `/docs`, ReDoc at `/redoc`\n\n"
                "## Key concepts\n\n"
                "- **Profile**: named bundle of (provider, model, prompt). "
                "Persisted to `profiles.json`.\n"
                "- **Provider**: backend (ollama local, openrouter cloud). "
                "Configured in `config.json`.\n"
                "- **Detect**: one-shot image-to-text call. "
                "Concurrency-capped per server.\n"
            ),
            openapi_tags=[
                {
                    "name": "detect",
                    "description": "Run vision/OCR on an image.",
                },
                {
                    "name": "profiles",
                    "description": "CRUD for named prompt+model bundles.",
                },
                {
                    "name": "models",
                    "description": "Enumerate available vision models.",
                },
            ],
            contact={
                "name": "vision-ocr-detect",
                "url": "https://github.com/dormael/vision-ocr-detect",
            },
            lifespan=lifespan,
        )
```

- [ ] **Step 4: Re-run Layer 1 tests; confirm pass**

Run: `uv run pytest tests/test_openapi.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Run the full suite; confirm no regression**

Run: `uv run pytest --ignore=tests/test_provider_smoke.py`
Expected: 137 existing tests pass + 4 new tests = 141 passing.

- [ ] **Step 6: Commit**

```bash
git add tests/test_openapi.py src/vision_ocr_detect/main.py
git commit -m "feat(openapi): app metadata — description, tags, contact

Enrich create_app()'s FastAPI(...) constructor so /docs and /redoc
render a Markdown overview, tag descriptions, and contact info.
Behavior unchanged. Adds tests/test_openapi.py with 4 regression tests."
```

---

## Task 2: Layer 2 — Pydantic Model Examples

**Files:**
- Modify: `src/vision_ocr_detect/models/detect.py` (DetectResponse, JsonSchemaSpec, JsonSchemaResponseFormat)
- Modify: `src/vision_ocr_detect/models/profile.py` (Profile, ProfileCreate, ProfileUpdate)
- Modify: `src/vision_ocr_detect/models/models.py` (ProviderModels, ModelsResponse)
- Test: `tests/test_openapi.py` (extend)

**Interfaces:**
- Consumes: existing model classes; `ConfigDict(extra="forbid")` constraint.
- Produces: each response/request model has `examples` in its JSON schema, with at least one entry that satisfies the field types.

- [ ] **Step 1: Extend `tests/test_openapi.py` with example-assertion tests**

Append to `tests/test_openapi.py`:

```python
import pytest

from vision_ocr_detect.models.detect import (
    DetectResponse,
    JsonSchemaResponseFormat,
    JsonSchemaSpec,
)
from vision_ocr_detect.models.models import ModelsResponse, ProviderModels
from vision_ocr_detect.models.profile import Profile, ProfileCreate, ProfileUpdate


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
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `uv run pytest tests/test_openapi.py -v`
Expected: 8 `test_model_has_examples` failures (one per model) + 2 example-validate failures.

- [ ] **Step 3: Add examples to `DetectResponse`, `JsonSchemaSpec`, `JsonSchemaResponseFormat`**

In `src/vision_ocr_detect/models/detect.py`:

- Replace `DetectResponse`'s `model_config` (currently absent — it's a plain `BaseModel`) with:

```python
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "text": '{"stage_location": "TOP", "sections": []}',
                    "parsed": {"stage_location": "TOP", "sections": []},
                    "profile": "interpark-layout",
                    "model": "qwen2.5vl:7b",
                    "provider": "local-ollama",
                    "elapsed_ms": 1247,
                    "tokens_in": 1024,
                    "tokens_out": 128,
                    "cost_usd": 0.0,
                    "seed_used": 42,
                    "endpoint_used": "native",
                }
            ]
        },
    )
```

- Replace `JsonSchemaSpec`'s existing `model_config` (currently `ConfigDict(extra="forbid")`) with:

```python
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "seat_layout",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "stage_location": {
                                "type": "string",
                                "enum": ["TOP", "BOTTOM", "LEFT", "RIGHT", "CENTER"],
                            },
                            "sections": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                        },
                        "required": ["stage_location", "sections"],
                    },
                    "strict": True,
                }
            ]
        },
    )
```

- Replace `JsonSchemaResponseFormat`'s existing `model_config` with:

```python
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "seat_layout",
                        "schema": {
                            "type": "object",
                            "properties": {"stage_location": {"type": "string"}},
                        },
                    },
                }
            ]
        },
    )
```

- [ ] **Step 4: Add examples to `Profile`, `ProfileCreate`, `ProfileUpdate`**

In `src/vision_ocr_detect/models/profile.py`:

- Replace `ProfileBase.model_config` (currently `ConfigDict(extra="forbid")`) with:

```python
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "ocr-default",
                    "provider": "local-ollama",
                    "model": "glm-ocr:latest",
                    "prompt": "Extract all text from this image.",
                    "description": "Default OCR profile for general text.",
                    "tags": ["ocr", "default"],
                }
            ]
        },
    )
```

(Note: `ProfileBase` is shared by `ProfileCreate`. Pydantic's `json_schema_extra` is inherited. To give `Profile` its own example with timestamps, define a separate `model_config` on `Profile` after the class body — see next bullet. The shared `ProfileBase` example above is what `ProfileCreate` will advertise.)

- Add a `model_config` to `Profile` (currently no `model_config` on `Profile` itself). Insert at the top of the class body:

```python
class Profile(ProfileBase):
    """Stored profile (includes timestamps)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "ocr-default",
                    "provider": "local-ollama",
                    "model": "glm-ocr:latest",
                    "prompt": "Extract all text from this image.",
                    "description": "Default OCR profile for general text.",
                    "tags": ["ocr", "default"],
                    "created_at": "2026-06-01T12:00:00Z",
                    "updated_at": "2026-06-25T09:00:00Z",
                }
            ]
        },
    )

    created_at: datetime
    updated_at: datetime
```

- Replace `ProfileUpdate.model_config` with:

```python
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"model": "qwen2.5vl:7b"},
                {"temperature": 0.0, "seed": 42, "description": None, "tags": []},
            ]
        },
    )
```

- [ ] **Step 5: Add examples to `ProviderModels`, `ModelsResponse`**

In `src/vision_ocr_detect/models/models.py`:

- Replace `ProviderModels.model_config` with:

```python
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "models": [
                        {
                            "name": "qwen2.5vl:7b",
                            "family": "qwen25vl",
                            "parameter_size": "7B",
                            "quantization_level": "Q4_0",
                            "context_length": 8192,
                            "vision_capable": True,
                            "source": "capabilities",
                        }
                    ]
                }
            ]
        },
    )
```

- Replace `ModelsResponse.model_config` with:

```python
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "providers": {
                        "local-ollama": {
                            "models": [
                                {
                                    "name": "qwen2.5vl:7b",
                                    "vision_capable": True,
                                    "source": "capabilities",
                                }
                            ]
                        }
                    }
                }
            ]
        },
    )
```

- [ ] **Step 6: Re-run the example tests; confirm pass**

Run: `uv run pytest tests/test_openapi.py -v`
Expected: all tests pass (4 from Layer 1 + 10 from Layer 2 = 14 tests).

- [ ] **Step 7: Run the full suite; confirm no regression**

Run: `uv run pytest --ignore=tests/test_provider_smoke.py`
Expected: 137 existing + 14 new = 151 passing.

- [ ] **Step 8: Commit**

```bash
git add tests/test_openapi.py \
  src/vision_ocr_detect/models/detect.py \
  src/vision_ocr_detect/models/profile.py \
  src/vision_ocr_detect/models/models.py
git commit -m "feat(models): json_schema_extra examples on request/response models

Adds Swagger 'Try it out' prefills and richer /docs schema panels.
Affects DetectResponse, JsonSchemaSpec, JsonSchemaResponseFormat,
Profile, ProfileCreate, ProfileUpdate, ProviderModels, ModelsResponse.
Behavior unchanged. Validation already covered by existing tests."
```

---

## Task 3: Layer 3 — Route Summary / Description / Response Description

**Files:**
- Modify: `src/vision_ocr_detect/api/detect.py:272-307` (`@router.post("/detect", ...)`)
- Modify: `src/vision_ocr_detect/api/profiles.py:32-113` (5 route decorators)
- Modify: `src/vision_ocr_detect/api/models.py:36-71` (2 route decorators)
- Modify: `src/vision_ocr_detect/main.py:164-187` (`/health` route)
- Test: `tests/test_openapi.py` (extend)

**Interfaces:**
- Consumes: existing route signatures, dependencies, response models — unchanged.
- Produces: each route in `app.openapi()["paths"]` has non-empty `summary`; `/api/detect` additionally has non-empty `description` and `responses[422]` mentions truncation signature.

- [ ] **Step 1: Extend `tests/test_openapi.py` with route-summary tests**

Append to `tests/test_openapi.py`:

```python
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
```

- [ ] **Step 2: Run tests and confirm failures**

Run: `uv run pytest tests/test_openapi.py -v`
Expected: 5 parametrized summary failures + 2 description failures.

- [ ] **Step 3: Add summary/description to `POST /api/detect`**

In `src/vision_ocr_detect/api/detect.py`, replace the `@router.post("/detect", response_model=DetectResponse)` decorator (line 272) with:

```python
@router.post(
    "/detect",
    response_model=DetectResponse,
    summary="Run vision/OCR on an image",
    description=(
        "multipart/form-data with three fields:\n\n"
        "- `image` (required): PNG / JPEG / WebP / GIF, max 20 MiB. "
        "Animated GIFs use the first frame.\n"
        "- `profile` (required): profile name (must exist; see `GET /api/profiles`).\n"
        "- `options` (optional): JSON string. Three notable options:\n\n"
        "  - `response_format: \"json\"` — provider is asked to emit JSON; "
        "server parses leniently (`parsed` may be `null` on parse failure).\n"
        "  - `response_format: {type: \"json_schema\", json_schema: {...}}` — "
        "server validates the model's output against the supplied JSON Schema; "
        "returns 422 on schema mismatch.\n"
        "  - `profile_override` — per-call (provider, model, prompt, "
        "temperature, seed) override. Does not persist.\n\n"
        "**Errors:** 404 if profile missing; 422 on bad options / bad image / "
        "JSON parse or schema failure (detail includes a truncation signature: "
        "`text_length`, `last_nonspace_char`, `ends_with_unclosed_brace`, "
        "`last_nonempty_line`, `suggestion`); 502 if provider fails; 503 with "
        "`Retry-After: 1` when concurrency cap is reached.\n"
    ),
    response_description=(
        "200 with DetectResponse on success. 404 if profile is unknown. "
        "422 on bad options / image / JSON parse or schema mismatch. "
        "502 on provider failure. 503 + Retry-After: 1 when concurrency cap "
        "is reached."
    ),
)
```

- [ ] **Step 4: Add summaries to profile routes**

In `src/vision_ocr_detect/api/profiles.py`, decorate each route. Replace each `@router.<method>` line:

- `@router.get("", response_model=list[Profile])` → add `summary="List profiles (optional ?tag= filter)"`
- `@router.get("/{name}", response_model=Profile)` → add `summary="Get one profile by name"`
- `@router.post("", response_model=Profile, status_code=status.HTTP_201_CREATED)` → add `summary="Create profile"`, `response_description="201 with the created Profile. 409 if name is taken. 400 if provider is unknown. 422 on validation failure."`
- `@router.put("/{name}", response_model=Profile)` → add `summary="PATCH-style update (omitted fields preserved)"`, `response_description="200 with the updated Profile. 404 if not found. 422 on validation failure."`
- `@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)` → add `summary="Delete profile"`, `response_description="204 on success. 404 if not found."`

The resulting decorator shape for each (example for `GET ""`):

```python
@router.get(
    "",
    response_model=list[Profile],
    summary="List profiles (optional ?tag= filter)",
)
```

- [ ] **Step 5: Add summaries to model routes**

In `src/vision_ocr_detect/api/models.py`:

- `@router.get("/models", response_model=ModelsResponse)` → add `summary="List models per provider (optional vision_only filter)"`, `response_description="200 with ModelsResponse. 502 if a provider errors; the failing provider contributes a synthetic entry rather than failing the whole response."`
- `@router.get("/providers/{name}/models", response_model=ProviderModels)` → add `summary="List models for one provider"`, `response_description="200 with ProviderModels. 404 if provider name is unknown. 502 if the provider errors."`

- [ ] **Step 6: Add summary/description to `/health`**

In `src/vision_ocr_detect/main.py`, replace the `@app.get("/health")` decorator (line 164) with:

```python
    @app.get(
        "/health",
        summary="Liveness + capability snapshot",
        description=(
            "Reports configured provider names, count of loaded profiles, "
            "and vision-capable model names per provider. Never returns 5xx — "
            "provider failures are swallowed and contribute an empty "
            "`vision_models` entry."
        ),
        response_description="200 with a small JSON snapshot.",
    )
```

- [ ] **Step 7: Re-run the route tests; confirm pass**

Run: `uv run pytest tests/test_openapi.py -v`
Expected: all tests pass (4 from Layer 1 + 10 from Layer 2 + 7 from Layer 3 = 21 tests).

- [ ] **Step 8: Run the full suite; confirm no regression**

Run: `uv run pytest --ignore=tests/test_provider_smoke.py`
Expected: 137 existing + 21 new = 158 passing.

- [ ] **Step 9: Commit**

```bash
git add tests/test_openapi.py \
  src/vision_ocr_detect/api/detect.py \
  src/vision_ocr_detect/api/profiles.py \
  src/vision_ocr_detect/api/models.py \
  src/vision_ocr_detect/main.py
git commit -m "feat(openapi): route summary, description, response_description

Affects /api/detect, /api/profiles* (5 routes), /api/models* (2 routes),
and /health. Surfaces truncation signature hint, JSON parse modes, error
codes, and concurrency-gate behavior on /docs. Behavior unchanged."
```

---

## Task 4: Layer 4 — README Gap Fills + `.env.example`

**Files:**
- Modify: `README.md` (six section extensions; no structural reorganization)
- Create: `.env.example`

No automated tests. Verify by:
1. `git diff README.md` to eyeball the additions.
2. Boot the server (`uv run vision-ocr-detect`); open `http://localhost:8000/docs` and confirm Markdown renders, tag descriptions show, "Try it out" prefills.
3. Confirm `.env.example` is tracked (`git ls-files .env.example`).

- [ ] **Step 1: Add 20 MiB cap to the `image` field documentation**

In `README.md`, locate the `### Detect` section and the multipart form-data block (around line 89-96). Change the `image:` line from:

```
  image:    <file>              (required; PNG / JPEG / WebP / GIF;
                                animated GIFs use the first frame)
```

to:

```
  image:    <file>              (required; PNG / JPEG / WebP / GIF; max 20 MiB;
                                animated GIFs use the first frame)
```

- [ ] **Step 2: Add 422 truncation signature block before the existing error-codes line**

In the same `### Detect` section, locate the line that begins `Error codes: \`404\` ...` (around line 253). Insert the following paragraph immediately before that line:

```markdown
**422 with truncation signature:** when JSON parsing or JSON Schema
validation fails, the response `detail` carries a structured fingerprint
to distinguish "the model hit `max_tokens` mid-value" from "the model
emitted malformed JSON". The string contains the fields:

| field | meaning |
|---|---|
| `text_length` | total characters in the raw model output |
| `last_nonspace_char` | the trailing non-whitespace character |
| `ends_with_unclosed_brace` | `true` when the last char is `{`, `[`, `,`, `:`, or `"` — strong truncation signal |
| `last_nonempty_line` | the last non-blank line (truncated to 200 chars) |
| `suggestion` | remediation hint, currently `"Try response_format=json (lenient) or max_tokens=16384."` |

A `true` `ends_with_unclosed_brace` is usually truncation: raise
`max_tokens` or fall back to `response_format: "json"` (lenient mode).
A `false` value with a parse error usually means a prompt or model
change is needed.

```

- [ ] **Step 3: Add `X-Process-Time` and middleware-log subsection under `## Run`**

In `README.md`, locate the `## Run` section. After the uvicorn command block (ending around line 50), insert:

```markdown
### Response headers and per-request logs

Every response carries `X-Process-Time: <ms>ms`, set by the request
middleware in `main.py`. The middleware also emits one
`vision_ocr_detect.request` log line per request:

```
method=POST path=/api/detect status=200 elapsed_ms=1247 params={"profile": "interpark-layout", "options": {"response_format": "json"}}
```

Other endpoints log the same line without the `params=` segment.
Filter the access log with `grep vision_ocr_detect.request` for the
per-request view; use `X-Process-Time` for client-side timing.

```

- [ ] **Step 4: Add env-var usage example under `### Path overrides`**

In `README.md`, locate `### Path overrides` (around line 415). After the two-bullet list, append:

```markdown
Example:

```bash
VISION_OCR_CONFIG=/etc/vision-ocr/config.json \
VISION_OCR_PROFILES=/var/lib/vision-ocr/profiles.json \
  uv run vision-ocr-detect
```

Both paths are resolved against the process CWD when relative.

```

- [ ] **Step 5: Add `.env` format details under `### Secrets (api_key)`**

In `README.md`, locate `### Secrets (api_key)` (around line 397). After the existing prose, insert:

```markdown
### `.env` file format

`.env` is parsed by pydantic-settings' `BaseSettings` on startup.
One `KEY=value` pair per line; comments start with `#`:

```ini
# .env (project root; .gitignored)
OPENROUTER_API_KEY=sk-or-v1-...
```

See `.env.example` at the repo root for the canonical template.
Process env vars override `.env`, which overrides `config.json`.

```

- [ ] **Step 6: Add `### Provider internals` subsection before `## Adding a new provider type`**

In `README.md`, locate `## Adding a new provider type` (around line 420). Insert this subsection immediately before it:

```markdown
### Provider internals

- **Ollama** (`local-ollama`): tries the native `/api/generate`
  surface first. If ollama returns 404 or `model-not-found` (some
  builds report this as 200 + `body.error`), the provider falls back
  to the OpenAI-compat `/v1/chat/completions` surface for the same
  call. The successful surface is recorded in
  `DetectResponse.endpoint_used` (`"native"` or `"openai"`), so
  consumers can see which path served a given request. Both surfaces
  accept vision models; vision-only ones like granite-vision and
  minicpm-v only work on the native surface.

- **OpenRouter** (`openrouter`): single OpenAI-compat path
  (`/api/v1/chat/completions`). The constructor does **not** raise
  when `OPENROUTER_API_KEY` is missing — the lifespan startup logs
  a warning listing the affected profiles, and the first `detect`
  call raises a `RuntimeError` that the API layer surfaces as 502.
  This keeps the server bootable for diagnosis even with incomplete
  config.

```

- [ ] **Step 7: Create `.env.example` at the repo root**

Create `.env.example` with this exact content:

```ini
# Copy this file to `.env` and fill in real values.
# `.env` is gitignored; `.env.example` is tracked.
# Lines beginning with `#` are comments (pydantic-settings).

# Required for any profile whose `provider` is `openrouter`.
# Get a key at https://openrouter.ai/keys
OPENROUTER_API_KEY=sk-or-v1-replace-me
```

- [ ] **Step 8: Verify `.env.example` is tracked**

Run:

```bash
git ls-files .env.example
```

Expected: `.env.example` printed (file is tracked).

- [ ] **Step 9: Confirm `.env` stays ignored**

Run:

```bash
git check-ignore -v .env
```

Expected: a line of the form `/.env` (the existing `/.env` rule in `.gitignore` matches).

- [ ] **Step 10: Re-run the full test suite; confirm no regression**

Run: `uv run pytest --ignore=tests/test_provider_smoke.py`
Expected: 158 tests still pass (README + `.env.example` are doc-only; no test surface affected).

- [ ] **Step 11: Visual spot-check (optional, manual)**

Boot the server with `uv run vision-ocr-detect`. In a browser:

- `http://localhost:8000/docs` — confirm the long Markdown description renders, the three sidebar tags show descriptions, and at least one model "Try it out" is prefilled.
- `http://localhost:8000/redoc` — confirm ReDoc renders the same description and per-route summaries.

Skip this step if no display is available; the automated tests in Tasks 1-3 already gate the metadata.

- [ ] **Step 12: Commit**

```bash
git add README.md .env.example
git commit -m "docs: README gap fills + .env.example

Adds 422 truncation signature spec, 20 MiB cap, X-Process-Time and
middleware log subsection, env-var usage example, .env format
details, and provider internals (ollama dual-call strategy,
openrouter tolerant constructor). New .env.example at repo root
provides a tracked template; .env stays gitignored."
```

---

## Self-Review Checklist (run before execution)

- **Spec coverage:**
  - 4 layers all present ✓ (Tasks 1-4)
  - 9 routes get summaries ✓ (Task 3; /api/detect + 5 profiles + 2 models + /health = 9)
  - 8 models get examples ✓ (Task 2)
  - README sections all covered ✓ (Task 4, Steps 1-6)
  - `.env.example` exists ✓ (Task 4, Step 7)
  - OpenAPI metadata regression tests ✓ (Tasks 1-3)
- **Placeholder scan:** No "TBD"/"TODO"/"implement later"/"fill in". One deliberate "low priority TODO" was in the spec but is **not** carried into the plan; surface drift is mitigated by the test suite, not by a comment.
- **Type consistency:** `app`, `create_app`, `_schema`, `model_cls` consistently used across tests; FastAPI constructor kwargs match the spec verbatim.
- **Commit cadence:** 4 commits, one per layer. Each is independently reviewable and revertable.
