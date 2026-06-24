"""Runtime configuration loading.

Reads `config.json` from the project root (or path given by `VISION_OCR_CONFIG`
env var). Validates structure with pydantic. Fail fast on bad config so the
server never boots into a half-initialized state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ServerConfig(BaseModel):
    """HTTP server settings."""

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    max_concurrent_requests: int = Field(default=4, ge=1, le=128)


class ProviderConfig(BaseModel):
    """Vision provider connection.

    `type` drives which concrete provider class is instantiated (`ollama`
    for local ollama, `openrouter` for OpenRouter's OpenAI-compatible
    gateway).

    `cost_per_1k_input_tokens` / `cost_per_1k_output_tokens` (USD): optional.
    Used to compute `cost_usd` in the response. Local providers (ollama)
    leave them at 0.0; cloud providers (openrouter) should set them
    from the provider's published pricing — `0.0` is allowed (free
    tier) but `cost_usd` will report `0.0` for those calls.

    For openrouter, `api_key` is required; set it via the
    `OPENROUTER_API_KEY` environment variable (or hardcode in
    `config.json` for self-hosted deployments — not recommended).
    """

    type: Literal["ollama", "openrouter"]
    base_url: str
    api_key: str | None = None
    timeout_seconds: float = Field(default=300.0, gt=0)
    cost_per_1k_input_tokens: float = Field(default=0.0, ge=0)
    cost_per_1k_output_tokens: float = Field(default=0.0, ge=0)


class Settings(BaseModel):
    """Top-level config."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)

    @field_validator("providers")
    @classmethod
    def _no_empty_name(cls, v: dict[str, ProviderConfig]) -> dict[str, ProviderConfig]:
        if not v:
            raise ValueError("at least one provider must be configured")
        for name in v:
            if not name.strip():
                raise ValueError("provider names must be non-empty")
        return v


def find_config_path() -> Path:
    """Locate config.json.

    Order:
    1. `VISION_OCR_CONFIG` env var (absolute or relative)
    2. `./config.json` (cwd)
    """
    import os

    env = os.environ.get("VISION_OCR_CONFIG")
    if env:
        return Path(env).expanduser().resolve()
    return Path("config.json").resolve()


def load_settings(path: Path | None = None) -> Settings:
    """Load and validate config.json. Raises FileNotFoundError or ValueError."""
    target = path or find_config_path()
    if not target.exists():
        raise FileNotFoundError(
            f"config not found at {target}; copy config.example.json to config.json"
        )
    raw = json.loads(target.read_text(encoding="utf-8"))
    return Settings.model_validate(raw)
