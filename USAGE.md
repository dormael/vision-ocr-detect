# Usage

This guide covers installing, running, configuring, and calling
`vision-ocr-detect`.

## Install and Run

```bash
uv sync
cp config.example.json config.json
cp profiles.example.json profiles.json
```

Edit `config.json` if your ollama server is not at
`http://localhost:11434`.

Start the API:

```bash
uv run vision-ocr-detect
```

Equivalent explicit uvicorn command:

```bash
uv run uvicorn vision_ocr_detect.main:app --host 0.0.0.0 --port 8000 \
  --log-config logging.json
```

OpenAPI docs are available at:

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>

## Configuration

`config.json` is loaded from the current working directory by default.
Set `VISION_OCR_CONFIG` to use another path.

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8000,
    "max_concurrent_requests": 4
  },
  "providers": {
    "local-ollama": {
      "type": "ollama",
      "base_url": "http://localhost:11434",
      "api_key": null,
      "timeout_seconds": 300,
      "cost_per_1k_input_tokens": 0.0,
      "cost_per_1k_output_tokens": 0.0
    },
    "openrouter": {
      "type": "openrouter",
      "base_url": "https://openrouter.ai/api/v1",
      "api_key": null,
      "timeout_seconds": 300,
      "cost_per_1k_input_tokens": 0.0,
      "cost_per_1k_output_tokens": 0.0
    }
  }
}
```

Server fields:

- `host`, `port` - listener settings.
- `max_concurrent_requests` - simultaneous `/api/detect` requests. Over-limit
  requests return `503` with `Retry-After: 1`.

Provider fields:

- `type` - currently `ollama` or `openrouter`.
- `base_url` - provider base URL.
- `api_key` - usually `null`; prefer environment variables for secrets.
- `timeout_seconds` - upstream model request timeout.
- `cost_per_1k_input_tokens`, `cost_per_1k_output_tokens` - used to compute
  `cost_usd` in detect responses when token usage is available.

## Secrets

OpenRouter uses `OPENROUTER_API_KEY`.

Preferred options:

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
```

or create `.env` in the project root:

```ini
OPENROUTER_API_KEY=sk-or-v1-...
```

Process environment variables override `.env`. The provider registry copies
`OPENROUTER_API_KEY` into the `openrouter` provider config when
`config.json` leaves `api_key` as `null`.

## Path Overrides

```bash
VISION_OCR_CONFIG=/etc/vision-ocr/config.json \
VISION_OCR_PROFILES=/var/lib/vision-ocr/profiles.json \
  uv run vision-ocr-detect
```

Relative paths are resolved against the process current working directory.

## Profiles API

A profile is a reusable bundle of `provider`, `model`, and `prompt`.
Profiles are stored in `profiles.json`.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/profiles` | List all profiles. Use `?tag=<name>` to filter. |
| `GET` | `/api/profiles/{name}` | Get one profile. |
| `POST` | `/api/profiles` | Create a profile. Returns `201`, `409`, `400`, or `422`. |
| `PUT` | `/api/profiles/{name}` | PATCH-style update. Omitted fields are preserved. |
| `DELETE` | `/api/profiles/{name}` | Delete a profile. Returns `204` or `404`. |

Create a profile:

```bash
curl -X POST localhost:8000/api/profiles \
  -H 'content-type: application/json' \
  -d '{
    "name": "ocr",
    "provider": "local-ollama",
    "model": "qwen2.5vl:7b",
    "prompt": "Extract all text from this image.",
    "description": "General OCR profile",
    "tags": ["ocr", "default"]
  }'
```

Profile constraints:

- `name`: URL-safe, 1-64 chars, `[a-zA-Z0-9_.-]`.
- `description`: optional, max 500 chars.
- `tags`: optional, max 20 tags. Tags are lowercased, deduplicated, and must
  be 1-32 chars of lowercase letters, digits, `_`, or `-`.

## Detect API

```http
POST /api/detect
Content-Type: multipart/form-data
```

Form fields:

- `image` - required image file. PNG, JPEG, WebP, and GIF are accepted.
  Animated GIFs use the first frame.
- `profile` - required profile name.
- `options` - optional JSON string with per-call overrides.

Basic call:

```bash
curl -X POST localhost:8000/api/detect \
  -F profile=ocr \
  -F image=@sample.png
