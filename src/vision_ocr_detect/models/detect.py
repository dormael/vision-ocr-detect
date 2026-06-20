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
    max_tokens: int | None = Field(default=None, gt=0, le=8192)
    temperature: float | None = Field(default=None, ge=0, le=2)
    profile_override: ProfileOverride | None = None
    # When set, the provider is asked to emit JSON. The server does NOT
    # validate against a specific schema (no jsonschema dependency) — it
    # only parses `text` best-effort into `parsed`. If the model returns
    # invalid JSON, `parsed` is null and `text` still holds the raw output.
    response_format: Literal["json"] | None = None


class DetectResponse(BaseModel):
    text: str
    profile: str
    model: str
    provider: str
    elapsed_ms: int
    parsed: dict[str, Any] | None = None