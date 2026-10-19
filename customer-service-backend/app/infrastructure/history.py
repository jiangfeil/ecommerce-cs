"""把对话历史渲染成提示词里能读的纯文本。"""
from __future__ import annotations

from app.domain.messages import MessageType, UserMessage
from app.domain.state import Turn


class HistoryBuilder:
    @staticmethod
    def render_user_message(message: UserMessage) -> str:
        if message.type is MessageType.OBJECT and message.object is not None:
            obj = message.object
            label = f"{obj.title}（{obj.id}）" if obj.title else obj.id
            return f"[用户点击了{obj.type}对象] {label}"
        return (message.text or "").strip()

    @classmethod
    def build(cls, turns: list[Turn], limit: int | None = None) -> str:
        selected = turns[-limit:] if limit else list(turns)
        lines: list[str] = []
        for turn in selected:
            user_text = cls.render_user_message(turn.input_message)
            if user_text:
                lines.append(f"用户：{user_text}")
            for bot_message in turn.assistant_messages:
                text = (bot_message.text or "").strip()
                if text:
                    lines.append(f"助手：{text}")
        return "\n".join(lines)
