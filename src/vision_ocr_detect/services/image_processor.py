"""Image preprocessing pipeline.

Wraps Pillow to apply `ImageOptions` to a raw image and produce the bytes +
mime_type that the ollama provider expects.

Pipeline: decode (PIL) → crop → preprocess → scale → resize → encode

Notes:
  - `crop` removes pixels outside the rectangle (if given).
  - `preprocess` applies pixel-value corrections at the current resolution.
  - `scale` multiplies current size by a factor (e.g. 0.5 = half-size).
  - `resize` overrides the final dimensions to an absolute pixel size, with
    aspect-ratio handling via `fit`.
  - `format` re-encodes the result (e.g. `jpeg` to shrink base64 payload).
    When None, output is PNG (the safe default for vision models).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageEnhance, ImageFilter, UnidentifiedImageError

from vision_ocr_detect.models.image import ImageOptions, ResizeFit


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
        img = Image.open(io.BytesIO(raw))
    except (UnidentifiedImageError, OSError) as e:
        raise ImageProcessingError(f"could not decode image: {e}") from e
    # Animated GIF: PIL exposes the first frame by default, but the underlying
    # file handle is shared and may not survive serialization. Force a copy
    # so subsequent operations don't touch the original buffer. `copy()` drops
    # `format`, so remember and re-apply it.
    if getattr(img, "is_animated", False):
        img.seek(0)
        copied = img.copy()
        copied.format = img.format
        img = copied
    return img


def _encode(img: Image.Image, fmt: str | None) -> tuple[bytes, str]:
    """Encode `img` to the target format. Returns (bytes, mime_type).

    If `fmt` is None, defaults to PNG. PNG is the safe universal choice for
    vision models; even if the source is e.g. GIF (animated → static), we
    re-encode to a single-frame format the model can handle.
    """
    out_fmt = (fmt or "png").lower()
    pil_fmt = _FORMAT_TABLE.get(out_fmt)
    if pil_fmt is None:
        raise ImageProcessingError(f"unsupported output format '{out_fmt}'")

    # JPEG can't store alpha — flatten onto white.
    buf = io.BytesIO()
    if pil_fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    img.save(buf, format=pil_fmt)
    return buf.getvalue(), _MIME_TABLE[out_fmt]


# ----------------------------------------------------------------------
# preprocess (pixel-value corrections)
# ----------------------------------------------------------------------


def _apply_preprocess(img: Image.Image, opts) -> Image.Image:
    """Apply sharpening/contrast/brightness/binarize in declaration order."""
    from vision_ocr_detect.models.image import ImagePreprocess

    if not isinstance(opts, ImagePreprocess):
        return img
    if opts.sharpen is not None:
        img = img.filter(ImageFilter.UnsharpMask(radius=opts.sharpen.sigma * 2, percent=150, threshold=3))
    if opts.contrast is not None:
        img = ImageEnhance.Contrast(img).enhance(opts.contrast)
    if opts.brightness is not None:
        img = ImageEnhance.Brightness(img).enhance(opts.brightness)
    if opts.binarize is not None:
        # L mode = grayscale; threshold per spec.
        gray = img.convert("L")
        t = opts.binarize.threshold
        img = gray.point(lambda p: 255 if p > t else 0)
    return img


# ----------------------------------------------------------------------
# resize (with fit: fill / contain / cover)
# ----------------------------------------------------------------------


def _parse_hex_color(hexstr: str) -> tuple[int, int, int, int]:
    """`#fff` / `#ffffff` / `#rrggbbaa` → (r, g, b, a)."""
    h = hexstr.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) == 6:
        h += "ff"
    r, g, b, a = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16)
    return (r, g, b, a)


def _canvas_mode_for(img: Image.Image) -> str:
    """PIL mode that can host RGBA fill color matching the source's channels."""
    return img.mode if img.mode in ("RGB", "RGBA") else "RGB"


def _resize_with_fit(
    img: Image.Image, target_w: int, target_h: int, fit: ResizeFit, bg: str
) -> Image.Image:
    if fit == "fill":
        return img.resize((target_w, target_h), Image.Resampling.LANCZOS)

    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        raise ImageProcessingError("cannot resize a zero-dimension image")

    src_ratio = src_w / src_h
    tgt_ratio = target_w / target_h
    if src_ratio > tgt_ratio:
        # source is wider; width matches, height is smaller (contain) or
        # height matches, width is larger (cover).
        if fit == "contain":
            new_w, new_h = target_w, max(1, round(target_w / src_ratio))
        else:  # cover
            new_w, new_h = max(1, round(target_h * src_ratio)), target_h
    else:
        if fit == "contain":
            new_w, new_h = max(1, round(target_h * src_ratio)), target_h
        else:  # cover
            new_w, new_h = target_w, max(1, round(target_w / src_ratio))

    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    if fit == "contain":
        # Paste onto canvas filled with background.
        r, g, b, a = _parse_hex_color(bg)
        canvas = Image.new(_canvas_mode_for(resized), (target_w, target_h), (r, g, b))
        if resized.mode == "RGBA":
            canvas = canvas.convert("RGBA")
        canvas.paste(resized, ((target_w - new_w) // 2, (target_h - new_h) // 2))
        return canvas

    # cover: center-crop to exact target.
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def process(raw: bytes, options: ImageOptions) -> ProcessedImage:
    """Apply `options` to `raw` and return the encoded result.

    Pipeline: decode → crop → preprocess → scale → resize → encode.
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
        if c.x + c.width > src_w or c.y + c.height > src_h:
            raise ImageProcessingError(
                f"crop {c.model_dump()} exceeds image size {src_w}x{src_h}"
            )
        img = img.crop((c.x, c.y, c.x + c.width, c.y + c.height))

    # ---- 2. preprocess (at current resolution) ----
    if options.preprocess is not None:
        img = _apply_preprocess(img, options.preprocess)

    # ---- 3. scale (relative multiplier) ----
    if options.scale is not None:
        new_size = (
            max(1, int(img.size[0] * options.scale)),
            max(1, int(img.size[1] * options.scale)),
        )
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    # ---- 4. resize (absolute target, with fit) ----
    if options.resize is not None:
        img = _resize_with_fit(
            img,
            options.resize.width,
            options.resize.height,
            options.resize.fit,
            options.resize.background,
        )

    # ---- 5. encode ----
    data, mime = _encode(img, options.format)

    return ProcessedImage(
        bytes=data,
        mime_type=mime,
        width=img.size[0],
        height=img.size[1],
    )
