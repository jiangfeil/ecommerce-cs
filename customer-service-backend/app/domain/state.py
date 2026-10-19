"""对话状态：整个系统唯一的"记忆"。

一次消息处理 = 从库里读出 DialogueState → 在它身上读写 → 写回库里。
所有组件（Planner、Handler、Executor）都只操作这一个对象，不存在第二份状态。

结构分四组：
  1. 用户任务上下文  active_task / paused_tasks
  2. 系统任务上下文  active_system_flow
  3. 聚焦对象        focused_object
  4. 会话历史        sessions / current_session_id / pending_turn
"""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from app.domain.messages import BotMessage, FocusedObject, UserMessage
from app.domain.system_contexts import SystemContext


def _new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"


# --------------------------------------------------------------------------
# 用户任务上下文
# --------------------------------------------------------------------------
@dataclass(slots=True)
class TaskContext:
    """一个业务任务的执行进度。

    slots 挂在这里而不是挂在整个对话上，是为了让不同任务的参数空间互相隔离：
    退款任务收集到一半被物流查询打断，退款已填的订单号仍然留在自己的 slots 里。
    """

    flow_id: str
    step_id: str | None = None
    slots: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TaskContext | None:
        if not data:
            return None
        return cls(
            flow_id=data.get("flow_id", ""),
            step_id=data.get("step_id"),
            slots=dict(data.get("slots") or {}),
        )


# --------------------------------------------------------------------------
# 会话与轮次
# --------------------------------------------------------------------------
@dataclass(slots=True)
class Turn:
    """一轮对话 = 一次用户输入 + 机器人可能的多条回复。"""

    turn_id: str
    input_message: UserMessage
    assistant_messages: list[BotMessage] = field(default_factory=list)

    @property
    def user_message(self) -> str:
        return self.input_message.text

    @property
    def bot_messages(self) -> list[BotMessage]:
        """兼容旧叫法。"""
        return self.assistant_messages

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "input_message": self.input_message.to_dict(),
            "assistant_messages": [m.to_dict() for m in self.assistant_messages],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Turn:
        return cls(
            turn_id=data.get("turn_id", ""),
            input_message=UserMessage.from_dict(data.get("input_message") or {}),
            assistant_messages=[
                BotMessage.from_dict(m) for m in data.get("assistant_messages") or []
            ],
        )


@dataclass(slots=True)
class Session:
    """按活跃时间窗口把 Turn 分组。

    用户隔很久再回来，就开一个新 Session 并清空运行时状态；
    旧 Session 的历史仍然保留，可以翻回去看。
    """

    session_id: str
    started_at: float
    last_activity_at: float
    closed_at: float | None = None
    turns: list[Turn] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "last_activity_at": self.last_activity_at,
            "closed_at": self.closed_at,
            "turns": [t.to_dict() for t in self.turns],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        return cls(
            session_id=data.get("session_id", ""),
            started_at=float(data.get("started_at") or 0),
            last_activity_at=float(data.get("last_activity_at") or 0),
            closed_at=data.get("closed_at"),
            turns=[Turn.from_dict(t) for t in data.get("turns") or []],
        )