```

With options:

```bash
curl -X POST localhost:8000/api/detect \
  -F profile=ocr \
  -F image=@sample.png \
  -F 'options={
    "image": {"format": "jpeg", "scale": 0.5},
    "max_tokens": 256,
    "temperature": 0.0,
    "seed": 42
  }'
```

`options` schema:

```json
{
  "image": {
    "crop": {"x": 0, "y": 0, "width": 800, "height": 600},
    "preprocess": {
      "sharpen": {"sigma": 1.0},
      "contrast": 1.2,
      "brightness": 1.0,
      "binarize": {"threshold": 128}
    },
    "scale": 0.5,
    "resize": {
      "width": 1024,
      "height": 768,
      "fit": "fill",
      "background": "#ffffff"
    },
    "format": "jpeg"
  },
  "max_tokens": 512,
  "temperature": 0.0,
  "seed": 42,
  "response_format": "json",
  "profile_override": {
    "provider": "local-ollama",
    "model": "qwen2.5vl:7b",
    "prompt": "Extract the seat layout as JSON.",
    "temperature": 0.0,
    "seed": 42
  }
}
```

Response:

```json
{
  "text": "{\"stage_location\":\"TOP\",\"sections\":[]}",
  "parsed": {"stage_location": "TOP", "sections": []},
  "profile": "ocr",
  "model": "qwen2.5vl:7b",
  "provider": "local-ollama",
  "elapsed_ms": 1247,
  "tokens_in": 1024,
  "tokens_out": 128,
  "cost_usd": 0.0,
  "seed_used": 42,
  "endpoint_used": "native"
}
```

Metadata fields:

- `tokens_in`, `tokens_out` - `null` if the provider does not report usage.
- `cost_usd` - `null` if usage or provider pricing is unavailable.
- `seed_used` - seed forwarded to the provider, or `null`.
- `endpoint_used` - for ollama, usually `native` or `openai`; for OpenRouter,
  `openai`.

## Image Options

Pipeline order:

```text
crop -> preprocess -> scale -> resize -> encode
```

Image fields:

- `crop` - pixel rectangle with top-left origin.
- `preprocess.sharpen.sigma` - unsharp mask strength, `> 0` and `<= 10`.
- `preprocess.contrast` - contrast multiplier, `> 0` and `<= 10`.
- `preprocess.brightness` - brightness multiplier, `> 0` and `<= 10`.
- `preprocess.binarize.threshold` - grayscale threshold, `0-255`.
- `scale` - scale multiplier, `> 0` and `<= 10`.
- `resize.width`, `resize.height` - target dimensions, `1-8192`.
- `resize.fit` - `fill`, `contain`, or `cover`.
- `resize.background` - hex color for `contain`, such as `#fff`,
  `#ffffff`, or `#ffffff80`.
- `format` - output encoding: `png`, `jpeg`, or `webp`.

Resize modes:

- `fill` - stretch to exact dimensions, ignoring aspect ratio.
- `contain` - preserve aspect ratio and letterbox with `background`.
- `cover` - preserve aspect ratio and center-crop to exact dimensions.

For layout-recall workloads with qwen2.5vl:7b-class models, the existing
project measurements found `format=png`, `fit=fill`, and `600x540` to be a
good default. `contain` can add letterbox pixels that some VLMs read as part
of the layout. Larger images are not always safer because output can truncate
when the model spends more context on visual tokens.

## Response Formats

Default mode returns raw text and leaves `parsed` as `null`.

Lenient JSON mode:

```bash
curl -X POST localhost:8000/api/detect \
  -F profile=ocr \
  -F image=@sample.png \
  -F 'options={"response_format":"json","temperature":0.0,"seed":42}'
```

