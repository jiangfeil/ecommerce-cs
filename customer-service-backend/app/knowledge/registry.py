"""Provider 注册表：provider_id -> 实例。"""
from __future__ import annotations

from app.knowledge.providers import KnowledgeProvider


class KnowledgeProviderRegistry:
    def __init__(self, providers: list[KnowledgeProvider] | None = None) -> None:
        self._providers_by_id: dict[str, KnowledgeProvider] = {
            provider.provider_id: provider for provider in (providers or [])
        }

    def register(self, provider: KnowledgeProvider) -> None:
        self._providers_by_id[provider.provider_id] = provider

    def get(self, provider_id: str) -> KnowledgeProvider | None:
        return self._providers_by_id.get(provider_id)

    @property
    def provider_ids(self) -> list[str]:
        return sorted(self._providers_by_id)
