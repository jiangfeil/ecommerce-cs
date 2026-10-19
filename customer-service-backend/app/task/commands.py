"""Command：大模型对"用户想干什么"的结构化表达。

TurnPlanner 只负责把自然语言翻译成这 4 种命令之一（或几种），
真正改状态的是 CommandProcessor。两者分开的好处是：
模型再怎么幻觉，也只能在这 4 种动作里选，破坏不了状态机。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Command:
    command: str

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Command | None:
        return command_from_dict(data)


@dataclass
class StartFlowCommand(Command):
    flow: str = ""


@dataclass
class SetSlotsCommand(Command):
    slots: dict[str, Any] = field(default_factory=dict)


@dataclass
class CancelFlowCommand(Command):
    pass


@dataclass
class ResumeTaskCommand(Command):
    """恢复一个被挂起的任务。"""

    flow: str = ""


def command_from_dict(data: dict[str, Any]) -> Command | None:
    """把 LLM 输出的 JSON 命令转成对象；无法识别时返回 None。"""
    if not isinstance(data, dict):
        return None

    name = str(data.get("command") or "").strip()
    if name == "start_flow":
        return StartFlowCommand(command=name, flow=str(data.get("flow") or ""))
    if name == "set_slots":
        slots = data.get("slots") or {}
        if not isinstance(slots, dict):
            return None
        return SetSlotsCommand(command=name, slots=dict(slots))
    if name == "cancel_flow":
        return CancelFlowCommand(command=name)
    if name in {"resume_flow", "resume_task"}:
        return ResumeTaskCommand(command="resume_flow", flow=str(data.get("flow") or ""))
    return None
