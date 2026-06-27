"""Runtime configuration loading.

Reads `config.json` from the project root (or path given by `VISION_OCR_CONFIG`
env var). Validates structure with pydantic. Fail fast on bad config so the
server never boots into a half-initialized state.

Environment variables and `.env` (project root) are honored via pydantic-
settings' BaseSettings: any field populated by env at process start takes
precedence over the same key in `config.json`. The primary use case is
secret material — `OPENROUTER_API_KEY` can live in `.env` or be exported
in the shell and override whatever (typically `null`) is in `config.json`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    TODO: when introducing per-model pricing (e.g. qwen2.5-vl-72b is
    priced differently from qwen3-vl-32b on OpenRouter), this flat
    per-provider rate needs to become a function `(model) -> rate`.
    For now, one rate per provider is enough — see README
    'Configuration' for the current pricing lookup flow.

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


class Settings(BaseSettings):
    """Top-level config.

    Inherits `BaseSettings` (instead of plain `BaseModel`) so a project-
    root `.env` file is loaded on instantiation. Priority order:
      1. Process env vars (e.g. `OPENROUTER_API_KEY`)
      2. `.env` file values
      3. `config.json` values (via `Settings.model_validate(...)` in
         `load_settings`)
      4. Field defaults

    Note: only top-level scalar fields receive env-var mapping
    automatically. Nested fields like `providers.openrouter.api_key`
    are populated from config.json; the `OPENROUTER_API_KEY` field
    below is the top-level counterpart that pydantic-settings maps
    from env / `.env`. The provider registry's `from_settings`
    copies this field into `providers.openrouter.api_key` when the
    provider config didn't already supply one.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
    server: ServerConfig = Field(default_factory=ServerConfig)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    # Top-level so pydantic-settings auto-maps from `OPENROUTER_API_KEY`
    # in process env / `.env` (priority order per BaseSettings). The
    # provider registry copies this into `providers.openrouter.api_key`
    # when that nested field is None.
    openrouter_api_key: str | None = Field(
        default=None,
        alias="OPENROUTER_API_KEY",
        description="OpenRouter API key. Auto-loaded from env or .env.",
    )

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
    """Load and validate config.json. Raises FileNotFoundError or ValueError.

    Note: `.env` (if present at project root) is read by BaseSettings at
    instantiation, so callers get any env-var overrides automatically.
    """
    target = path or find_config_path()
    if not target.exists():
        raise FileNotFoundError(
            f"config not found at {target}; copy config.example.json to config.json"
        )
    raw = json.loads(target.read_text(encoding="utf-8"))
    return Settings.model_validate(raw)