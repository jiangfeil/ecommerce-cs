"""CommandProcessor：把命令作用到对话状态上。

这是"意图"与"状态"之间唯一的转换层。
它不产生任何用户可见的回复，只负责改状态；回复由 FlowExecutor 推进流程时产生。
"""
from __future__ import annotations

from app.domain.state import DialogueState
from app.domain.system_contexts import (
    CanceledSystemContext,
    CollectSystemContext,
    InterruptedSystemContext,
    ResumedSystemContext,
    StartedSystemContext,
    SystemContext,
)
from app.task.commands import (
    CancelFlowCommand,
    Command,
    ResumeTaskCommand,
    SetSlotsCommand,
    StartFlowCommand,
)
from app.task.flow_models import Flow, FlowsList


class CommandProcessor:
    def run(
        self,
        commands: list[Command],
        state: DialogueState,
        flows: FlowsList,
    ) -> None:
        for command in commands:
            self._apply(command, state, flows)

    def _apply(
        self,
        command: Command,
        state: DialogueState,
        flows: FlowsList,
    ) -> None:
        if isinstance(command, StartFlowCommand):
            self._handle_start_flow(command, state, flows)
        elif isinstance(command, SetSlotsCommand):
            self._handle_set_slots(command, state)
        elif isinstance(command, CancelFlowCommand):
            self._handle_cancel_flow(state, flows)
        elif isinstance(command, ResumeTaskCommand):
            self._handle_resume_task(command, state, flows)

    # ------------------------------------------------------------ start_flow
    def _handle_start_flow(
        self,
        command: StartFlowCommand,
        state: DialogueState,
        flows: FlowsList,
    ) -> None:
        target_flow = flows.get_flow_by_id(command.flow)
        if target_flow is None:
            return
        start_step = target_flow.start_step()
        if start_step is None:
            return

        state.end_system_flow()
        active = state.active_task

        # 已经在做同一件事：不重复启动，继续原来的进度
        if active is not None and active.flow_id == target_flow.id:
            return

        # 没有活跃任务，但这件事之前被挂起过：直接恢复，保住已填的槽位
        if active is None:
            paused = state.find_paused_task(target_flow.id)
            if paused is not None:
                state.pop_paused_task(target_flow.id)
                state.activate_task(paused)
                self._activate_system_flow(
                    state,
                    flows,
                    ResumedSystemContext(
                        resumed_flow_id=target_flow.id,
                        resumed_flow_name=target_flow.name or target_flow.id,
                    ),
                )
                return

            state.start_new_task(target_flow.id, start_step.id)
            self._activate_system_flow(
                state,
                flows,
                StartedSystemContext(
                    started_flow_id=target_flow.id,
                    started_flow_name=target_flow.name or target_flow.id,
                ),
            )
            return

        # 正在办 A，又要办 B：挂起 A，启动 B，并告知用户
        state.pause_active_task()
        state.start_new_task(target_flow.id, start_step.id)
        self._activate_system_flow(
            state,
            flows,
            InterruptedSystemContext(
                interrupted_flow_id=active.flow_id,
                interrupted_flow_name=self._flow_name(flows, active.flow_id),
                started_flow_id=target_flow.id,
                started_flow_name=target_flow.name or target_flow.id,
            ),
        )

    # ------------------------------------------------------------- set_slots
    def _handle_set_slots(
        self,
        command: SetSlotsCommand,
        state: DialogueState,
    ) -> None:
        if state.active_task is None:
            return
        for name, value in command.slots.items():
            state.set_slot(name, value)

        # 用户已经把答案给出来了，系统那条"请告诉我订单号"的询问流程就该收尾，
        # 否则下一轮 FlowExecutor 还会先看到它，导致流程卡住。
        if isinstance(state.active_system_flow, CollectSystemContext):
            state.end_system_flow()

    # ----------------------------------------------------------- cancel_flow
    def _handle_cancel_flow(
        self,
        state: DialogueState,
        flows: FlowsList,
    ) -> None:
        canceled = state.cancel_active_task()
        if canceled is None:
            return
        self._activate_system_flow(
            state,
            flows,
            CanceledSystemContext(
                canceled_flow_id=canceled.flow_id,
                canceled_flow_name=self._flow_name(flows, canceled.flow_id),
            ),
        )

    # ----------------------------------------------------------- resume_flow
    def _handle_resume_task(
        self,
        command: ResumeTaskCommand,
        state: DialogueState,
        flows: FlowsList,
    ) -> None:
        target_flow = flows.get_flow_by_id(command.flow)
        if target_flow is None:
            return

        active = state.active_task
        if active is not None and active.flow_id == target_flow.id:
            return

        if active is None:
            paused = state.pop_paused_task(target_flow.id)
            if paused is None:
                return
            state.activate_task(paused)
            self._activate_system_flow(
                state,
                flows,
                ResumedSystemContext(
                    resumed_flow_id=target_flow.id,
                    resumed_flow_name=target_flow.name or target_flow.id,
                ),
            )
            return

        paused = state.pop_paused_task(target_flow.id)
        if paused is None:
            return
        interrupted = active
        state.pause_active_task()
        state.activate_task(paused)
        self._activate_system_flow(
            state,
            flows,
            InterruptedSystemContext(
                interrupted_flow_id=interrupted.flow_id,
                interrupted_flow_name=self._flow_name(flows, interrupted.flow_id),
                started_flow_id=target_flow.id,
                started_flow_name=target_flow.name or target_flow.id,
            ),
        )

    # ---------------------------------------------------------------- helper
    @staticmethod
    def _flow_name(flows: FlowsList, flow_id: str) -> str:
        flow: Flow | None = flows.get_flow_by_id(flow_id)
        return (flow.name or flow.id) if flow else flow_id

    @staticmethod
    def _activate_system_flow(
        state: DialogueState,
        flows: FlowsList,
        context: SystemContext,
    ) -> None:
        flow = flows.get_flow_by_id(context.flow_id)
        if flow is None:
            return
        start_step = flow.start_step()
        context.step_id = start_step.id if start_step else None
        state.activate_system_flow(context)
