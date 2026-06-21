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
| `GET`    | `/api/profiles`         | — | list all |
| `GET`    | `/api/profiles/{name}`  | — | one profile |
| `POST`   | `/api/profiles`         | `{name, provider, model, prompt}` | 201 / 409 (dup) / 422 (bad name) / 400 (unknown provider) |
| `PUT`    | `/api/profiles/{name}`  | partial `{provider?, model?, prompt?}` | 200 / 404 / 422 |
| `DELETE` | `/api/profiles/{name}`  | — | 204 / 404 |

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
- `image.resize.background`: hex color (`#rgb` / `#rrggbb` / `#rrggbbaa`),
  only used when `fit: "contain"`. Defaults to `#ffffff`.
- `response_format`: when set to `"json"`, the provider is asked to emit
  JSON. The server attempts a lenient `json.loads` on the response and
  populates `parsed` on success; if parsing fails, `parsed` is `null` and
  `text` still holds the raw output (the client decides what to do).
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
  "elapsed_ms": 1247
}
```

`parsed` is `null` unless the request set `response_format: "json"` and
the response parsed successfully as a JSON object.

Error codes: `404` (profile / image issue), `422` (bad options / image),
`502` (provider failure), `503` (concurrency cap reached, with
`Retry-After: 1`).

### Health

```
GET /health
→ {"status": "ok", "providers": ["local-ollama"], "profiles_loaded": 2}
```

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
      "timeout_seconds": 300
    }
  }
}
```

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