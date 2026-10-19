"""TurnPlanValidator：判断这轮计划能不能直接执行。

模型负责"理解"，这里负责"能不能办"。
把这两件事分开，是因为它们的失败方式不同：
  理解失败 → 需要问用户
  执行不了 → 需要走澄清或告知不支持
用一个枚举把"为什么不能办"说清楚，后面的话术生成才有依据。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.domain.state import DialogueState
from app.knowledge.intents import KnowledgeIntent
from app.planning.turn_plan import TurnPlan


class ClarifyReason(str, Enum):
    MISSING_TRACK = "missing_track"
    MULTIPLE_TRACKS = "multiple_tracks"
    MISSING_TASK_COMMANDS = "missing_task_commands"
    MISSING_KNOWLEDGE_INTENT = "missing_knowledge_intent"
    MISSING_FOCUSED_OBJECT = "missing_focused_object"
    OBJECT_REQUIRES_INTENT = "object_requires_intent"


@dataclass(slots=True)
class TurnPlanValidationResult:
    valid: bool
    reason: ClarifyReason | None = None


class TurnPlanValidator:
    def validate(
        self,
        turn_plan: TurnPlan,
        state: DialogueState,
        knowledge_intents: dict[str, KnowledgeIntent],
    ) -> TurnPlanValidationResult:
        active_tracks = self._active_tracks(turn_plan)
        if not active_tracks:
            return self._reject(ClarifyReason.MISSING_TRACK)
        if len(active_tracks) > 1:
            return self._reject(ClarifyReason.MULTIPLE_TRACKS)

        track = active_tracks[0]
        if track == "task":
            return self._validate_task(turn_plan)
        if track == "knowledge":
            return self._validate_knowledge(turn_plan, state, knowledge_intents)
        return TurnPlanValidationResult(valid=True)

    @staticmethod
    def _active_tracks(turn_plan: TurnPlan) -> list[str]:
        tracks: list[str] = []
        if turn_plan.task is not None:
            tracks.append("task")
        if turn_plan.knowledge is not None:
            tracks.append("knowledge")
        if turn_plan.chitchat is not None:
            tracks.append("chitchat")
        return tracks

    @staticmethod
    def _validate_task(turn_plan: TurnPlan) -> TurnPlanValidationResult:
        task_plan = turn_plan.task
        if task_plan is None or not task_plan.commands:
            return TurnPlanValidationResult(
                valid=False, reason=ClarifyReason.MISSING_TASK_COMMANDS
            )
        return TurnPlanValidationResult(valid=True)

    @staticmethod
    def _validate_knowledge(
        turn_plan: TurnPlan,
        state: DialogueState,
        knowledge_intents: dict[str, KnowledgeIntent],
    ) -> TurnPlanValidationResult:
        knowledge_plan = turn_plan.knowledge
        if knowledge_plan is None or not knowledge_plan.intents:
            return TurnPlanValidationResult(
                valid=False, reason=ClarifyReason.MISSING_KNOWLEDGE_INTENT
            )

        focused_object = state.focused_object
        for intent_id in knowledge_plan.intents:
            intent_meta = knowledge_intents.get(intent_id)
            if intent_meta is None:
                # 模型编了一个不存在的意图，按"没听懂"处理
                return TurnPlanValidationResult(
                    valid=False, reason=ClarifyReason.MISSING_KNOWLEDGE_INTENT
                )
            required = intent_meta.requires_object
            if required is not None:
                if focused_object is None or focused_object.type != required:
                    return TurnPlanValidationResult(
                        valid=False, reason=ClarifyReason.MISSING_FOCUSED_OBJECT
                    )
        return TurnPlanValidationResult(valid=True)

    @staticmethod
    def _reject(reason: ClarifyReason) -> TurnPlanValidationResult:
        return TurnPlanValidationResult(valid=False, reason=reason)
