# API Documentation Hardening — Design Spec

**Date**: 2026-06-26
**Target**: `vision-ocr-detect` (FastAPI HTTP service)
**Audience**: API consumers (integrators who call the HTTP API)
**Status**: Design — pending user review

## Problem

The codebase has good internal documentation (module docstrings, inline
comments explain design choices) and an excellent high-level README.
What it lacks is **API-consumer-facing documentation that surfaces in
the FastAPI-generated `/docs` and `/redoc` pages**, and a few
operational details that an integrator would need but currently has to
read source to discover.

Concretely:

1. `create_app()`'s `description` is a single line. The `/docs` header
   gives consumers no context beyond the title.
2. No `openapi_tags`: every endpoint group on `/docs` is nameless.
3. Response/request models have no `examples` — Swagger's "Try it out"
   is empty, hurting integration velocity.
4. Several operational behaviors are documented in source comments but
   not in README or OpenAPI:
   - 422 truncation signature shape
   - 20 MiB image upload cap
   - `VISION_OCR_CONFIG` / `VISION_OCR_PROFILES` env var usage examples
   - `.env` file format (no `.env.example` exists)
   - Ollama native-first / OpenAI-compat-fallback strategy
   - OpenRouter tolerant-constructor behavior
   - `X-Process-Time` response header
   - Per-request middleware log (`vision_ocr_detect.request` line)

## Goals

1. **Make `/docs` self-sufficient** for first-time integrators: header,
   tag descriptions, model examples, route summaries, and response
   descriptions together answer "what does this endpoint do?" without
   needing to read README.
2. **Fill the README gaps** that an integrator hits during setup and
   debugging (env vars, error shape, middleware, dual-call strategy).
3. **Zero behavior change**: documentation metadata only. No request
   handling, validation, or persistence logic changes.

## Non-Goals (out of scope)

- Translating/rewriting `fixtures/README.md` (dev-only).
- Adding `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE` (project policy;
  separate concern).
- Expanding `__init__.py` package docstring (developer-facing, not API).
- Reorganizing `collab-log.md` (operational history, not API doc).
- Generating a separate `docs/` site. README + OpenAPI metadata cover
  the audience; deeper architecture docs can be a future, separately
  scoped project.

## Design

Four layers, applied in one PR. Layers are stacked top-to-bottom
(outermost first) so a reviewer can read them in order and the testing
hierarchy (`tests/` → `models/` → `api/` → `main.py`) matches the
review order.

### Layer 1 — FastAPI app metadata (`src/vision_ocr_detect/main.py`)

`create_app()` gets a richer `FastAPI(...)` constructor:

```python
app = FastAPI(
    title="vision-ocr-detect",
    version="0.1.0",
    summary="Vision/OCR HTTP API wrapping local & hosted vision models",
    description=(
        "## Overview\n\n"
        "Run vision/OCR models over HTTP. Manage named profiles "
        "(provider + model + prompt) at runtime, then call `POST /api/detect` "
        "with an image to get extracted text back.\n\n"
        "## Quick start\n\n"
        "1. `uv sync && cp config.example.json config.json && cp profiles.example.json profiles.json`\n"
        "2. Edit `config.json` to point at your ollama instance\n"
        "3. `uv run vision-ocr-detect`\n"
        "4. OpenAPI/Swagger UI at `/docs`, ReDoc at `/redoc`\n\n"
        "## Key concepts\n\n"
        "- **Profile**: named bundle of (provider, model, prompt). Persisted to `profiles.json`.\n"
        "- **Provider**: backend (ollama local, openrouter cloud). Configured in `config.json`.\n"
        "- **Detect**: one-shot image-to-text call. Concurrency-capped per server.\n"
    ),
    openapi_tags=[
        {"name": "detect", "description": "Run vision/OCR on an image."},
        {"name": "profiles", "description": "CRUD for named prompt+model bundles."},
        {"name": "models", "description": "Enumerate available vision models."},
    ],
    contact={"name": "vision-ocr-detect", "url": "https://github.com/dormael/vision-ocr-detect"},
    lifespan=lifespan,
)
```

