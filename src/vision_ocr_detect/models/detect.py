"""Detect request/response models.

The HTTP body comes in as multipart/form-data with:
  - `image`: required file
  - `profile`: required form field (profile name)
  - `options`: optional form field, a JSON string parsed into DetectOptions
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from vision_ocr_detect.models.image import ImageOptions


class DetectOptions(BaseModel):
    """Per-call overrides on top of the profile's defaults."""

    model_config = ConfigDict(extra="forbid")

    image: ImageOptions = Field(default_factory=ImageOptions)
    max_tokens: int | None = Field(default=None, gt=0, le=8192)
    temperature: float | None = Field(default=None, ge=0, le=2)


class DetectResponse(BaseModel):
    text: str
    profile: str
    model: str
    provider: str
    elapsed_ms: int
