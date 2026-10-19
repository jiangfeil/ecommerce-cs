"""KnowledgeResponder：把检索到的素材交给模型，组织成人话。

关键设计：**先检索、后生成**。
模型只负责表达，不负责回忆事实，这样能显著降低编造。
素材为空时，明确要求模型承认"没查到"，而不是硬编一个答案。
"""
from __future__ import annotations

from app.domain.messages import BotMessage
from app.domain.state import Turn
from app.infrastructure.history import HistoryBuilder
from app.infrastructure.llm import LLMError, get_llm
from app.infrastructure.prompts import load_prompt, render
from app.knowledge.providers import KnowledgeChunk


class KnowledgeResponder:
    async def respond(
        self,
        user_message: str,
        recent_turns: list[Turn],
        chunks: list[KnowledgeChunk],
    ) -> list[BotMessage]:
        knowledge_content = "\n\n".join(chunk.content for chunk in chunks).strip()
        history = HistoryBuilder.build(recent_turns)

        llm = get_llm()
        if llm.available:
            prompt = render(
                load_prompt("knowledge_respond"),
                {
                    "knowledge_content": knowledge_content,
                    "history": history,
                    "user_message": user_message,
                },
            )
            try:
                answer = (await llm.complete(prompt)).strip()
                if answer:
                    return [BotMessage(text=answer)]
            except LLMError:
                pass

        # 模型不可用时的降级：直接把检索到的最相关原文给用户
        if chunks:
            return [BotMessage(text=chunks[0].content)]
        return [
            BotMessage(
                text="这个问题我暂时没有查到明确的说明。你可以换个说法，或者告诉我具体的商品或订单，我再帮你看看。"
            )
        ]
