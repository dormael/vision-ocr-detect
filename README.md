# vision-ocr-detect

Local **ollama** vision/OCR models exposed as an HTTP API. Manage named
profiles (provider + model + prompt) at runtime, then call
`POST /api/detect` with an image to get extracted text back.

- Built with **FastAPI** + **httpx** + **Pillow** + **pydantic v2**
- Single-file config and profile store (no DB)
- Pluggable providers — `ollama` today, OpenAI-compatible vLLM / others
  later
- Image preprocessing pipeline:
  `crop → preprocess → scale → resize → encode`
  (PNG / JPEG / WebP / GIF input; `fit`: fill / contain / cover;
  sharpening, contrast, brightness, binarize)
- Per-call overrides: `profile_override` (one-off provider / model /
  prompt / temperature / seed) and `response_format` (`"json"` → `parsed`
  populated on success, `null` on parse failure)
- Concurrency-capped via `asyncio.Semaphore`

## Install

```bash
uv sync
cp config.example.json config.json
cp profiles.example.json profiles.json
```

Edit `config.json` to point at your ollama instance (default is
`http://localhost:11434`).

## Run

```bash
uv run vision-ocr-detect          # uses config.json
# or
uv run uvicorn vision_ocr_detect.main:app --host 0.0.0.0 --port 8000
```

OpenAPI docs at `http://localhost:8000/docs`.

## API

### Profiles

| Method | Path | Body | Notes |
|---|---|---|---|
| `GET`    | `/api/profiles`         | — | list all (`?tag=<name>` filters by tag) |
| `GET`    | `/api/profiles/{name}`  | — | one profile |
| `POST`   | `/api/profiles`         | `{name, provider, model, prompt, description?, tags?}` | 201 / 409 (dup) / 422 (bad name / tags) / 400 (unknown provider) |
| `PUT`    | `/api/profiles/{name}`  | partial `{provider?, model?, prompt?, description?, tags?}` | 200 / 404 / 422 (PATCH-style: omitted fields preserved) |
| `DELETE` | `/api/profiles/{name}`  | — | 204 / 404 |

Profile fields beyond `name/provider/model/prompt`:
- `description: string | null` — free-text, max 500 chars
- `tags: string[]` — max 20; each is lowercased alphanumeric + `-`/`_`, 1-32 chars; duplicates collapsed

`tags` lets clients organize profiles (e.g. `["layout", "venue-kbs"]`) and
filter via `GET /api/profiles?tag=layout`. Legacy profile JSON without
these fields loads with `tags=[]`, `description=null`.

### Detect

```
POST /api/detect
Content-Type: multipart/form-data

  image:    <file>              (required; PNG / JPEG / WebP / GIF;
                                animated GIFs use the first frame)
  profile:  <string>            (required — profile name)
  options:  <JSON string>       (optional, see below)
```

`options` schema (all fields optional):

```json
{
  "image": {
    "crop":   {"x": 0, "y": 0, "width": 800, "height": 600},
    "preprocess": {
      "sharpen":    {"sigma": 1.0},
      "contrast":   1.2,
      "brightness": 1.0,
      "binarize":   {"threshold": 128}
    },
    "resize": {"width": 1024, "height": 768, "fit": "fill", "background": "#ffffff"},
    "scale":  0.5,
    "format": "jpeg"
  },
  "max_tokens":       512,
  "temperature":      0.0,
  "seed":             42,
  "response_format":  "json",
  "profile_override": {
    "provider":    "local-ollama",
    "model":       "qwen2.5vl:7b",
    "prompt":      "Extract the seat layout as JSON.",
    "temperature": 0.0,
    "seed":        42
  }
}
```

Pipeline order is **crop → preprocess → scale → resize → encode**.

- `image.preprocess`: pixel-value corrections applied at the current
  resolution, in declaration order (`sharpen` → `contrast` → `brightness`
  → `binarize`). Unset fields pass through unchanged. Binarize loses
  information — only use it for OCR-style pipelines.
