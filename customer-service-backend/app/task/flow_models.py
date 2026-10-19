"""Flow 配置的静态模型。

一条 flow 就是一张"流程图纸"：由若干 step 串起来，step 之间用 next 连接。
系统只认识 4 种 step，这 4 种足够表达客服里绝大多数业务流程：
  start   入口，本身不产生任何输出，只负责跳到下一步
  collect 收集一个槽位；槽位没值就向用户提问并停下等待
  action  执行一个动作（回复、查接口、提交申请……）
  end     结束当前流程
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class FlowStepType(str, Enum):
    START = "start"
    ACTION = "action"
    COLLECT = "collect"
    END = "end"


# --------------------------------------------------------------------------
# 下一步怎么走
# --------------------------------------------------------------------------
@dataclass(slots=True)
class FlowStepLink:
    target: str


@dataclass(slots=True)
class StaticLink(FlowStepLink):
    """无条件跳到 target。"""


@dataclass(slots=True)
class ConditionalLink(FlowStepLink):
    """condition 为真时跳到 target。"""

    condition: str = ""


@dataclass(slots=True)
class FallbackLink(FlowStepLink):
    """前面所有条件都不成立时走这里（相当于 else）。"""


# --------------------------------------------------------------------------
# step 的配置片段
# --------------------------------------------------------------------------
@dataclass(slots=True)
class ResponseDefinition:
    mode: str = "static"
    text: str | None = None
    prompt: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | str | None) -> ResponseDefinition:
        if data is None:
            return cls()
        if isinstance(data, str):
            return cls(mode="static", text=data)
        return cls(
            mode=str(data.get("mode") or "static"),
            text=data.get("text"),
            prompt=data.get("prompt"),
        )


@dataclass(slots=True)
class SlotValidation:
    condition: str | None = None
    failure_response: ResponseDefinition | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SlotValidation | None:
        if not data:
            return None
        return cls(
            condition=data.get("condition"),
            failure_response=ResponseDefinition.from_dict(data.get("failure_response")),
        )


# --------------------------------------------------------------------------
# step
# --------------------------------------------------------------------------
@dataclass(slots=True)
class FlowStep:
    id: str
    type: FlowStepType
    next: list[FlowStepLink] = field(default_factory=list)
    description: str = ""


@dataclass(slots=True)
class StartFlowStep(FlowStep):
    pass


@dataclass(slots=True)
class ActionFlowStep(FlowStep):
    action: str = ""
    # args 既可能是结构化的 dict，也可能是一句引用（如 "context.response"）
    args: dict[str, Any] | str = field(default_factory=dict)


@dataclass(slots=True)
class CollectSlotStep(FlowStep):
    slot_name: str = ""
    response: ResponseDefinition = field(default_factory=ResponseDefinition)
    validation: SlotValidation | None = None


@dataclass(slots=True)
class EndFlowStep(FlowStep):
    pass


# --------------------------------------------------------------------------
# flow 与 flow 集合
# --------------------------------------------------------------------------
@dataclass(slots=True)
class FlowSlot:
    name: str
    type: str = "any"
    label: str = ""
    description: str = ""


@dataclass(slots=True)
class Flow:
    id: str
    description: str = ""
    steps: list[FlowStep] = field(default_factory=list)
    slots: list[FlowSlot] = field(default_factory=list)
    name: str | None = None

    def get_step_by_id(self, step_id: str | None) -> FlowStep | None:
        if step_id is None:
            return self.start_step()
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def start_step(self) -> FlowStep | None:
        for step in self.steps:
            if isinstance(step, StartFlowStep):
                return step
        return self.steps[0] if self.steps else None


@dataclass(slots=True)
class FlowsList:
    flows: list[Flow] = field(default_factory=list)
    slots: dict[str, FlowSlot] = field(default_factory=dict)

    def get_flow_by_id(self, flow_id: str) -> Flow | None:
        for flow in self.flows:
            if flow.id == flow_id:
                return flow
        return None

    def require_flow(self, flow_id: str) -> Flow:
        flow = self.get_flow_by_id(flow_id)
        if flow is None:
            raise KeyError(f"Unknown flow '{flow_id}'.")
        return flow

    def get_slot(self, name: str) -> FlowSlot | None:
        return self.slots.get(name)

    def summary(self) -> list[dict[str, Any]]:
        """给 TurnPlanner 的"可用能力清单"，故意不带 steps，避免提示词过长。"""
        return [
            {
                "id": flow.id,
                "name": flow.name,
                "description": flow.description,
                "slots": [
                    {"name": slot.name, "description": slot.description or slot.label}
                    for slot in flow.slots
                ],
            }
            for flow in self.flows
        ]

    def flow_to_dict(self, flow: Flow) -> dict[str, Any]:
        data = asdict(flow)
        data.pop("steps", None)
        return data
