"""闲聊轨道。

它和知识问答的区别：闲聊不检索任何资料，纯粹是社交性回复。
和业务任务的区别：闲聊不推进任何流程，也不改任务状态。
"""
from __future__ import annotations

from app.config import settings
from app.domain.messages import BotMessage, UserMessage
from app.domain.state import DialogueState, Turn
from app.infrastructure.history import HistoryBuilder
from app.infrastructure.llm import LLMError, get_llm
from app.infrastructure.prompts import load_prompt, render


class ChitchatResponder:
    async def respond(
        self,
        user_message: UserMessage,
        recent_turns: list[Turn],
    ) -> list[BotMessage]:
        text = HistoryBuilder.render_user_message(user_message)
        history = HistoryBuilder.build(recent_turns)

        llm = get_llm()
        if not llm.available:
            return [BotMessage(text="你好，我是 Atguigu 电商助手。查订单、查物流、退款或者商品咨询，都可以直接跟我说。")]

        prompt = render(
            load_prompt("chitchat_respond"),
            {"user_message": text, "history": history},
        )
        try:
            answer = (await llm.complete(prompt)).strip()
        except LLMError:
            answer = ""
        if not answer:
            answer = "你好，我是 Atguigu 电商助手。有什么可以帮你的？"
        return [BotMessage(text=answer)]


class ChitchatHandler:
    def __init__(self, responder: ChitchatResponder) -> None:
        self.responder = responder

    async def handle(self, state: DialogueState) -> list[BotMessage]:
        pending_turn = state.pending_turn
        if pending_turn is None:
            return []
        return await self.responder.respond(
            user_message=pending_turn.input_message,
            recent_turns=state.recent_turns(settings.history_turns),
        )
