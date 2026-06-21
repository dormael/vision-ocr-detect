"""`POST /api/detect` endpoint.

multipart/form-data:
  - `image` (required): the image file
  - `profile` (required): profile name (must exist in the store)
  - `options` (optional): JSON string, parsed into DetectOptions

Behavior:
  - Concurrency-capped by an `asyncio.Semaphore` sized from
    `settings.server.max_concurrent_requests`. Over-cap requests get 503
    immediately (with `Retry-After: 1`).
  - Errors are mapped to HTTP codes; see `_map_error`.
"""

from __future__ import annotations

import asyncio
import json
import re
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import ValidationError

from vision_ocr_detect.config import Settings
from vision_ocr_detect.deps import get_provider_registry, get_profile_store, get_settings
from vision_ocr_detect.models.detect import (
    DetectOptions,
    DetectResponse,
    JsonSchemaResponseFormat,
)
from vision_ocr_detect.providers.base import VisionProvider
from vision_ocr_detect.providers.registry import ProviderRegistry
from vision_ocr_detect.services.image_processor import (
    ImageProcessingError,
    process as process_image,
)
from vision_ocr_detect.services.profile_store import ProfileStore


router = APIRouter(prefix="/api", tags=["detect"])

# When the concurrency cap is hit, we wait at most this long for a slot.
# Short enough to fail fast under load; long enough to absorb tiny spikes.
_ACQUIRE_TIMEOUT_S = 0.5


def _parse_options(raw: str | None) -> DetectOptions:
    if not raw:
        return DetectOptions()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"options must be valid JSON: {e.msg}",
        ) from e
    try:
        return DetectOptions.model_validate(data)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=e.errors(include_url=False),
        ) from e


