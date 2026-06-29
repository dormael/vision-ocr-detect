# vision-ocr-detect

Local and hosted vision/OCR models exposed as a FastAPI HTTP API.

The service manages named profiles (`provider + model + prompt`) in
`profiles.json`, preprocesses uploaded images, calls a configured vision model,
and returns extracted text plus optional parsed JSON.

## What It Does

- Runs `POST /api/detect` over PNG, JPEG, WebP, and GIF uploads.
- Stores reusable OCR/layout extraction profiles without a database.
- Supports local `ollama` and hosted `openrouter` providers.
- Applies image preprocessing before model calls:
  `crop -> preprocess -> scale -> resize -> encode`.
- Supports per-request model, prompt, temperature, seed, image, and
  response-format overrides.
- Exposes profile CRUD, model listing, health checks, OpenAPI docs, request
  timing headers, and structured request logs.

## Quick Start

```bash
uv sync
cp config.example.json config.json
cp profiles.example.json profiles.json
uv run vision-ocr-detect
```

OpenAPI docs: <http://localhost:8000/docs>

For the full setup, configuration, API, and curl examples, see
[USAGE.md](USAGE.md).

## Documentation

- [USAGE.md](USAGE.md) - install, run, configure, call the API, manage
  profiles, tune image options, and use OpenRouter.
- [DEV.md](DEV.md) - project layout, runtime architecture, provider internals,
  tests, logging, and extension points.

Useful sections:

- [Install and Run](USAGE.md#install-and-run)
- [Configuration](USAGE.md#configuration)
- [Profiles API](USAGE.md#profiles-api)
- [Detect API](USAGE.md#detect-api)
- [Image Options](USAGE.md#image-options)
- [Response Formats](USAGE.md#response-formats)
- [Models API](USAGE.md#models-api)
- [Development Setup](DEV.md#development-setup)
- [Architecture](DEV.md#architecture)
- [Adding a Provider](DEV.md#adding-a-provider)
- [Testing](DEV.md#testing)

## Limits

- No API authentication yet.
- No streaming response support.
- No request cache.
- Profile storage is file-backed and intended for a single service process.

