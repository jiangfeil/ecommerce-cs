"""服务层：把"一次请求"编排成"读状态 → 跑引擎 → 存状态"。

引擎本身不碰数据库，仓储不碰业务，两者的接缝就在这里。
"""
from __future__ import annotations

import uuid

from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    HistoryResponse,
    HistoryTurnSchema,
    MessageSchema,
    ObjectSchema,
)
from app.domain.messages import MessageType, ObjectPayload, UserMessage
from app.engine.dialogue_engine import DialogueEngine
from app.repositories.dialogue_state_repository import DialogueStateRepository


class DialogueService:
    def __init__(
        self,
        dialogue_state_repository: DialogueStateRepository,
        dialogue_engine: DialogueEngine,
    ) -> None:
        self.dialogue_state_repository = dialogue_state_repository
        self.dialogue_engine = dialogue_engine

    async def chat(self, request: ChatRequest) -> ChatResponse:
        state = await self.dialogue_state_repository.get_or_create(request.sender_id)

        message_id = request.message_id or f"msg_{uuid.uuid4().hex[:12]}"
        message_type = MessageType.OBJECT if request.object is not None else MessageType.TEXT
        user_message = UserMessage(
            sender_id=request.sender_id,
            message_id=message_id,
            type=message_type,
            text=(request.text or "").strip(),
            object=ObjectPayload.from_dict(
                request.object.model_dump() if request.object else None
            ),
        )

        result = await self.dialogue_engine.process_message(state, user_message)
        await self.dialogue_state_repository.save(state)

        return ChatResponse(
            sender_id=result.sender_id,
            message_id=result.message_id,
            messages=[
                MessageSchema(
                    text=message.text,
                    object=ObjectSchema(**message.object.to_dict()) if message.object else None,
                )
                for message in result.messages
            ],
        )

    async def history(self, sender_id: str) -> HistoryResponse:
        state = await self.dialogue_state_repository.get(sender_id)
        if state is None:
            return HistoryResponse(sender_id=sender_id, messages=[])

        messages: list[HistoryTurnSchema] = []
        for session in state.sessions:
            for turn in session.turns:
                input_message = turn.input_message
                messages.append(
                    HistoryTurnSchema(
                        role="user",
                        text=input_message.text or "",
                        object=(
                            ObjectSchema(**input_message.object.to_dict())
                            if input_message.object
                            else None
                        ),
                    )
                )
                for bot_message in turn.assistant_messages:
                    if not (bot_message.text or "").strip():
                        continue
                    messages.append(
                        HistoryTurnSchema(
                            role="bot",
                            text=bot_message.text,
                            object=(
                                ObjectSchema(**bot_message.object.to_dict())
                                if bot_message.object
                                else None
                            ),
                        )
                    )
        return HistoryResponse(sender_id=sender_id, messages=messages)