Effect:
- `/docs` and `/redoc` render the long description as Markdown.
- Sidebar groups (`detect`, `profiles`, `models`) show a description.
- `contact` populates the Swagger UI footer.

### Layer 2 — Pydantic model examples

Each request/response Pydantic model gets
`json_schema_extra={"examples": [<one or more>]}`. The Swagger "Try it
out" feature uses this for prefill; `/docs` shows it under each schema.

**`models/detect.py`** — `DetectResponse`:

```python
model_config = ConfigDict(
    extra="forbid",
    json_schema_extra={
        "examples": [
            {
                "text": "{\"stage_location\": \"TOP\", \"sections\": []}",
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

**`models/profile.py`** — `Profile`, `ProfileCreate`, `ProfileUpdate`:
each gets a representative example. `ProfileCreate` example shows a
fresh profile (no timestamps). `ProfileUpdate` shows a PATCH-style
partial body (one field). `Profile` shows a stored entry with both
timestamps. Tags examples use lowercase alphanumeric + dashes.

**`models/models.py`** — `ProviderModels`, `ModelsResponse`: each gets
a small example with one provider / two models.

**`models/detect.py`** — `JsonSchemaSpec`, `JsonSchemaResponseFormat`:
one example each, mirroring an OpenAI-style `seat_layout` schema.

Convention: examples are concise (no 1KB prompt blobs); long prompts
stay in README only.

### Layer 3 — Route summary / description / response_description

Every endpoint gets `summary=...` and where useful `description=...` and
`response_description=...`. Existing module-level docstrings stay; route
descriptions are short and excerpt the key behavior.

| Endpoint | summary | response_description highlights |
|---|---|---|
| `POST /api/detect` | `Run vision/OCR on an image` | `200 with DetectResponse; 404 if profile missing; 422 on bad options/image/JSON parse/schema; 502 on provider failure; 503 with Retry-After when concurrency cap reached` |
| `GET /api/profiles` | `List profiles (optional ?tag= filter)` | `200 with [Profile]` |
| `GET /api/profiles/{name}` | `Get one profile by name` | `200 with Profile; 404 if not found` |
| `POST /api/profiles` | `Create profile` | `201 with Profile; 409 if name taken; 400 unknown provider; 422 validation` |
| `PUT /api/profiles/{name}` | `PATCH-style update (omitted fields preserved)` | `200 with Profile; 404; 422 validation` |
| `DELETE /api/profiles/{name}` | `Delete profile` | `204; 404` |
| `GET /api/models` | `List models per provider (optional vision_only filter)` | `200 with ModelsResponse; 502 if a provider errors` |
| `GET /api/providers/{name}/models` | `List models for one provider` | `200; 404 unknown provider; 502 provider error` |
| `GET /health` | `Liveness + capability snapshot` | `200 always; never 5xx — provider failures are swallowed` |

Route descriptions for `/api/detect` mention the JSON parsing modes
(`"json"` lenient vs `json_schema` strict) and reference README for
422 truncation signature detail (kept there to avoid duplication).

### Layer 4 — README gap fills

Single `README.md` edit. No structural change; sections are extended in
place. New top-level content: `.env.example` (new file at repo root,
tracked).

| Section | Existing location | Addition |
|---|---|---|
| `### Detect` (image upload) | line ~92 | Add "max 20 MiB" to image field description. |
| `### Detect` (error codes) | line ~253 | Insert 422 truncation signature spec block before the existing code list. |
| `### Run` | line ~52 | Add subsection: response headers (`X-Process-Time`) and middleware log line (`vision_ocr_detect.request`). |
| `### Path overrides` | line ~415 | Add a 2-line example with `VISION_OCR_CONFIG=` and `VISION_OCR_PROFILES=`. |
| `### Secrets (api_key)` | line ~397 | Add `.env` file format example (one line) and reference to `.env.example`. |
| `## Adding a new provider type` | line ~420 (preceding it) | New subsection: `### Provider internals` documenting (a) ollama native-first / OpenAI-compat-fallback with trigger conditions and (b) OpenRouter tolerant constructor behavior. |
| `### Models` (vision_capable) | line ~292 | One-line cross-reference: heuristic patterns list lives in `providers/ollama.py` (avoids duplication). |

