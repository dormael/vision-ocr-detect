"""Models endpoint response schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from vision_ocr_detect.providers.base import ModelInfo


class ProviderModels(BaseModel):
    """Models exposed by a single provider."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "models": [
                        {
                            "name": "qwen2.5vl:7b",
                            "family": "qwen25vl",
                            "parameter_size": "7B",
                            "quantization_level": "Q4_0",
                            "context_length": 8192,
                            "vision_capable": True,
                            "source": "capabilities",
                        }
                    ]
                }
            ]
        },
    )

    models: list[ModelInfo]


class ModelsResponse(BaseModel):
    """All models grouped by provider name."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "providers": {
                        "local-ollama": {
                            "models": [
                                {
                                    "name": "qwen2.5vl:7b",
                                    "vision_capable": True,
                                    "source": "capabilities",
                                }
                            ]
                        }
                    }
                }
            ]
        },
    )

    providers: dict[str, ProviderModels] = Field(default_factory=dict)