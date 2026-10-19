"""ClarifyResponder：把"为什么没听懂"翻译成一句用户能回应的追问。

分两步：
  1. 根据 reason 生成一句**信息明确**的基础话术（保证追问有指向性）
  2. 交给模型润色（可选，模型挂了就用基础话术）

先有确定性的兜底，再叠一层自然语言润色，是这套系统里反复出现的模式。
"""
from __future__ import annotations

import json

from app.config import settings
from app.domain.messages import BotMessage
from app.domain.state import DialogueState
from app.infrastructure.history import HistoryBuilder
from app.infrastructure.llm import LLMError, get_llm
from app.infrastructure.prompts import load_prompt, render
from app.planning.validator import ClarifyReason


class ClarifyResponder:
    async def respond(
        self,
        state: DialogueState,
        reason: ClarifyReason,
    ) -> list[BotMessage]:
        clarify_message = self.build_clarify_message(reason=reason, state=state)

        pending = state.pending_turn
        user_message = (
            HistoryBuilder.render_user_message(pending.input_message) if pending else ""
        )
        history = HistoryBuilder.build(state.recent_turns(settings.history_turns))
        focused_object = (
            json.dumps(state.focused_object.to_dict(), ensure_ascii=False)
            if state.focused_object
            else ""
        )

        llm = get_llm()
        if not llm.available:
            return [BotMessage(text=clarify_message)]

        prompt = render(
            load_prompt("clarify_respond"),
            {
                "reason": reason.value,
                "clarify_message": clarify_message,
                "focused_object": focused_object,
                "history": history,
                "user_message": user_message,
            },
        )
        try:
            rewritten = (await llm.complete(prompt)).strip()
        except LLMError:
            rewritten = ""
        return [BotMessage(text=rewritten or clarify_message)]

    @staticmethod
    def build_clarify_message(reason: ClarifyReason, state: DialogueState) -> str:
        if reason is ClarifyReason.MULTIPLE_TRACKS:
            return "你这次同时提到了多个方向。我们先处理一个，你想先办业务还是先咨询信息呢？"

        if reason is ClarifyReason.MISSING_FOCUSED_OBJECT:
            return "请先发送你想咨询的商品或订单，我再继续帮你看。"

        if reason is ClarifyReason.MISSING_KNOWLEDGE_INTENT:
            return "你是想了解商品信息、订单信息，还是售后配送规则呢？"

        if reason is ClarifyReason.MISSING_TRACK:
            return "你是想先处理业务问题，还是先咨询信息呢？比如查订单、查物流、申请退款都可以。"

        if reason is ClarifyReason.MISSING_TASK_COMMANDS:
            return "你这次是想办理什么业务呢？比如查订单、查物流，或者申请退款。"

        if reason is ClarifyReason.OBJECT_REQUIRES_INTENT:
            focused_object = state.focused_object
            if focused_object is not None and focused_object.type == "order":
                return "我已经收到这个订单了。你想查订单状态、查物流，还是申请退款呢？"
            if focused_object is not None and focused_object.type == "product":
                return "我已经收到这个商品了。你想了解它的商品信息、发货情况，还是售后相关问题呢？"

        return "我还需要再确认一下你的意思，你可以换个更具体的说法告诉我。"
