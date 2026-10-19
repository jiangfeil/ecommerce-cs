"""DialogueEngine：一轮消息的调度中心。

它自己不做任何业务判断，只做四件事：
  1. 准备会话（超时则重置运行时状态）
  2. 开一条 Turn
  3. 按消息类型 / TurnPlan 把活分给对应的 Handler
  4. 提交 Turn，返回结果

"谁来做"这件事全部收敛在这里，Handler 之间互不感知。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.config import settings
from app.domain.messages import BotMessage, FocusedObject, MessageType, UserMessage
from app.domain.state import DialogueState
from app.domain.system_contexts import CollectSystemContext
from app.handlers.chitchat_handler import ChitchatHandler
from app.handlers.knowledge_handler import KnowledgeHandler
from app.handlers.task_handler import TaskHandler
from app.planning.clarify_responder import ClarifyResponder
from app.planning.turn_planner import TurnPlanner
from app.planning.validator import ClarifyReason, TurnPlanValidator
from app.task.commands import Command, SetSlotsCommand
from app.task.flow_models import CollectSlotStep, FlowsList


@dataclass(slots=True)
class ProcessResult:
    sender_id: str
    message_id: str
    messages: list[BotMessage] = field(default_factory=list)


class DialogueEngine:
    def __init__(
        self,
        turn_planner: TurnPlanner,
        task_handler: TaskHandler,
        knowledge_handler: KnowledgeHandler,
        chitchat_handler: ChitchatHandler,
        clarify_responder: ClarifyResponder,
        turn_plan_validator: TurnPlanValidator,
    ) -> None:
        self.turn_planner = turn_planner
        self.task_handler = task_handler
        self.knowledge_handler = knowledge_handler
        self.chitchat_handler = chitchat_handler
        self.clarify_responder = clarify_responder
        self.turn_plan_validator = turn_plan_validator

    # ------------------------------------------------------------------ 入口
    async def process_message(
        self,
        state: DialogueState,
        user_message: UserMessage,
    ) -> ProcessResult:
        self._prepare_session(state)
        self._begin_turn(state, user_message)

        try:
            if user_message.type is MessageType.TEXT:
                messages = await self._handle_text_message(state=state)
            else:
                state.set_focused_object(
                    FocusedObject.from_dict(
                        user_message.object.to_dict() if user_message.object else None
                    )
                )
                messages = await self._handle_object_message(message=user_message, state=state)
        except Exception:
            # 处理失败也要把本轮提交掉，否则 pending_turn 会一直挂着
            state.commit_pending_turn()
            raise

        if state.pending_turn is not None:
            state.pending_turn.assistant_messages.extend(messages)
        state.commit_pending_turn()

        return ProcessResult(
            sender_id=user_message.sender_id,
            message_id=user_message.message_id,
            messages=messages,
        )

    # -------------------------------------------------------------- Session
    def _prepare_session(self, state: DialogueState) -> None:
        session = state.current_session()
        now = time.time()
        if session is None:
            state.start_session()
            return
        if now - session.last_activity_at > settings.session_timeout_seconds:
            state.close_current_session()
            state.reset_runtime_state_for_new_session()
            state.start_session()
        else:
            session.last_activity_at = now

    @staticmethod
    def _begin_turn(state: DialogueState, message: UserMessage) -> None:
        state.begin_turn(message)

    # ----------------------------------------------------------- TEXT 消息
    async def _handle_text_message(self, state: DialogueState) -> list[BotMessage]:
        turn_plan = await self.turn_planner.predict(
            state,
            self.task_handler.flows,
            self.knowledge_handler.knowledge_intents,
        )
        validation = self.turn_plan_validator.validate(
            turn_plan,
            state=state,
            knowledge_intents=self.knowledge_handler.knowledge_intents,
        )

        if not validation.valid:
            # 工程兜底：系统正在问某个槽位时，用户回的那句话本质上就是槽位值。
            # 模型有时会把"10001"判成"意图不明"，这里直接把它填进槽位，
            # 避免因为一次误判让整个流程卡死。
            fallback = self._slot_fill_fallback(state, self.task_handler.flows)
            if fallback is not None:
                return await self.task_handler.handle(commands=[fallback], state=state)
            return await self._clarify(state=state, reason=validation.reason)

        if turn_plan.task is not None:
            return await self.task_handler.handle(
                commands=turn_plan.task.commands, state=state
            )

        if turn_plan.knowledge is not None:
            # 临时问一句知识，先把业务任务挂起，问完用户可以继续原来的事
            if state.active_task is not None:
                state.interrupt_active_task()
            return await self.knowledge_handler.handle(
                state=state,
                intents=turn_plan.knowledge.intents,
            )

        if state.active_task is not None:
            state.interrupt_active_task()
        return await self.chitchat_handler.handle(state=state)

    # --------------------------------------------------------- OBJECT 消息
    async def _handle_object_message(
        self,
        message: UserMessage,
        state: DialogueState,
    ) -> list[BotMessage]:
        command = self._object_slot_command(
            message=message,
            state=state,
            flows=self.task_handler.flows,
        )
        if command is None:
            return await self._clarify(
                state=state, reason=ClarifyReason.OBJECT_REQUIRES_INTENT
            )
        return await self.task_handler.handle(commands=[command], state=state)

    def _object_slot_command(
        self,
        message: UserMessage,
        state: DialogueState,
        flows: FlowsList,
    ) -> Command | None:
        if message.object is None:
            return None
        object_type = (message.object.type or "").strip().lower()
        collect_slot_name = self._current_collect_slot_name(state=state, flows=flows)

        if object_type == "order" and collect_slot_name == "order_number":
            return SetSlotsCommand(
                command="set_slots", slots={"order_number": message.object.id}
            )
        if object_type == "product" and collect_slot_name == "product_id":
            return SetSlotsCommand(
                command="set_slots", slots={"product_id": message.object.id}
            )
        return None

    @staticmethod
    def _current_collect_slot_name(
        state: DialogueState,
        flows: FlowsList,
    ) -> str | None:
        if isinstance(state.active_system_flow, CollectSystemContext):
            return state.active_system_flow.slot_name or None

        active_task = state.active_task
        if active_task is None:
            return None
        flow = flows.get_flow_by_id(active_task.flow_id)
        if flow is None:
            return None
        current_step = flow.get_step_by_id(active_task.step_id)
        if not isinstance(current_step, CollectSlotStep):
            return None
        return current_step.slot_name

    def _slot_fill_fallback(
        self,
        state: DialogueState,
        flows: FlowsList,
    ) -> Command | None:
        slot_name = self._current_collect_slot_name(state, flows)
        if not slot_name or state.pending_turn is None:
            return None

        text = (state.pending_turn.input_message.text or "").strip()
        if not text or len(text) > 100:
            return None
        if any(word in text for word in ("取消", "算了", "不用了", "别弄了", "换个")):
            return None
        return SetSlotsCommand(command="set_slots", slots={slot_name: text})

    # ------------------------------------------------------------ 澄清
    async def _clarify(
        self,
        state: DialogueState,
        reason: ClarifyReason | None,
    ) -> list[BotMessage]:
        return await self.clarify_responder.respond(
            state=state,
            reason=reason or ClarifyReason.MISSING_TRACK,
        )
