"""Provider smoke test against the local ollama instance.

Skipped if ollama is unreachable. Verifies that the OpenAI-compat
`/v1/chat/completions` endpoint accepts our payload and returns text.
"""

from __future__ import annotations

import asyncio
import base64
import io

import httpx
import pytest
from PIL import Image


def _png_bytes(color: tuple[int, int, int] = (255, 0, 0), size: int = 128) -> bytes:
    img = Image.new("RGB", (size, size), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _ollama_reachable(base_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{base_url.rstrip('/')}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


@pytest.mark.asyncio
async def test_ollama_detect_red_image() -> None:
    from vision_ocr_detect.config import ProviderConfig
    from vision_ocr_detect.providers.ollama import OllamaProvider

    base_url = "http://localhost:11434"
    if not await _ollama_reachable(base_url):
        pytest.skip(f"ollama not reachable at {base_url}")

    provider = OllamaProvider("local-ollama", ProviderConfig(
        type="ollama", base_url=base_url, timeout_seconds=60.0
    ))
    try:
        png = _png_bytes()
        text = await provider.detect(
            png, "image/png",
            "granite3.2-vision:2b",
            "What color is this solid image? Reply with one word.",
        )
        assert isinstance(text, str)
        assert text.strip()
        # very loose: "red" should appear, model sometimes adds punctuation
        assert any(w in text.lower() for w in ("red", "crimson", "scarlet")), text
    finally:
        await provider.aclose()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(test_ollama_detect_red_image())