# --------------------------------------------------------------------------
# 对话状态
# --------------------------------------------------------------------------
@dataclass
class DialogueState:
    sender_id: str
    active_task: TaskContext | None = None
    paused_tasks: list[TaskContext] = field(default_factory=list)
    active_system_flow: SystemContext | None = None
    focused_object: FocusedObject | None = None
    sessions: list[Session] = field(default_factory=list)
    current_session_id: str | None = None
    pending_turn: Turn | None = None

    # ---------------------------------------------------------------- 会话
    def current_session(self) -> Session | None:
        if not self.current_session_id:
            return None
        for session in self.sessions:
            if session.session_id == self.current_session_id:
                return session
        return None

    def start_session(self) -> Session:
        now = time.time()
        session = Session(
            session_id=_new_id("session"),
            started_at=now,
            last_activity_at=now,
        )
        self.sessions.append(session)
        self.current_session_id = session.session_id
        return session

    def close_current_session(self) -> None:
        session = self.current_session()
        if session is not None:
            session.closed_at = time.time()

    def reset_runtime_state_for_new_session(self) -> None:
        """会话超时后清理运行时状态，但保留 sessions 历史。"""
        self.active_task = None
        self.paused_tasks = []
        self.active_system_flow = None
        self.focused_object = None
        self.pending_turn = None

    def recent_turns(self, limit: int = 10) -> list[Turn]:
        session = self.current_session()
        if session is None:
            return []
        if limit <= 0:
            return list(session.turns)
        return session.turns[-limit:]

    # ---------------------------------------------------------------- 轮次
    def begin_turn(self, message: UserMessage) -> Turn:
        self.pending_turn = Turn(
            turn_id=message.message_id or _new_id("turn"),
            input_message=message,
        )
        return self.pending_turn

    def commit_pending_turn(self) -> None:
        """把本轮写进会话历史。处理过程抛异常时不会走到这里，因此不会留下半截记录。"""
        turn = self.pending_turn
        if turn is None:
            return
        session = self.current_session()
        if session is None:
            session = self.start_session()
        session.turns.append(turn)
        session.last_activity_at = time.time()
        self.pending_turn = None

    # ------------------------------------------------------------ 聚焦对象
    def set_focused_object(self, focused_object: FocusedObject | None) -> None:
        self.focused_object = focused_object

    # ------------------------------------------------------------ 用户任务
    def start_new_task(self, flow_id: str, step_id: str | None = None) -> TaskContext:
        self.active_task = TaskContext(flow_id=flow_id, step_id=step_id, slots={})
        return self.active_task

    def pause_active_task(self) -> TaskContext | None:
        if self.active_task is None:
            return None
        paused = self.active_task
        self.paused_tasks.append(paused)
        self.active_task = None
        return paused

    def interrupt_active_task(self) -> TaskContext | None:
        """临时离开业务轨道（问知识、闲聊）时调用，语义上等同挂起。"""
        return self.pause_active_task()

    def cancel_active_task(self) -> TaskContext | None:
        canceled = self.active_task
        self.active_task = None
        return canceled

    def finish_active_task(self) -> None:
        self.active_task = None

    def activate_task(self, task: TaskContext) -> None:
        self.active_task = task

    def pop_paused_task(self, flow_id: str) -> TaskContext | None:
        for index, task in enumerate(self.paused_tasks):
            if task.flow_id == flow_id:
                return self.paused_tasks.pop(index)
        return None

    def find_paused_task(self, flow_id: str) -> TaskContext | None:
        for task in self.paused_tasks:
            if task.flow_id == flow_id:
                return task
        return None

    def set_slot(self, name: str, value: Any) -> None:
        if self.active_task is not None:
            self.active_task.slots[name] = value

    # ------------------------------------------------------------ 系统流程
    @property
    def active_system_task(self) -> SystemContext | None:
        """兼容旧叫法。"""
        return self.active_system_flow

    def activate_system_flow(self, context: SystemContext) -> None:
        self.active_system_flow = context

    def end_system_flow(self) -> None:
        self.active_system_flow = None

    # ---------------------------------------------------------- 序列化
    def to_dict(self) -> dict[str, Any]:
        return {
            "sender_id": self.sender_id,
            "active_task": self.active_task.to_dict() if self.active_task else None,
            "paused_tasks": [t.to_dict() for t in self.paused_tasks],
            "active_system_flow": (
                self.active_system_flow.to_dict() if self.active_system_flow else None
            ),
            "focused_object": (
                self.focused_object.to_dict() if self.focused_object else None
            ),
            "sessions": [s.to_dict() for s in self.sessions],
            "current_session_id": self.current_session_id,
            # pending_turn 是请求内瞬态，不落库
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DialogueState:
        return cls(
            sender_id=data.get("sender_id", ""),
            active_task=TaskContext.from_dict(data.get("active_task")),
            paused_tasks=[TaskContext.from_dict(t) for t in data.get("paused_tasks") or [] if t],
            active_system_flow=SystemContext.from_dict(data.get("active_system_flow")),
            focused_object=FocusedObject.from_dict(data.get("focused_object")),
            sessions=[Session.from_dict(s) for s in data.get("sessions") or []],
            current_session_id=data.get("current_session_id"),
        )
