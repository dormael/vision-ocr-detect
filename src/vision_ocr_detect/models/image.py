"""Image preprocessing options applied before sending to the vision model.

All operations are pixel-based. The pipeline order (chosen by the
processor) is: crop → scale → resize → encode.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OutputFormat = Literal["png", "jpeg", "webp"]


class CropRegion(BaseModel):
    """Pixel-space rectangle. Origin is top-left."""

    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ResizeSpec(BaseModel):
    """Target dimensions in pixels."""

    model_config = ConfigDict(extra="forbid")

    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)


class ImageOptions(BaseModel):
    """Bundle of preprocessing operations.

    Each field is independent and optional. The processor decides how to
    combine them — see `services/image_processor.py`.
    """

    model_config = ConfigDict(extra="forbid")

    crop: CropRegion | None = None
    resize: ResizeSpec | None = None
    scale: float | None = Field(default=None, gt=0.0, le=10.0)
    format: OutputFormat | None = None
