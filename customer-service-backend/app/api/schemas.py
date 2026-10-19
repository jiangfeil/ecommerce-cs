"""API 层的数据契约（请求 / 响应）。

字段名与《客服后端接口文档》保持一致，前端不用改。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ObjectSchema(BaseModel):
    type: str
    id: str
    title: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    sender_id: str
    text: str | None = None
    object: ObjectSchema | None = None
    message_id: str | None = None


class MessageSchema(BaseModel):
    text: str = ""
    object: ObjectSchema | None = None


class ChatResponse(BaseModel):
    sender_id: str
    message_id: str
    messages: list[MessageSchema] = Field(default_factory=list)


class HistoryTurnSchema(BaseModel):
    role: str
    text: str = ""
    object: ObjectSchema | None = None


class HistoryResponse(BaseModel):
    sender_id: str
    messages: list[HistoryTurnSchema] = Field(default_factory=list)