- `image.resize.fit`:
  - `fill` (default) — stretch to exact dimensions, ignoring aspect ratio
  - `contain` — preserve aspect ratio, letterbox with `background`
  - `cover` — preserve aspect ratio, center-crop to exact dimensions

  **Trade-off observed in the interpark-ticket use case (3-venue recall
  measurement, qwen2.5vl:7b)**: `fit=contain` adds white padding around
  the source image to preserve the aspect ratio. Some VLMs (qwen2.5vl:7b
  on KBS Hall layouts) misinterpret the letterbox as part of the seating
  area and misclassify `stage_location` as `CENTER` instead of `TOP`.

  Measured outcomes on 3 venues (26000382 / 26000634 / 26008115):

  | baseline                       | mean recall | mean precision | mean halluc | stage_location |
  |--------------------------------|-------------|----------------|-------------|----------------|
  | jpeg 1200x1080 `fit=contain`   | 0.512       | 0.577          | 0.090       | 1/3 ✓          |
  | **png 600x540 `fit=fill`**     | **0.897**   | **0.912**      | 0.088       | 2/3 ✓          |
  | png 600x540 `fit=cover`        | 0.892       | 0.943          | +2 sections | 2/3 ✓          |

  Recommendations for layout-recall workloads (qwen2.5vl:7b-class models):
  - **Default**: `format=png, fit=fill, size 600x540`. No padding, no
    cropping, smallest input that still preserves label detail. Smaller
    inputs leave more output-token headroom — 37-section venues fit
    comfortably without truncation.
  - **Aspect-preserving alternative**: `fit=cover` (center-crop). Recall
    is comparable but the cropped edge can produce hallucinated sections
    (observed: 306 / 307 on venue 26008115).
  - **Avoid `fit=contain`** when `stage_location` accuracy matters —
    white letterbox is occasionally read as part of the seating area.
  - **Caveat**: at small resolutions (≤600x540) the `STAGE` text label
    itself becomes less readable to the VLM. Venue 26000382 regressed
    from `TOP` (1200x1080) to `CENTER` (600x540). **Simply overriding
    to a larger image is not a safe workaround**: a direct A/B on
    26000382 with `fit=fill` controlled, size bumped from 600x540 to
    1200x1080, recovered `stage_location` but collapsed recall from
    0.815 to 0.037 (`tokens_out` 1398 → 116 — the 7B model
    self-truncated). For per-venue stage fix, prefer a rule-based
    correction over `image.resize`; the `image.resize` knob alone
    cannot optimise both axes in a single model pass.
- `image.resize.background`: hex color (`#rgb` / `#rrggbb` / `#rrggbbaa`),
  only used when `fit: "contain"`. Defaults to `#ffffff`.
- `response_format`: when set to `"json"`, the provider is asked to emit
  JSON. The server runs a **lenient JSON parser** that strips a wrapping
  ```json ... ``` markdown fence and normalizes common VLM quirks
  (`: +N` signed integers, trailing commas, double commas) before
  `json.loads`. `parsed` is populated on success; on failure, `parsed` is
  `null` and `text` still holds the raw output (the client can decide
  whether to retry or fall back to its own parser). The `text` field is
  never mutated.
  Alternatively, an OpenAI-style structured-output spec can be supplied:

  ```json
  {
    "response_format": {
      "type": "json_schema",
      "json_schema": {
        "name": "seat_layout",
        "schema": { "type": "object", "properties": {...}, "required": [...] }
      }
    }
  }
  ```

  In `json_schema` mode the server passes the spec to the provider as a
  structured-output constraint and validates the response against the
  schema using the `jsonschema` library. Both JSON parse failure and
  schema mismatch return **422** with the raw text in the error
  detail — clients should treat this as a hard failure and retry with
  a different model or prompt, not silently accept `parsed: null`.
  **Null-tolerance retry**: when schema validation fails, the server
  retries once with explicit `"field": null` values stripped from the
  parsed output before revalidating. This absorbs a common VLM quirk
  where the model emits `"field": null` for an optional field instead
  of omitting it; the schema (correctly) treats null as a type violation
  but is usually happy with the field missing. The raw `text` field is
  always preserved — the cleaning only affects `parsed`.
- `profile_override`: per-call override of the resolved profile. Unset
  fields fall back to the profile's value. `provider` is re-validated
  against the configured providers (400 on unknown). `temperature` is
  request-level > override > `None`. Note: `response_format` is currently
  limited to the literal string `"json"`; OpenAI-style
  `{"type":"json_schema", ...}` schema enforcement is **not** supported
  yet (no server-side schema validation).

Response:

```json
{
  "text": "extracted text...",
  "parsed": {"stage_location": "TOP", "sections": []},
  "profile": "ocr-default",
  "model": "glm-ocr:latest",
  "provider": "local-ollama",
  "elapsed_ms": 1247,
  "tokens_in": 1024,
  "tokens_out": 512,
  "cost_usd": 0.0,
  "seed_used": 42
}
```

`parsed` is `null` unless the request set `response_format: "json"` and
the response parsed successfully as a JSON object.

The `tokens_in/out`, `cost_usd`, `seed_used` fields are best-effort:
- `tokens_in/out` — `null` if the provider doesn't surface usage stats
  (older ollama); otherwise the prompt/completion token counts.
- `cost_usd` — derived from `cost_per_1k_*_tokens` in `config.json`. Local
  ollama defaults to `0.0`. Set non-zero values to track spend when you
  swap in a paid provider.