# Match a ```json ... ``` (or bare ``` ... ```) fence wrapping the entire
# text. Captures the body so we can feed it to json.loads without mutating
# the raw `text` field that callers still receive.
_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?\s*```\s*$",
    re.DOTALL,
)


def _strip_markdown_fence(text: str) -> str:
    """Return the body of a markdown JSON fence, or the input unchanged.

    Only strips a fence that wraps the *entire* string. The raw `text`
    field is preserved — we don't mutate what the model returned.
    """
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text


def _validate_against_schema(
    candidate: dict, schema: dict
) -> dict | None:
    """Validate `candidate` against a JSON Schema. Return the (possibly
    unchanged) dict on success, or None on validation failure.

    Uses the `jsonschema` library with the Draft 2020-12 validator when
    available; falls back to Draft 7 if the schema doesn't declare a
    $schema (the most permissive default).
    """
    from jsonschema import Draft202012Validator, Draft7Validator
    from jsonschema.exceptions import SchemaError, ValidationError

    if not schema:
        # No schema given — accept anything (parsed must be a dict already).
        return candidate

    # Pick a validator that matches the schema's $schema, if any.
    decl = schema.get("$schema", "")
    try:
        if "2020-12" in decl:
            validator_cls = Draft202012Validator
        else:
            validator_cls = Draft7Validator
    except Exception:
        validator_cls = Draft7Validator

    try:
        validator_cls.check_schema(schema)
    except SchemaError:
        # The schema itself is invalid — treat as no schema (best-effort).
        return candidate

    validator = validator_cls(schema)
    try:
        validator.validate(candidate)
        return candidate
    except ValidationError:
        return None


@router.post("/detect", response_model=DetectResponse)
async def detect(
    request: Request,
    image: UploadFile = File(
        ...,
        description="Image file (PNG/JPEG/WebP/GIF). Max 20 MiB. Animated GIFs use the first frame.",
    ),
    profile: str = Form(
        ...,
        description="Profile name. Must exist (use GET /api/profiles).",
        examples=["ocr-default"],
    ),
    options: str | None = Form(
        default=None,
        description=(
            "Optional JSON string with per-call overrides. Schema:\n"
            "```json\n"
            "{\n"
            '  "image": {\n'
            '    "crop":   {"x": 0, "y": 0, "width": 800, "height": 600},\n'
            '    "resize": {"width": 1024, "height": 768},\n'
            '    "scale":  0.5,\n'
            '    "format": "jpeg"\n'
            "  },\n"
            '  "max_tokens":  512,\n'
            '  "temperature": 0.0\n'
            "}\n"
            "```\n"
            "Pipeline order: crop → scale → resize → encode."
        ),
        examples=['{"image":{"scale":0.5,"format":"jpeg"},"max_tokens":256}'],
    ),
    settings: Settings = Depends(get_settings),
    store: ProfileStore = Depends(get_profile_store),
    registry: ProviderRegistry = Depends(get_provider_registry),
) -> DetectResponse:
    parsed = _parse_options(options)
    semaphore: asyncio.Semaphore = request.app.state.detect_semaphore

    # --- concurrency gate ---
    try:
        async with asyncio.timeout(_ACQUIRE_TIMEOUT_S):
            await semaphore.acquire()
    except TimeoutError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="server at concurrent-request limit; retry shortly",
            headers={"Retry-After": "1"},
        ) from e

    started = time.perf_counter()
    try:
        # --- profile lookup ---
        try:
            prof = store.get(profile)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"profile '{profile}' not found",
            )

        # --- apply profile_override (one-off; not persisted) ---
        ov = parsed.profile_override
        if ov is not None:
            if ov.provider is not None and ov.provider != prof.provider:
                # Cross-provider override: validate the new provider name.
                if ov.provider not in settings.providers:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"profile_override.provider '{ov.provider}' "
                            f"is not configured; available: "
                            f"{sorted(settings.providers.keys())}"
                        ),
                    )
            prof = prof.model_copy(
                update={
                    "provider": ov.provider if ov.provider is not None else prof.provider,
                    "model": ov.model if ov.model is not None else prof.model,
                    "prompt": ov.prompt if ov.prompt is not None else prof.prompt,
                }
            )

        # --- provider lookup ---
        try:
            provider: VisionProvider = registry.get(prof.provider)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"profile references unknown provider '{prof.provider}'",
            )

        # --- image preprocessing ---
        raw = await image.read()
        try:
            processed = process_image(raw, parsed.image)
        except ImageProcessingError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(e),
            ) from e

        # --- model call ---
        # temperature/seed: request-level beats profile_override beats None.
        # (profile doesn't store these; only per-call.)
        eff_temperature = parsed.temperature
        eff_seed = parsed.seed
        if ov is not None:
            if eff_temperature is None:
                eff_temperature = ov.temperature
            if eff_seed is None:
                eff_seed = ov.seed

        # Normalize response_format for the provider:
        #   - None → None
        #   - "json" → "json"
        #   - {type: "json_schema", ...} → the dict as-is (ollama accepts it)
        provider_format: str | dict | None
        if parsed.response_format is None:
            provider_format = None
        elif isinstance(parsed.response_format, str):
            provider_format = parsed.response_format
        else:  # JsonSchemaResponseFormat
            provider_format = parsed.response_format.model_dump(
                mode="json", by_alias=True
            )

        try:
            text = await provider.detect(
                processed.bytes,
                processed.mime_type,
                prof.model,
                prof.prompt,
                max_tokens=parsed.max_tokens,
                temperature=eff_temperature,
                seed=eff_seed,
                response_format=provider_format,
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"provider '{prof.provider}' failed: {e!s}",
            ) from e

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        # Parse + validate. Three modes:
        #   - None → parsed=None unconditionally
        #   - "json" → lenient parse; on failure parsed=None, text preserved
        #   - json_schema → parse + schema validation; either failure → 422
        parsed_json: dict | None = None
        rf = parsed.response_format
        if rf is not None:
            stripped = _strip_markdown_fence(text)
            try:
                candidate = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                candidate = None
            if isinstance(candidate, dict):
                if isinstance(rf, JsonSchemaResponseFormat):
                    parsed_json = _validate_against_schema(
                        candidate, rf.json_schema.schema_
                    )
                    if parsed_json is None:
                        # Schema mismatch → 422.
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                            detail=(
                                f"model output did not match response_format."
                                f"json_schema; raw={text!r}"
                            ),
                        )
                else:
                    parsed_json = candidate
            else:
                # JSON parse failed (or result wasn't a dict).
                if isinstance(rf, JsonSchemaResponseFormat):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail=(
                            f"response_format=json_schema requires valid JSON "
                            f"object output; raw={text!r}"
                        ),
                    )
                # "json" mode: lenient → parsed=None is acceptable.

        return DetectResponse(
            text=text,
            profile=prof.name,
            model=prof.model,
            provider=prof.provider,
            elapsed_ms=elapsed_ms,
            parsed=parsed_json,
        )
    finally:
        semaphore.release()
