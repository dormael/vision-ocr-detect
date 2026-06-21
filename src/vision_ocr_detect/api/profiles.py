"""`/api/profiles` CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from vision_ocr_detect.deps import get_profile_store, get_provider_names
from vision_ocr_detect.models.profile import (
    Profile,
    ProfileCreate,
    ProfileUpdate,
    utcnow,
)
from vision_ocr_detect.services.profile_store import (
    ProfileAlreadyExists,
    ProfileNotFound,
    ProfileStore,
)


router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _validate_provider(provider: str, allowed: set[str]) -> None:
    if provider not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown provider '{provider}'; configured: {sorted(allowed)}",
        )


@router.get("", response_model=list[Profile])
def list_profiles(
    tag: str | None = Query(
        default=None,
        description="Filter by tag (OR match). Lowercased before comparison.",
    ),
    store: ProfileStore = Depends(get_profile_store),
) -> list[Profile]:
    return store.list(tag=tag)


@router.get("/{name}", response_model=Profile)
def get_profile(
    name: str,
    store: ProfileStore = Depends(get_profile_store),
) -> Profile:
    try:
        return store.get(name)
    except ProfileNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"profile '{name}' not found"
        )


@router.post("", response_model=Profile, status_code=status.HTTP_201_CREATED)
def create_profile(
    body: ProfileCreate,
    store: ProfileStore = Depends(get_profile_store),
    allowed: set[str] = Depends(get_provider_names),
) -> Profile:
    _validate_provider(body.provider, allowed)
    now = utcnow()
    profile = Profile(
        name=body.name,
        provider=body.provider,
        model=body.model,
        prompt=body.prompt,
        description=body.description,
        tags=body.tags,
        created_at=now,
        updated_at=now,
    )
    try:
        return store.create(profile)
    except ProfileAlreadyExists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"profile '{body.name}' already exists",
        )


@router.put("/{name}", response_model=Profile)
def update_profile(
    name: str,
    body: ProfileUpdate,
    store: ProfileStore = Depends(get_profile_store),
    allowed: set[str] = Depends(get_provider_names),
) -> Profile:
    if "provider" in body.model_fields_set and body.provider is not None:
        _validate_provider(body.provider, allowed)
    # PATCH-style semantics: only update fields the client explicitly sent.
    # Omitting a field leaves it unchanged. Sending null/[] clears it.
    provided = body.model_dump(exclude_unset=True)
    try:
        return store.update(name, **provided)
    except ProfileNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"profile '{name}' not found"
        )


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(
    name: str,
    store: ProfileStore = Depends(get_profile_store),
) -> None:
    try:
        store.delete(name)
    except ProfileNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"profile '{name}' not found"
        )