- `seed_used` — the seed actually forwarded to the provider, or `null`
  if neither the request nor `profile_override` set one.
- `endpoint_used` — `"native"` if the call went through ollama's
  `/api/generate` surface; `"openai"` if the native endpoint 404'd
  and we fell back to `/v1/chat/completions`. Most ollama vision
  models (granite-vision, minicpm-v, qwen2.5vl, etc.) work on the
  native surface; the fallback exists for models that only speak
  OpenAI-compat.

Error codes: `404` (profile / image issue), `422` (bad options / image),
`502` (provider failure), `503` (concurrency cap reached, with
`Retry-After: 1`).

### Health

```
GET /health
→ {
    "status": "ok",
    "providers": ["local-ollama"],
    "profiles_loaded": 2,
    "vision_models": {"local-ollama": ["qwen2.5vl:7b", "glm-ocr:latest"]}
  }
```

### Models

```
GET /api/models                            # all providers, all models
GET /api/models?vision_only=true           # only vision-capable models
GET /api/providers/{name}/models           # one provider, all models
GET /api/providers/{name}/models?vision_only=true
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

`vision_capable` classification:
- `"capabilities"` — provider's authoritative signal (ollama ≥ 0.3.12
  exposes a `capabilities` field on `/api/tags` listing `"vision"` when
  applicable). Used as-is.
- `"heuristic"` — provider didn't expose capabilities; we matched the
  model name against conservative patterns (`*-vl*`, `llava*`,
  `moondream`, `*-ocr`, etc.).
- `"unknown"` — no capability signal and no name match → defaults to
  not vision-capable.

Useful for the interpark-ticket use case: filter `vision_only=true`
to pick a layout-extraction candidate before saving a profile.

## End-to-end example

```bash
# 1. Create a profile
curl -X POST localhost:8000/api/profiles -H 'content-type: application/json' \
  -d '{"name":"ocr","provider":"local-ollama","model":"glm-ocr:latest","prompt":"Extract all text from this image."}'

# 2. Detect
curl -X POST localhost:8000/api/detect \
  -F profile=ocr \
  -F image=@sample.png \
  -F 'options={"image":{"format":"jpeg","scale":0.5},"max_tokens":256}'

# 3. List
curl localhost:8000/api/profiles
```

### Examples: per-call overrides

```bash
# One-off model + seed without creating a new profile
curl -X POST localhost:8000/api/detect \
  -F profile=ocr \
  -F image=@sample.png \
  -F 'options={"profile_override":{"model":"qwen2.5vl:7b","seed":42}}'

# Ask for structured JSON output
curl -X POST localhost:8000/api/detect \
  -F profile=ocr \
  -F image=@sample.png \
  -F 'options={"response_format":"json","temperature":0.0,"seed":42}'

# Small-label OCR with sharpening and contrast, then letterboxed 2x upscale
curl -X POST localhost:8000/api/detect \
  -F profile=ocr \
  -F image=@sample.png \
  -F 'options={"image":{"preprocess":{"sharpen":{"sigma":1.0},"contrast":1.2},"resize":{"width":1200,"height":1080,"fit":"contain","background":"#000000"}}}'

# Animated GIF upload — first frame is processed
curl -X POST localhost:8000/api/detect \
  -F profile=ocr \
  -F image=@sample.gif \
  -F 'options={"image":{"format":"jpeg"}}'
```

## Configuration (`config.json`)

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
    }
  }
}
```

`cost_per_1k_input_tokens` / `cost_per_1k_output_tokens` (USD) drive the
`cost_usd` field in detect responses. Leave at `0.0` for local ollama.

Override the path with `VISION_OCR_CONFIG=...` (same for
`VISION_OCR_PROFILES`).

## Adding a new provider type

1. Implement `VisionProvider` in `src/vision_ocr_detect/providers/<name>.py`.
2. Register the builder in `registry._BUILDERS`.
3. Add a new `ProviderConfig.type` literal in `config.py`.

## Testing

```bash
uv run pytest                                # all tests
uv run pytest tests/test_provider_smoke.py   # live ollama roundtrip
```

The suite uses a `FakeProvider` to exercise the API end-to-end without
hitting the network; only `test_provider_smoke.py` talks to real ollama
(and skips if unreachable).

## Limits & future work

- **No API auth yet.** `config.providers.*.api_key` field is wired but
  not enforced.
- **No streaming.** OCR responses are short; if you need streaming,
  add SSE on `/api/detect`.
- **No request caching.** Identical image+profile calls re-run.
- **Single-process profile store.** Filesystem lock protects against
  external mutations, but multi-replica deployments need a real DB.