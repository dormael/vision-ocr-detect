"""Models endpoint response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from vision_ocr_detect.providers.base import ModelInfo


class ProviderModels(BaseModel):
    """Models exposed by a single provider."""

    model_config = ConfigDict(extra="forbid")

    models: list[ModelInfo]


class ModelsResponse(BaseModel):
    """All models grouped by provider name."""

    model_config = ConfigDict(extra="forbid")

    providers: dict[str, ProviderModels] = Field(default_factory=dict)