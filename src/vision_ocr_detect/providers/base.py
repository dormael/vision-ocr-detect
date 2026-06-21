"""Provider interface.

A `VisionProvider` is anything that can run a vision/OCR model on an image
and return extracted text. The detect endpoint looks up the right provider
by name (resolved from the profile) and calls `detect()` — it knows nothing
about HTTP, base64, or specific model APIs.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


CapabilitySource = Literal["capabilities", "heuristic", "unknown"]


class ModelInfo(BaseModel):
    """Metadata about a model available through a provider.

    `vision_capable` is the key field for clients — they can filter to
    only the models that can accept image input. `source` records how we
    arrived at that verdict so debugging is straightforward when a model
    is mis-classified.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    family: str | None = None
    parameter_size: str | None = None
    quantization_level: str | None = None
    context_length: int | None = None
    vision_capable: bool
    source: CapabilitySource


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
        seed: int | None = None,
        response_format: str | dict | None = None,
    ) -> str:
        """Run the model on `image` and return the assistant text.

        `response_format`: provider-defined hint for structured output. The
        default `None` means "free-form text". Implementations accept
        either a string hint (`"json"`) or a structured spec dict (e.g.
        OpenAI-style `{type: "json_schema", json_schema: {...}}`).
        """
        ...

    async def list_models(self) -> list[ModelInfo]:
        """List models available through this provider with metadata.

        Implementations should populate `vision_capable` from the provider's
        authoritative capability signal when available (e.g. ollama's
        `/api/tags` `capabilities` field). When not available, fall back
        to a name-based heuristic and record the `source` accordingly so
        callers can see which path was taken.

        Raises on transport errors (the API layer maps these to 502).
        """
        ...


class ProviderNotFound(Exception):
    """Raised by the registry when a name is unknown."""