In this mode the provider is asked for JSON. The server tries to parse the
model output after stripping a wrapping markdown JSON fence and normalizing
small VLM quirks such as signed integers, trailing commas, and double commas.
If parsing fails, the response still returns `200`; `text` is preserved and
`parsed` is `null`.

Structured JSON Schema mode:

```bash
curl -X POST localhost:8000/api/detect \
  -F profile=ocr \
  -F image=@sample.png \
  -F 'options={
    "response_format": {
      "type": "json_schema",
      "json_schema": {
        "name": "seat_layout",
        "schema": {
          "type": "object",
          "properties": {
            "stage_location": {
              "type": "string",
              "enum": ["TOP", "BOTTOM", "LEFT", "RIGHT", "CENTER"]
            },
            "sections": {"type": "array"}
          },
          "required": ["stage_location", "sections"]
        },
        "strict": true
      }
    },
    "max_tokens": 4096,
    "temperature": 0.0
  }'
```

In schema mode the server parses the output and validates it with
`jsonschema`. Parse failure or schema mismatch returns `422` with raw output
and a truncation signature in the error detail. The validator retries once
after dropping explicit `null` values from parsed objects, which handles a
common VLM optional-field quirk.

Provider note: the API currently rejects simple `response_format: "json"` for
the `openrouter` provider with `422`. Use `json_schema` mode for OpenRouter.

## Per-call Profile Overrides

Overrides do not persist to `profiles.json`.

```bash
curl -X POST localhost:8000/api/detect \
  -F profile=ocr \
  -F image=@sample.png \
  -F 'options={
    "profile_override": {
      "model": "qwen2.5vl:7b",
      "prompt": "Extract only visible Korean text.",
      "seed": 42
    }
  }'
```

Request-level `temperature` and `seed` take precedence over values inside
`profile_override`.

## Models API

```bash
curl localhost:8000/api/models
curl 'localhost:8000/api/models?vision_only=true'
curl localhost:8000/api/providers/local-ollama/models
curl 'localhost:8000/api/providers/local-ollama/models?vision_only=true'
```

Each model entry:

```json
{
  "name": "qwen2.5vl:7b",
  "family": "qwen25vl",
  "parameter_size": "7B",
  "quantization_level": "Q4_0",
  "context_length": 8192,
  "vision_capable": true,
  "source": "capabilities"
}
```

`source` values:

- `capabilities` - provider supplied an authoritative vision capability.
- `heuristic` - model name matched a conservative vision/OCR pattern.
- `unknown` - no signal was available.

## Health

```bash
curl localhost:8000/health
```

Example:

```json
{
  "status": "ok",
  "providers": ["local-ollama"],
  "profiles_loaded": 2,
  "vision_models": {"local-ollama": ["qwen2.5vl:7b"]}
}
```

The health endpoint is best-effort and should not return `5xx` just because
a provider cannot list models.

## Logging and Timing

Every response includes:

```text
X-Process-Time: <ms>ms
```

When run with `--log-config logging.json`, the middleware emits one
`vision_ocr_detect.request` line per request:

```text
method=POST path=/api/detect status=200 elapsed_ms=1247 params={"profile": "ocr", "options": {"response_format": "json"}}
```

Endpoints without extra context omit `params=...`.

## Errors

Common API errors:

- `400` - unknown provider in a profile or profile override.
- `404` - missing profile.
- `409` - duplicate profile name.
- `422` - invalid body/options/image, JSON parse failure in schema mode, or
  schema mismatch.
- `502` - upstream provider failure.
- `503` - concurrent detect request cap reached. Response includes
  `Retry-After: 1`.

`422` errors from schema mode include fields such as `text_length`,
`last_nonspace_char`, `ends_with_unclosed_brace`, `last_nonempty_line`, and
`suggestion`. A trailing `{`, `[`, `,`, `:`, or `"` usually points to model
output truncation; try raising `max_tokens` or using lenient JSON mode.

