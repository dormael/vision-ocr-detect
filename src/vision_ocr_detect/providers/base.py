"""Provider interface.

A `VisionProvider` is anything that can run a vision/OCR model on an image
and return extracted text. The detect endpoint looks up the right provider
by name (resolved from the profile) and calls `detect()` — it knows nothing
about HTTP, base64, or specific model APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class ProviderResult:
    """Outcome of one provider.detect() call.

    `text` is the raw assistant output (no server-side mutation; clients
    see this verbatim). The metadata fields are best-effort: providers
    that don't expose usage stats leave them None.

    `seed_used` is the seed the provider actually used for this call.
    When the caller passed a seed, that value; when the provider picked
    its own (e.g. ollama with no seed given), whatever the provider
    echoes back; None when neither is available.
    """

    text: str
    tokens_in: int | None = None
    tokens_out: int | None = None
    seed_used: int | None = None


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
    ) -> ProviderResult:
        """Run the model on `image` and return the result.

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
