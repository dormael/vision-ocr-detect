# Development

This guide covers the code structure, runtime flow, tests, and extension
points for `vision-ocr-detect`.

## Development Setup

```bash
uv sync
cp config.example.json config.json
cp profiles.example.json profiles.json
uv run vision-ocr-detect
```

Run the test suite:

```bash
uv run pytest
```

Run the live provider smoke test:

```bash
uv run pytest tests/test_provider_smoke.py
```

The normal API tests use fake providers and do not require network access.
The smoke test talks to a real ollama server and skips when unavailable.

## Project Layout

```text
src/vision_ocr_detect/
  main.py                    FastAPI app, lifespan, health, request logging
  config.py                  config.json/.env loading and validation
  deps.py                    FastAPI dependency helpers and profile path lookup
  api/
    detect.py                POST /api/detect
    profiles.py              profile CRUD endpoints
    models.py                model listing endpoints
  models/
    detect.py                detect request/response schemas
    image.py                 image preprocessing option schemas
    profile.py               profile schemas and validation
    models.py                model-listing schemas
  providers/
    base.py                  provider protocol/result/model types
    registry.py              provider construction and lookup
    ollama.py                native ollama + OpenAI-compatible fallback
    openrouter.py            OpenRouter OpenAI-compatible provider
  services/
    image_processor.py       Pillow preprocessing pipeline
    profile_store.py         JSON-backed profile persistence

tests/                       pytest suite
config.example.json          documented example runtime config
profiles.example.json        example profile store
logging.json                 uvicorn/app logging config
```

## Architecture

Startup happens in `main.py` lifespan:

1. Load settings from `config.json`, `.env`, and environment variables.
2. Load `profiles.json` through `ProfileStore`.
3. Build `ProviderRegistry` from configured providers.
4. Create an `asyncio.Semaphore` sized by
   `server.max_concurrent_requests`.
5. Close provider HTTP clients during shutdown.

Request flow for `POST /api/detect`:

1. Parse multipart form fields and validate `options` as `DetectOptions`.
2. Acquire the detect semaphore, failing fast with `503` when saturated.
3. Resolve the named profile.
4. Apply `profile_override` without persisting it.
5. Resolve the provider from `ProviderRegistry`.
6. Process the uploaded image with `services.image_processor`.
7. Call the provider.
8. Parse and optionally validate JSON output.
9. Compute response metadata and cost.

## Configuration Internals

`config.py` uses pydantic v2 and pydantic-settings.

Config path resolution:

1. `VISION_OCR_CONFIG`
2. `./config.json`

Profile path resolution is handled in `deps.py`:

1. `VISION_OCR_PROFILES`
2. `./profiles.json`

`Settings.openrouter_api_key` is a top-level field aliased to
`OPENROUTER_API_KEY`. `ProviderRegistry.from_settings()` copies it into the
nested `openrouter` provider config when `config.json` leaves `api_key` unset.

## Providers

Provider implementations expose the common `VisionProvider` behavior from
`providers/base.py`.

### Ollama

`OllamaProvider` tries native ollama first:

```text
POST /api/generate
```

If native returns a model-not-found style failure, it falls back once to:

```text
POST /v1/chat/completions
```

The response records the successful surface in `endpoint_used` as `native` or
`openai`.

Model listing uses ollama's native `/api/tags`. When ollama exposes model
`capabilities`, that signal is authoritative. Otherwise the provider falls
back to conservative name heuristics such as `llava`, `vision`, `qwen.*vl`,
and `-ocr`.

### OpenRouter

`OpenRouterProvider` calls:

```text
POST /chat/completions
GET /models
```

It accepts a missing API key at construction time so the service can boot and
surface diagnostics. A detect call without a key raises a runtime error that
the API maps to `502`.

OpenRouter model capability detection is name-heuristic because the catalog
does not expose a dedicated vision capability flag.

## Adding a Provider

1. Implement a provider class in `src/vision_ocr_detect/providers/<name>.py`.
2. Match the behavior expected by `providers/base.py`.
3. Add the provider to `_BUILDERS` in `providers/registry.py`.
4. Add the provider type literal to `ProviderConfig.type` in `config.py`.
5. If the provider needs a secret, add a top-level `Settings` field with an
   env alias and bridge it in `ProviderRegistry.from_settings()`.
6. Add tests for registry construction, request forwarding, error mapping, and
   model listing if applicable.
7. Update [USAGE.md](USAGE.md#configuration) with config and secret examples.

## Image Pipeline

The image processing pipeline lives in `services/image_processor.py` and is
configured by `models/image.py`.

Order:

```text
crop -> preprocess -> scale -> resize -> encode
```

Keep this order stable unless you also update tests and usage docs. Users rely
on this order for OCR/layout tuning.

## JSON Output Handling

`api/detect.py` has two JSON modes:

- `response_format: "json"` - lenient parse. Parse failure is not fatal;
  `parsed` becomes `null` and `text` is preserved.
- `response_format: {"type": "json_schema", ...}` - parse and validate.
  Parse failure or schema mismatch returns `422`.

Lenient parsing strips a wrapping markdown JSON fence and normalizes a few
common VLM quirks before calling `json.loads`. The raw `text` field is never
mutated.

Schema validation uses `jsonschema`. On validation failure it retries once
after dropping explicit `null` values from parsed objects, which recovers the
common case where a model emits `null` for an optional field instead of
omitting it.

## Profile Store

`ProfileStore` persists profile data to JSON. It is intentionally simple and
suited to one service process. The public API layer validates provider names;
the store is responsible for loading, saving, creating, updating, deleting,
and reloading profile records.

For multi-replica deployments, replace the file-backed store with a database
or another shared persistence layer.

## Logging

`main.py` middleware adds `X-Process-Time` and emits one
`vision_ocr_detect.request` log line per request.

`/api/detect` adds `request.state.log_params` so logs include the profile and
normalized options. Other endpoints omit params.

`logging.json` is the single source for uvicorn logging when using the CLI
flag:

```bash
uv run uvicorn vision_ocr_detect.main:app --log-config logging.json
```

## Testing

Common commands:

```bash
uv run pytest
uv run pytest tests/test_detect_api.py
uv run pytest tests/test_openapi.py
uv run pytest tests/test_provider_smoke.py
```

Test responsibilities:

- `test_detect_api.py` - detect success/error behavior, JSON parsing, schema
  handling, concurrency, provider errors.
- `test_profiles_api.py` - profile CRUD and validation.
- `test_models_api.py` - model listing routes and filtering.
- `test_image_processor.py` - crop/preprocess/resize/encode behavior.
- `test_config.py` - config loading and env behavior.
- `test_profile_store.py` - file-backed persistence.
- `test_openrouter_provider.py` - OpenRouter request shape and errors.
- `test_request_middleware.py` - timing header and request logs.
- `test_openapi.py` - documented OpenAPI surface.
- `test_provider_smoke.py` - optional live ollama roundtrip.

## Documentation Maintenance

Keep the split clear:

- `README.md` is the project overview and link hub.
- `USAGE.md` is for operators and API clients.
- `DEV.md` is for contributors and maintainers.

When changing API behavior, update the OpenAPI annotations, tests, and
`USAGE.md` in the same change. When changing internals or extension points,
update `DEV.md`.

