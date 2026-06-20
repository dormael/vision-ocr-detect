"""Image preprocessing pipeline.

Wraps Pillow to apply `ImageOptions` to a raw image and produce the bytes +
mime_type that the ollama provider expects.

Pipeline: decode (PIL) → crop → scale → resize → encode (PIL)

Notes:
  - `crop` removes pixels outside the rectangle (if given).
  - `scale` multiplies current size by a factor (e.g. 0.5 = half-size).
  - `resize` overrides the final dimensions to an absolute pixel size.
  - `format` re-encodes the result (e.g. `jpeg` to shrink base64 payload).
    When None, the source format is preserved.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from vision_ocr_detect.models.image import ImageOptions


# 20 MiB: matches the plan's `413` boundary. Generous for OCR; some
# screenshots and book-page scans exceed 5 MiB easily.
MAX_INPUT_BYTES = 20 * 1024 * 1024

# Pillow uses uppercase format names ("PNG", "JPEG", "WEBP").
_FORMAT_TABLE: dict[str, str] = {
    "png": "PNG",
    "jpeg": "JPEG",
    "webp": "WEBP",
}

# mime type returned alongside the encoded bytes (consumed by the provider).
_MIME_TABLE: dict[str, str] = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


class ImageProcessingError(Exception):
    """Raised for unrecoverable image issues (bad format, oob crop, ...)."""


@dataclass(frozen=True)
class ProcessedImage:
    """Result of preprocessing."""

    bytes: bytes
    mime_type: str
    width: int
    height: int


def _decode(raw: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(raw))
    except UnidentifiedImageError as e:
        raise ImageProcessingError("could not identify image format") from e


def _encode(img: Image.Image, fmt: str | None) -> tuple[bytes, str]:
    """Encode `img` to the target format. Returns (bytes, mime_type).

    If `fmt` is None, re-encode in the source format (this strips metadata
    and normalizes the payload — desirable when forwarding to a model).
    """
    out_fmt = (fmt or img.format or "PNG").lower()
    pil_fmt = _FORMAT_TABLE.get(out_fmt)
    if pil_fmt is None:
        raise ImageProcessingError(f"unsupported output format '{out_fmt}'")

    # JPEG can't store alpha — flatten onto white.
    buf = io.BytesIO()
    if pil_fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    img.save(buf, format=pil_fmt)
    return buf.getvalue(), _MIME_TABLE[out_fmt]


def process(raw: bytes, options: ImageOptions) -> ProcessedImage:
    """Apply `options` to `raw` and return the encoded result.

    Pipeline: decode → crop → scale → resize → encode.
    All operations are no-ops when their option is None.
    """
    if len(raw) > MAX_INPUT_BYTES:
        raise ImageProcessingError(
            f"image too large: {len(raw)} > {MAX_INPUT_BYTES} bytes"
        )

    img = _decode(raw)
    src_w, src_h = img.size

    # ---- 1. crop (in source coordinates) ----
    if options.crop is not None:
        c = options.crop
        # Boundary check before mutating image state.
        if c.x + c.width > src_w or c.y + c.height > src_h:
            raise ImageProcessingError(
                f"crop {c.model_dump()} exceeds image size {src_w}x{src_h}"
            )
        img = img.crop((c.x, c.y, c.x + c.width, c.y + c.height))

    # ---- 2. scale (relative multiplier) ----
    if options.scale is not None:
        new_size = (max(1, int(img.size[0] * options.scale)),
                    max(1, int(img.size[1] * options.scale)))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    # ---- 3. resize (absolute target) ----
    if options.resize is not None:
        img = img.resize(
            (options.resize.width, options.resize.height),
            Image.Resampling.LANCZOS,
        )

    # ---- 4. encode ----
    data, mime = _encode(img, options.format)

    return ProcessedImage(
        bytes=data,
        mime_type=mime,
        width=img.size[0],
        height=img.size[1],
    )
