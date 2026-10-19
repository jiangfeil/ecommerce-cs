"""系统流程上下文。

系统流程是"由系统主动发起"的交互，用来通知用户：
任务开始了、任务恢复了、任务被打断了、请补充信息……

它和用户任务上下文（TaskContext）的区别是：
- TaskContext 记录"用户正在办的事"，可以有多个（1 个活跃 + N 个挂起）
- SystemContext 记录"系统正在对用户说的话"，同一时刻最多 1 个，且优先级高于 TaskContext

因此 FlowExecutor 每轮推进时，先看 active_system_flow，没有才看 active_task。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class SystemContext:
    flow_id: str
    step_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = type(self).__name__
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SystemContext | None:
        if not data:
            return None
        kind = data.get("kind") or "SystemContext"
        target = _SYSTEM_CONTEXT_TYPES.get(kind, SystemContext)
        known = {f for f in target.__dataclass_fields__}  # type: ignore[attr-defined]
        payload = {k: v for k, v in data.items() if k in known}
        return target(**payload)


@dataclass(slots=True)
class CollectSystemContext(SystemContext):
    """正在向用户索要某个槽位。"""

    flow_id: str = "system_collect_information"
    slot_name: str = ""
    response: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StartedSystemContext(SystemContext):
    """通知：新任务已开始。"""

    flow_id: str = "system_task_started"
    started_flow_id: str = ""
    started_flow_name: str = ""


@dataclass(slots=True)
class ResumedSystemContext(SystemContext):
    """通知：挂起任务已恢复。"""

    flow_id: str = "system_task_resumed"
    resumed_flow_id: str = ""
    resumed_flow_name: str = ""


@dataclass(slots=True)
class CanceledSystemContext(SystemContext):
    """通知：当前任务已取消。"""

    flow_id: str = "system_task_canceled"
    canceled_flow_id: str = ""
    canceled_flow_name: str = ""


@dataclass(slots=True)
class InterruptedSystemContext(SystemContext):
    """通知：旧任务被打断，新任务已开始。"""

    flow_id: str = "system_task_interrupted"
    interrupted_flow_id: str = ""
    interrupted_flow_name: str = ""
    started_flow_id: str = ""
    started_flow_name: str = ""


@dataclass(slots=True)
class CompletedSystemContext(SystemContext):
    """通知：任务已完成。"""

    flow_id: str = "system_completed"
    previous_flow_name: str = ""


@dataclass(slots=True)
class CannotHandleSystemContext(SystemContext):
    """通知：请求无法处理（可携带原因）。"""

    flow_id: str = "system_cannot_handle"
    reason: str | None = None


_SYSTEM_CONTEXT_TYPES: dict[str, type[SystemContext]] = {
    "SystemContext": SystemContext,
    "CollectSystemContext": CollectSystemContext,
    "StartedSystemContext": StartedSystemContext,
    "ResumedSystemContext": ResumedSystemContext,
    "CanceledSystemContext": CanceledSystemContext,
    "InterruptedSystemContext": InterruptedSystemContext,
    "CompletedSystemContext": CompletedSystemContext,
    "CannotHandleSystemContext": CannotHandleSystemContext,
}
