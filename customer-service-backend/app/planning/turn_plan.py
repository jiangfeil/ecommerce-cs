"""TurnPlan：大模型对本轮对话给出的"处理决策单"。

三个轨道 task / knowledge / chitchat，同一轮允许同时命中（用户可能一句话两个意图），
但执行引擎一次只能走一条，所以多轨道会被判定为"需要澄清先做哪个"。

这是一个刻意设计的约束：
  让模型如实表达它看到的所有意图，把"能不能执行"的判断交给代码，
  而不是逼模型替我们做取舍。模型的判断力用在理解上，工程规则用在执行上。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.task.commands import Command, command_from_dict


@dataclass(slots=True)
class TaskTurnPlan:
    commands: list[Command] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskTurnPlan:
        commands: list[Command] = []
        for item in data.get("commands") or []:
            command = command_from_dict(item)
            if command is not None:
                commands.append(command)
        return cls(commands=commands)

    def to_dict(self) -> dict[str, Any]:
        result: list[dict[str, Any]] = []
        for command in self.commands:
            payload: dict[str, Any] = {"command": command.command}
            if hasattr(command, "flow"):
                payload["flow"] = getattr(command, "flow")
            if hasattr(command, "slots"):
                payload["slots"] = getattr(command, "slots")
            result.append(payload)
        return {"commands": result}


@dataclass(slots=True)
class KnowledgeTurnPlan:
    intents: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgeTurnPlan:
        return cls(intents=[str(i) for i in (data.get("intents") or [])])

    def to_dict(self) -> dict[str, Any]:
        return {"intents": list(self.intents)}


@dataclass(slots=True)
class ChitchatTurnPlan:
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChitchatTurnPlan:
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {}


@dataclass(slots=True)
class TurnPlan:
    task: TaskTurnPlan | None = None
    knowledge: KnowledgeTurnPlan | None = None
    chitchat: ChitchatTurnPlan | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TurnPlan:
        data = data or {}
        task_raw = data.get("task")
        knowledge_raw = data.get("knowledge")
        chitchat_raw = data.get("chitchat")
        return cls(
            task=TaskTurnPlan.from_dict(task_raw) if isinstance(task_raw, dict) else None,
            knowledge=(
                KnowledgeTurnPlan.from_dict(knowledge_raw)
                if isinstance(knowledge_raw, dict)
                else None
            ),
            chitchat=ChitchatTurnPlan.from_dict(chitchat_raw) if isinstance(chitchat_raw, dict) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task.to_dict() if self.task else None,
            "knowledge": self.knowledge.to_dict() if self.knowledge else None,
            "chitchat": self.chitchat.to_dict() if self.chitchat else None,
        }