**New file**: `.env.example` at repo root:
```
# Copy to .env and fill in real values. .env is in .gitignore.
OPENROUTER_API_KEY=sk-or-v1-replace-me
```

(`.gitignore` already ignores `.env`; `.env.example` is tracked.)

## Why this layering

1. **Layer 1** is the cheapest and highest-impact change for first-time
   integrators visiting `/docs`.
2. **Layer 2** requires no behavior change and produces immediate Swagger
   UI value (prefilled forms).
3. **Layer 3** makes `/docs` self-describing per endpoint without
   bloating README with duplicate copy.
4. **Layer 4** captures the operational / debugging information that
   belongs in narrative prose, not schema metadata.

All four are documentation-only. The diff should be reviewable in
under 30 minutes.

## Testing

- Existing test suite (`uv run pytest`) must pass unchanged.
- New test in `tests/test_openapi.py` (or extend an existing test file):
  - `app.title == "vision-ocr-detect"` (regression on Layer 1)
  - `app.openapi()["tags"]` includes entries for `detect`, `profiles`,
    `models` (regression on Layer 1 `openapi_tags`)
  - Each response/request model schema contains a non-empty `examples`
    array (regression on Layer 2)
  - Each route's `summary` is non-empty (regression on Layer 3)
- Manual check: visit `/docs` and `/redoc` after boot; verify Markdown
  renders, sidebar shows tag descriptions, "Try it out" prefills.

## Risk

- **Test snapshots**: any existing test that asserts on the OpenAPI
  schema (e.g. dumps `app.openapi()` and compares to a fixture) will
  need updating. Mitigation: search for `app.openapi` and `openapi()`
  in `tests/` before changes; only `test_openapi.py` (if it exists)
  will need fixture updates.
- **Example drift**: model fields evolve, and `examples` will go stale
  silently. Mitigation: a low-priority TODO comment near the first
  `json_schema_extra` block, plus the schema assertion test above
  catches missing examples but not incorrect ones — manual review on
  model edits.

## Out of scope (deliberately)

- Code-level docstrings (already strong).
- `fixtures/README.md` (dev-only).
- `CHANGELOG.md`, `CONTRIBUTING.md`, `LICENSE` (project policy).
- `__init__.py` package docstring (developer-facing).
- `collab-log.md` (operational history).
- A separate `docs/` site.

## Acceptance criteria

1. `/docs` header shows the long description (Markdown renders).
2. `/docs` sidebar lists three tag groups with descriptions.
3. `/docs` schema panels show one or more `Examples` blocks; "Try it
   out" prefills.
4. `/docs` route entries each have a `Summary` line.
5. `uv run pytest` passes.
6. README covers: 20 MiB cap, 422 truncation signature, env var
   overrides, `.env` format, provider internals (dual-call + tolerant
   constructor), middleware log.
7. `.env.example` exists at repo root, is tracked in git, and contains
   the documented env-var name with a placeholder value.

## Implementation order (when plan is executed)

1. Layer 1: edit `main.py` `create_app()`.
2. Layer 2: edit `models/{detect,profile,models}.py` to add examples.
3. Layer 3: edit `api/{detect,profiles,models}.py` and `main.py`'s
   `/health` route to add summary/description/response_description.
4. Layer 4: edit `README.md` sections; create `.env.example`.
5. Tests: add `tests/test_openapi.py` (or extend existing file); run
   full suite.

Each step is independently testable; review is incremental.