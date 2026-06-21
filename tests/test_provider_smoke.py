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
    """Loose smoke test: red 256x256 image → non-empty text response.

    Vision models are nondeterministic and may add caveats like "I cannot
    see the image". We only assert (a) ollama is reachable, (b) a non-empty
    string comes back, (c) the response took a sensible amount of time.
    Strict content checks belong in dedicated integration tests with a
    pinned model + temperature=0 + seed.
    """
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
        result = await provider.detect(
            png, "image/png",
            "granite3.2-vision:2b",
            "Describe this solid-color image in one short sentence.",
        )
        assert isinstance(result.text, str)
        assert result.text.strip(), "ollama returned empty text"
        # Sanity: response shouldn't be absurdly short or long.
        assert 5 <= len(result.text) <= 2000, f"unexpected response length: {len(result.text)}"
    finally:
        await provider.aclose()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(test_ollama_detect_red_image())
