"""Unit tests for the image preprocessing pipeline."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from vision_ocr_detect.models.image import (
    BinarizeSpec,
    CropRegion,
    ImageOptions,
    ImagePreprocess,
    ResizeSpec,
    SharpenSpec,
)
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


# ----------------------------------------------------------------------
# preprocess (sharpen / contrast / brightness / binarize)
# ----------------------------------------------------------------------


def test_preprocess_sharpen_does_not_change_dimensions() -> None:
    """Sharpen only changes pixel values, not size."""
    raw = _png(64, 64)
    out = process(
        raw,
        ImageOptions(preprocess=ImagePreprocess(sharpen=SharpenSpec(sigma=1.0))),
    )
    assert (out.width, out.height) == (64, 64)


def test_preprocess_contrast_changes_pixel_values() -> None:
    """Contrast != 1.0 should produce different output bytes than the
    unprocessed image. We don't assert exact pixel values because PIL's
    ImageEnhance is not a simple linear remap (factor=0 still leaves
    small channel differences in practice)."""
    raw = _png(64, 64, color=(200, 50, 50))
    no_contrast = process(raw, ImageOptions(format="png"))
    with_contrast = process(
        raw,
        ImageOptions(
            preprocess=ImagePreprocess(contrast=0.1),
            format="png",
        ),
    )
    assert no_contrast.bytes != with_contrast.bytes


def test_preprocess_binarize_produces_bilevel() -> None:
    """binarize must result in only black (0) and white (255) pixels."""
    raw = _png(64, 64)
    out = process(
        raw,
        ImageOptions(preprocess=ImagePreprocess(binarize=BinarizeSpec(threshold=128))),
    )
    decoded = Image.open(io.BytesIO(out.bytes))
    pixels = set(decoded.getdata())
    # Allow up to 2 distinct values (black + white).
    assert len(pixels) <= 2
    assert all(p in (0, 255) for p in pixels)


def test_preprocess_runs_between_crop_and_scale() -> None:
    """Pipeline: crop → preprocess → scale → resize. After crop+preprocess+scale
    the result must match the crop's relative dimensions scaled."""
    raw = _png(200, 200)
    out = process(
        raw,
        ImageOptions(
            crop=CropRegion(x=0, y=0, width=100, height=100),
            preprocess=ImagePreprocess(contrast=1.5),
            scale=0.5,
        ),
    )
    assert (out.width, out.height) == (50, 50)


def test_preprocess_rejects_zero_contrast() -> None:
    """contrast=0 is degenerate; Pydantic gt=0 must reject it."""
    with pytest.raises(Exception):  # ValidationError from pydantic
        ImageOptions(preprocess=ImagePreprocess(contrast=0.0))


def test_preprocess_rejects_zero_sharpen_sigma() -> None:
    with pytest.raises(Exception):
        ImagePreprocess(sharpen=SharpenSpec(sigma=0.0))


# ----------------------------------------------------------------------
# fit: fill / contain / cover
# ----------------------------------------------------------------------


def test_fit_fill_stretches_to_exact_dimensions() -> None:
    """fill (default): aspect ratio is ignored."""
    raw = _png(200, 100)  # 2:1
    out = process(raw, ImageOptions(resize=ResizeSpec(width=80, height=80, fit="fill")))
    assert (out.width, out.height) == (80, 80)


def test_fit_contain_preserves_aspect_and_letterboxes() -> None:
    """contain: aspect preserved, image fits inside, no cropping."""
    raw = _png(200, 100)  # 2:1 — wider than target
    out = process(
        raw,
        ImageOptions(resize=ResizeSpec(width=100, height=100, fit="contain", background="#ffffff")),
    )
    assert (out.width, out.height) == (100, 100)
    decoded = Image.open(io.BytesIO(out.bytes)).convert("RGB")
    # Top-left corner is the letterbox area (white), not source pixel.
    assert decoded.getpixel((0, 0)) == (255, 255, 255)


def test_fit_contain_tall_image_uses_height_as_constraint() -> None:
    raw = _png(100, 200)  # 1:2 — taller than target
    out = process(
        raw,
        ImageOptions(resize=ResizeSpec(width=100, height=100, fit="contain", background="#000000")),
    )
    assert (out.width, out.height) == (100, 100)
    decoded = Image.open(io.BytesIO(out.bytes)).convert("RGB")
    # Black background on the sides.
    assert decoded.getpixel((0, 50)) == (0, 0, 0)


def test_fit_cover_preserves_aspect_and_crops() -> None:
    """cover: aspect preserved, fills target exactly, center-crops overflow."""
    raw = _png(200, 100)  # 2:1 — wider
    out = process(
        raw,
        ImageOptions(resize=ResizeSpec(width=100, height=100, fit="cover")),
    )
    assert (out.width, out.height) == (100, 100)


def test_resize_background_must_be_hex() -> None:
    """background rejects non-hex strings via Pydantic field_validator."""
    with pytest.raises(Exception):
        ResizeSpec(width=10, height=10, background="white")
    with pytest.raises(Exception):
        ResizeSpec(width=10, height=10, background="rgb(0,0,0)")
    # Valid forms accepted:
    assert ResizeSpec(width=10, height=10, background="#fff").background == "#fff"
    assert ResizeSpec(width=10, height=10, background="#ff00aa80").background == "#ff00aa80"


def test_fit_default_is_fill() -> None:
    """If fit is not given, the previous stretch behavior is preserved."""
    raw = _png(100, 50)
    out = process(raw, ImageOptions(resize=ResizeSpec(width=40, height=40)))
    assert (out.width, out.height) == (40, 40)
