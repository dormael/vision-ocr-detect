"""Unit tests for the image preprocessing pipeline."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from vision_ocr_detect.models.image import CropRegion, ImageOptions, ResizeSpec
from vision_ocr_detect.services.image_processor import (
    ImageProcessingError,
    ProcessedImage,
    process,
)


def _png(width: int, height: int, color=(255, 0, 0)) -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_no_options_returns_same_dimensions() -> None:
    raw = _png(64, 64)
    out = process(raw, ImageOptions())
    assert isinstance(out, ProcessedImage)
    assert (out.width, out.height) == (64, 64)
    assert out.mime_type == "image/png"


def test_crop_to_subregion() -> None:
    raw = _png(100, 100)
    out = process(
        raw,
        ImageOptions(crop=CropRegion(x=10, y=20, width=30, height=40)),
    )
    assert (out.width, out.height) == (30, 40)


def test_crop_out_of_bounds_raises() -> None:
    raw = _png(100, 100)
    with pytest.raises(ImageProcessingError, match="exceeds"):
        process(
            raw,
            ImageOptions(crop=CropRegion(x=90, y=90, width=50, height=50)),
        )


def test_scale_halves_dimensions() -> None:
    raw = _png(200, 100)
    out = process(raw, ImageOptions(scale=0.5))
    assert (out.width, out.height) == (100, 50)


def test_resize_overrides_dimensions() -> None:
    raw = _png(500, 300)
    out = process(raw, ImageOptions(resize=ResizeSpec(width=100, height=60)))
    assert (out.width, out.height) == (100, 60)


def test_crop_then_scale_combines() -> None:
    raw = _png(200, 200)
    out = process(
        raw,
        ImageOptions(
            crop=CropRegion(x=0, y=0, width=100, height=100),
            scale=0.5,
        ),
    )
    assert (out.width, out.height) == (50, 50)


def test_scale_then_resize_applies_resize_last() -> None:
    raw = _png(400, 400)
    out = process(
        raw,
        ImageOptions(scale=0.25, resize=ResizeSpec(width=80, height=80)),
    )
    # resize is applied after scale, so absolute size wins.
    assert (out.width, out.height) == (80, 80)


def test_format_jpeg_returns_jpeg_mime() -> None:
    raw = _png(50, 50)
    out = process(raw, ImageOptions(format="jpeg"))
    assert out.mime_type == "image/jpeg"


def test_format_converts_rgba_to_rgb_for_jpeg() -> None:
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    out = process(buf.getvalue(), ImageOptions(format="jpeg"))
    assert out.mime_type == "image/jpeg"


def test_invalid_image_raises() -> None:
    with pytest.raises(ImageProcessingError, match="could not decode"):
        process(b"not-an-image", ImageOptions())


def test_too_large_raises() -> None:
    # Pad with junk to exceed 20 MiB cap.
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * (21 * 1024 * 1024)
    with pytest.raises(ImageProcessingError, match="too large"):
        process(raw, ImageOptions())


def test_animated_gif_uses_first_frame() -> None:
    """Animated GIF: process() must extract the first frame, not corrupt or
    refuse. Output is re-encoded to the chosen (or source) format."""
    frames = [
        Image.new("RGB", (32, 32), color=(255, 0, 0)),
        Image.new("RGB", (32, 32), color=(0, 255, 0)),
        Image.new("RGB", (32, 32), color=(0, 0, 255)),
    ]
    buf = io.BytesIO()
    frames[0].save(
        buf, format="GIF", save_all=True, append_images=frames[1:], duration=100, loop=0
    )
    raw = buf.getvalue()

    out = process(raw, ImageOptions())
    # First frame is red; we can't directly inspect pixels in the encoded
    # bytes, but we can confirm the output is a valid image of correct size.
    # Default output format is PNG (vision-model friendly) regardless of
    # source format.
    assert (out.width, out.height) == (32, 32)
    assert out.mime_type == "image/png"
    # Round-trip the result and verify the first frame is the red one.
    decoded = Image.open(io.BytesIO(out.bytes))
    assert decoded.size == (32, 32)
    assert decoded.convert("RGB").getpixel((16, 16)) == (255, 0, 0)
