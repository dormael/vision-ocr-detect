"""Provider interface.

A `VisionProvider` is anything that can run a vision/OCR model on an image
and return extracted text. The detect endpoint looks up the right provider
by name (resolved from the profile) and calls `detect()` — it knows nothing
about HTTP, base64, or specific model APIs.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class VisionProvider(Protocol):
    """Async vision/OCR interface.

    Implementations must:
      - be safe to call concurrently (the detect endpoint may invoke the
        same provider from many coroutines; serialization, if needed, is
        the implementation's concern).
      - raise on transport / model errors. The API layer maps these to 502.
    """

    name: str

    async def detect(
        self,
        image: bytes,
        mime_type: str,
        model: str,
        prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Run the model on `image` and return the assistant text."""
        ...


class ProviderNotFound(Exception):
    """Raised by the registry when a name is unknown."""
