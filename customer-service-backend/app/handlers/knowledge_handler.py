"""KnowledgeHandler：知识问答的总入口。

流程很短，但每一步都不能省：
  意图 -> 合并所需数据源 -> 逐个检索 -> 汇总素材 -> 交给 Responder 生成回复

它不知道模型、不知道 HTTP，只负责"要查什么、查到了什么"。
"""
from __future__ import annotations

from app.config import settings
from app.domain.messages import BotMessage
from app.domain.state import DialogueState
from app.knowledge.intents import KnowledgeIntent
from app.knowledge.providers import KnowledgeChunk
from app.knowledge.registry import KnowledgeProviderRegistry
from app.knowledge.responder import KnowledgeResponder


class KnowledgeHandler:
    def __init__(
        self,
        knowledge_intents: dict[str, KnowledgeIntent],
        responder: KnowledgeResponder,
        registry: KnowledgeProviderRegistry,
    ) -> None:
        self.knowledge_intents = knowledge_intents
        self.responder = responder
        self.registry = registry

    async def handle(
        self,
        state: DialogueState,
        intents: list[str],
    ) -> list[BotMessage]:
        pending_turn = state.pending_turn
        user_message = (pending_turn.input_message.text or "").strip() if pending_turn else ""
        recent_turns = state.recent_turns(settings.history_turns)

        chunks: list[KnowledgeChunk] = []
        for provider_id in self._provider_ids_for_intents(intents):
            provider = self.registry.get(provider_id)
            if provider is None:
                continue
            chunks.extend(await provider.retrieve(state))

        return await self.responder.respond(user_message, recent_turns, chunks)

    def _provider_ids_for_intents(self, intents: list[str]) -> list[str]:
        provider_ids: list[str] = []
        for intent in intents:
            intent_meta = self.knowledge_intents.get(intent)
            if intent_meta is None:
                continue
            for provider_id in intent_meta.provider_ids:
                if provider_id not in provider_ids:
                    provider_ids.append(provider_id)
        return provider_ids
