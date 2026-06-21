"""`/api/models` and `/api/providers/{name}/models` endpoints.

Lists models available through each registered provider, with the
`vision_capable` flag the detect endpoint relies on. Vision filtering is
done at the API layer (not in providers) so the same response shape works
for any future OpenAI-compatible / vLLM provider.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from vision_ocr_detect.deps import get_provider_registry
from vision_ocr_detect.models.models import ModelsResponse, ProviderModels
from vision_ocr_detect.providers.registry import ProviderRegistry


router = APIRouter(prefix="/api", tags=["models"])


async def _gather_models(
    registry: ProviderRegistry, vision_only: bool
) -> dict[str, ProviderModels]:
    """Fetch from all providers in parallel and optionally filter."""
    raw = await registry.list_models_all()
    out: dict[str, ProviderModels] = {}
    for provider_name, infos in raw.items():
        if vision_only:
            infos = [m for m in infos if m.vision_capable]
        # Stable sort by name so the response is deterministic.
        infos = sorted(infos, key=lambda m: m.name)
        out[provider_name] = ProviderModels(models=infos)
    return out


@router.get("/models", response_model=ModelsResponse)
async def list_models(
    vision_only: bool = Query(
        default=False,
        description="If true, return only models whose `vision_capable` flag is true.",
    ),
    registry: ProviderRegistry = Depends(get_provider_registry),
) -> ModelsResponse:
    by_provider = await _gather_models(registry, vision_only)
    return ModelsResponse(providers=by_provider)


@router.get("/providers/{name}/models", response_model=ProviderModels)
async def list_provider_models(
    name: str,
    vision_only: bool = Query(default=False),
    registry: ProviderRegistry = Depends(get_provider_registry),
) -> ProviderModels:
    try:
        provider = registry.get(name)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown provider '{name}'; configured: {sorted(registry.names())}",
        )
    try:
        infos = await provider.list_models()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"provider '{name}' failed to list models: {e!s}",
        )
    if vision_only:
        infos = [m for m in infos if m.vision_capable]
    infos = sorted(infos, key=lambda m: m.name)
    return ProviderModels(models=infos)