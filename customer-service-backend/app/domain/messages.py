"""对话领域模型：消息、业务对象、聚焦对象。

这里刻意只放"数据长什么样"，不放任何业务规则。
规则放在 engine / handlers / task 层，保证领域模型可以被自由序列化。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class MessageType(str, Enum):
    """用户消息的两种形态。"""

    TEXT = "text"      # 自然语言，需要大模型理解
    OBJECT = "object"  # 结构化对象，来自前端点击（订单卡片 / 商品卡片）

    @classmethod
    def parse(cls, value: Any) -> MessageType:
        if isinstance(value, cls):
            return value
        if value is None:
            return cls.TEXT
        text = str(value).strip().lower()
        return cls.OBJECT if text == "object" else cls.TEXT


@dataclass(slots=True)
class ObjectPayload:
    """前端发来的结构化对象。"""

    type: str
    id: str
    title: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ObjectPayload | None:
        if not data:
            return None
        return cls(
            type=str(data.get("type") or "").strip().lower(),
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            attributes=dict(data.get("attributes") or {}),
        )


@dataclass(slots=True)
class FocusedObject:
    """当前聚焦对象。

    用户点一下订单卡片，系统就记下"接下来的操作都和这张订单相关"。
    之后流程里的 order_number 槽位可以自动填充，不必再问一遍。
    """

    type: str
    id: str
    title: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> FocusedObject | None:
        if not data:
            return None
        return cls(
            type=str(data.get("type") or "").strip().lower(),
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            attributes=dict(data.get("attributes") or {}),
        )


@dataclass(slots=True)
class UserMessage:
    """一轮对话里的用户输入。"""

    sender_id: str
    message_id: str
    type: MessageType = MessageType.TEXT
    text: str = ""
    object: ObjectPayload | None = None

    @property
    def user_message(self) -> str:
        """兼容旧叫法：把文本内容直接当作用户消息。"""
        return self.text

    def to_dict(self) -> dict[str, Any]:
        return {
            "sender_id": self.sender_id,
            "message_id": self.message_id,
            "type": self.type.value,
            "text": self.text,
            "object": self.object.to_dict() if self.object else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserMessage:
        return cls(
            sender_id=str(data.get("sender_id") or ""),
            message_id=str(data.get("message_id") or ""),
            type=MessageType.parse(data.get("type")),
            text=str(data.get("text") or ""),
            object=ObjectPayload.from_dict(data.get("object")),
        )


@dataclass(slots=True)
class BotMessage:
    """机器人输出的一条消息。一轮里可以有多条。"""

    text: str
    object: ObjectPayload | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "object": self.object.to_dict() if self.object else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BotMessage:
        return cls(
            text=str(data.get("text") or ""),
            object=ObjectPayload.from_dict(data.get("object")),
        )
