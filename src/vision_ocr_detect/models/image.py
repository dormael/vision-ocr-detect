"""Image preprocessing options applied before sending to the vision model.

Pipeline order: crop → preprocess → scale → resize → encode.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


OutputFormat = Literal["png", "jpeg", "webp"]
ResizeFit = Literal["fill", "contain", "cover"]
# Hex color: #rgb, #rrggbb, or #rrggbbaa. Validated in ResizeSpec.background.

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


class CropRegion(BaseModel):
    """Pixel-space rectangle. Origin is top-left."""

    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ResizeSpec(BaseModel):
    """Target dimensions in pixels.

    `fit`:
      - `fill` (default): stretch to exact dimensions, ignoring aspect ratio.
      - `contain`: preserve aspect ratio, letterbox with `background` color.
      - `cover`: preserve aspect ratio, center-crop to exact dimensions.
    """

    model_config = ConfigDict(extra="forbid")

    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)
    fit: ResizeFit = "fill"
    background: str = "#ffffff"

    @field_validator("background")
    @classmethod
    def _check_hex(cls, v: str) -> str:
        if not _HEX_RE.match(v):
            raise ValueError(
                f"background must be a hex color like '#fff' or '#ffffff' or "
                f"'#ffffff80'; got {v!r}"
            )
        return v


class SharpenSpec(BaseModel):
    """Unsharp-mask sharpening.

    Higher `sigma` = stronger sharpening. 0 is rejected because UnsharpMask
    with sigma=0 is undefined in Pillow.
    """

    model_config = ConfigDict(extra="forbid")

    sigma: float = Field(gt=0.0, le=10.0)


class BinarizeSpec(BaseModel):
    """Convert to grayscale and threshold.

    Pixels above `threshold` become white (255), others become black (0).
    """

    model_config = ConfigDict(extra="forbid")

    threshold: int = Field(ge=0, le=255)


class ImagePreprocess(BaseModel):
    """Pixel-value corrections applied at the original resolution.

    Operations compose in declaration order. Each is independent; unset
    fields pass through unchanged. Note: aggressive settings (binarize)
    lose information and may hurt accuracy for non-OCR use cases.
    """

    model_config = ConfigDict(extra="forbid")

    sharpen: SharpenSpec | None = None
    contrast: float | None = Field(default=None, gt=0.0, le=10.0)
    brightness: float | None = Field(default=None, gt=0.0, le=10.0)
    binarize: BinarizeSpec | None = None


class ImageOptions(BaseModel):
    """Bundle of preprocessing operations.

    Each field is independent and optional. The processor decides how to
    combine them — see `services/image_processor.py`.
    """

    model_config = ConfigDict(extra="forbid")

    crop: CropRegion | None = None
    preprocess: ImagePreprocess | None = None
    resize: ResizeSpec | None = None
    scale: float | None = Field(default=None, gt=0.0, le=10.0)
    format: OutputFormat | None = None