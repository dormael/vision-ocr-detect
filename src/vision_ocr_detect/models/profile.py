"""Profile schemas.

A profile is a reusable prompt+model bundle. The `name` is the lookup key
(URL-safe). `provider` must reference a configured provider in `config.json`
(validated at the API layer).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


# URL-safe characters only. Keep it short (path segment).
_NAME_PATTERN = r"^[a-zA-Z0-9_\-.]{1,64}$"

# Tags: lowercase alphanumeric + dashes, separated by single dashes/underscores
# or standalone. Reject whitespace, punctuation that breaks URL/query safety.
_TAG_PATTERN = r"^[a-z0-9][a-z0-9_\-]{0,31}$"
_TAG_RE = re.compile(_TAG_PATTERN)


def _validate_tags(v: list[str]) -> list[str]:
    """Normalize (lowercase/strip/dedupe) and validate tag list.

    Empty / whitespace-only entries are dropped. Each surviving entry must
    match _TAG_PATTERN (1-32 chars, lowercase alphanumeric + dashes/underscores,
    must start with a letter or digit).
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in v:
        t = raw.strip().lower()
        if not t or t in seen:
            continue
        if not _TAG_RE.match(t):
            raise ValueError(
                f"tag {t!r} does not match {_TAG_PATTERN!r} "
                f"(lowercase alphanumeric, dashes, underscores; "
                f"1-32 chars; must start with letter/digit)"
            )
        seen.add(t)
        out.append(t)
    return out


class ProfileBase(BaseModel):
    """Shared fields between create/update."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "ocr-default",
                    "provider": "local-ollama",
                    "model": "glm-ocr:latest",
                    "prompt": "Extract all text from this image.",
                    "description": "Default OCR profile for general text.",
                    "tags": ["ocr", "default"],
                }
            ]
        },
    )

    name: str = Field(pattern=_NAME_PATTERN)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    description: str | None = Field(default=None, max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, v: list[str]) -> list[str]:
        return _validate_tags(v)


class ProfileCreate(ProfileBase):
    """Body for `POST /api/profiles`."""


class ProfileUpdate(BaseModel):
    """Body for `PUT /api/profiles/{name}`. All fields optional, name immutable.

    To clear tags, send an empty list. To clear description, send null.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"model": "qwen2.5vl:7b"},
                {"temperature": 0.0, "seed": 42, "description": None, "tags": []},
            ]
        },
    )

    provider: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, max_length=500)
    tags: list[str] | None = Field(default=None, max_length=20)

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return _validate_tags(v)


class Profile(ProfileBase):
    """Stored profile (includes timestamps)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "name": "ocr-default",
                    "provider": "local-ollama",
                    "model": "glm-ocr:latest",
                    "prompt": "Extract all text from this image.",
                    "description": "Default OCR profile for general text.",
                    "tags": ["ocr", "default"],
                    "created_at": "2026-06-01T12:00:00Z",
                    "updated_at": "2026-06-25T09:00:00Z",
                }
            ]
        },
    )

    created_at: datetime
    updated_at: datetime


def utcnow() -> datetime:
    """Timezone-aware UTC now (pydantic serializes ISO 8601)."""
    return datetime.now(timezone.utc)
