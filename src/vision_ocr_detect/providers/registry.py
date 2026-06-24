"""Provider registry: maps profile `provider` strings to live instances.

Built once at startup from `Settings.providers`. Adding a new provider type
means adding a branch to `_build()`.
"""

from __future__ import annotations

from typing import Callable

from vision_ocr_detect.config import ProviderConfig, Settings
from vision_ocr_detect.providers.base import (
    ModelInfo,
    ProviderNotFound,
    VisionProvider,
)
from vision_ocr_detect.providers.ollama import OllamaProvider
from vision_ocr_detect.providers.openrouter import OpenRouterProvider


# Dispatch table for new provider types. Each factory takes the configured
# name + ProviderConfig and returns a VisionProvider.
_BUILDERS: dict[str, Callable[[str, ProviderConfig], VisionProvider]] = {
    "ollama": OllamaProvider,
    "openrouter": OpenRouterProvider,
}


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, VisionProvider] = {}

    def register(self, name: str, provider: VisionProvider) -> None:
        self._providers[name] = provider

    def get(self, name: str) -> VisionProvider:
        try:
            return self._providers[name]
        except KeyError as e:
            raise ProviderNotFound(name) from e

    def names(self) -> list[str]:
        return list(self._providers.keys())

    async def aclose(self) -> None:
        for p in self._providers.values():
            close = getattr(p, "aclose", None)
            if close is not None:
                await close()

    async def list_models_all(self) -> dict[str, list[ModelInfo]]:
        """Return {provider_name: [ModelInfo]} across all registered providers.

        Provider errors are caught and reported as an empty list with a
        single synthetic model entry carrying the error in `family` —
        callers see "no models" rather than a 5xx, and we don't take down
        a multi-provider response because one provider is down.
        """
        import asyncio

        async def _fetch(name: str, provider: VisionProvider) -> tuple[str, list[ModelInfo]]:
            try:
                return name, await provider.list_models()
            except Exception as e:
                return name, [
                    ModelInfo(
                        name=f"<{name} unavailable: {e!s}>",
                        vision_capable=False,
                        source="unknown",
                    )
                ]

        results = await asyncio.gather(
            *(_fetch(n, p) for n, p in self._providers.items())
        )
        return dict(results)

    @classmethod
    def from_settings(cls, settings: Settings) -> "ProviderRegistry":
        registry = cls()
        for name, pconfig in settings.providers.items():
            try:
                builder = _BUILDERS[pconfig.type]
            except KeyError as e:
                raise ValueError(
                    f"unsupported provider type '{pconfig.type}' for '{name}'"
                ) from e
            registry.register(name, builder(name, pconfig))
        return registry
