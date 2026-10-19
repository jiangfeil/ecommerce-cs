"""对话状态仓储：负责 state 与数据库之间的来回转换。

只做一件事：按 sender_id 整存整取。
DialogueState 内部结构复杂但整体读写，不需要拆表，也不该让上层感知 SQL。
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DialogueStateRecord
from app.domain.state import DialogueState


class DialogueStateRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, sender_id: str) -> DialogueState | None:
        result = await self.db.execute(
            select(DialogueStateRecord).where(DialogueStateRecord.sender_id == sender_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        try:
            payload = json.loads(record.state_json)
        except json.JSONDecodeError:
            return None
        payload["sender_id"] = sender_id
        return DialogueState.from_dict(payload)

    async def get_or_create(self, sender_id: str) -> DialogueState:
        state = await self.get(sender_id)
        if state is None:
            state = DialogueState(sender_id=sender_id)
        return state

    async def save(self, state: DialogueState) -> None:
        payload = json.dumps(state.to_dict(), ensure_ascii=False)
        result = await self.db.execute(
            select(DialogueStateRecord).where(
                DialogueStateRecord.sender_id == state.sender_id
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            self.db.add(
                DialogueStateRecord(
                    sender_id=state.sender_id,
                    state_json=payload,
                    updated_at=datetime.utcnow(),
                )
            )
        else:
            record.state_json = payload
            record.updated_at = datetime.utcnow()
        await self.db.commit()
