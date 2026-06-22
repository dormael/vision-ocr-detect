"""Detect request/response models.

The HTTP body comes in as multipart/form-data with:
  - `image`: required file
  - `profile`: required form field (profile name)
  - `options`: optional form field, a JSON string parsed into DetectOptions
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from vision_ocr_detect.models.image import ImageOptions


class JsonSchemaSpec(BaseModel):
    """JSON Schema for response_format=json_schema.

    Mirrors the OpenAI-style `json_schema` object. We accept an arbitrary
    JSON Schema dict — the server validates the model's output against it
    when present (best-effort; relies on the `jsonschema` library).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    schema_: dict[str, Any] = Field(
        default_factory=dict,
        alias="schema",
        description="JSON Schema object (https://json-schema.org/).",
    )
    strict: bool = True


class JsonSchemaResponseFormat(BaseModel):
    """OpenAI-style structured-output request.

    Example:
        {"type": "json_schema", "json_schema": {"name": "seat_layout", "schema": {...}}}
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["json_schema"]
    json_schema: JsonSchemaSpec


class ProfileOverride(BaseModel):
    """Per-call overrides on the resolved profile.

    Allows one-off experiments without persisting a new profile. Any unset
    field falls back to the profile's value. The `provider` field is
    re-validated against the configured providers; an unknown provider
    returns 400.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    model: str | None = None
    prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    seed: int | None = None


class DetectOptions(BaseModel):
    """Per-call overrides on top of the profile's defaults."""

    model_config = ConfigDict(extra="forbid")

    image: ImageOptions = Field(default_factory=ImageOptions)
    # Upper bound raised to 16384 after the requester hit the 8192 cap
    # while measuring recall across 4 venues. Ollama accepts up to
    # num_predict of the model's context size; this is a server-side
    # sanity cap rather than a strict provider limit.
    max_tokens: int | None = Field(default=None, gt=0, le=16384)
    temperature: float | None = Field(default=None, ge=0, le=2)
    seed: int | None = None
    profile_override: ProfileOverride | None = None
    # Three accepted shapes:
    #   - None (default): free-form text
    #   - "json": provider is asked to emit JSON; server parses leniently.
    #   - {type: "json_schema", json_schema: {...}}: server validates the
    #     model's output against the supplied JSON Schema. If validation
    #     fails, the request returns 422 with the schema error detail.
    response_format: Literal["json"] | JsonSchemaResponseFormat | None = None


class DetectResponse(BaseModel):
    text: str
    profile: str
    model: str
    provider: str
    elapsed_ms: int
    parsed: dict[str, Any] | None = None
    # Optional call metadata. None when the provider doesn't surface
    # usage stats (older ollama) or when no seed was set.
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    seed_used: int | None = None
    # Records which underlying API the provider used when it had a
    # choice (e.g. ollama "native" /api/generate vs "openai" OpenAI-compat
    # chat endpoint). None when there's no choice to make.
    endpoint_used: str | None = None