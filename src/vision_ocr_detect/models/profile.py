"""Profile schemas.

A profile is a reusable prompt+model bundle. The `name` is the lookup key
(URL-safe). `provider` must reference a configured provider in `config.json`
(validated at the API layer).
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


# URL-safe characters only. Keep it short (path segment).
_NAME_PATTERN = r"^[a-zA-Z0-9_\-.]{1,64}$"


class ProfileBase(BaseModel):
    """Shared fields between create/update."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=_NAME_PATTERN)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt: str = Field(min_length=1)


class ProfileCreate(ProfileBase):
    """Body for `POST /api/profiles`."""


class ProfileUpdate(BaseModel):
    """Body for `PUT /api/profiles/{name}`. All fields optional, name immutable."""

    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    prompt: str | None = Field(default=None, min_length=1)


class Profile(ProfileBase):
    """Stored profile (includes timestamps)."""

    created_at: datetime
    updated_at: datetime


def utcnow() -> datetime:
    """Timezone-aware UTC now (pydantic serializes ISO 8601)."""
    return datetime.now(timezone.utc)
