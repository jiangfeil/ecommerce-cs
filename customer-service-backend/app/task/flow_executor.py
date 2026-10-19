"""FlowExecutor：把 flow 图纸"跑"起来。

它回答三个问题：
  1. 现在该推进哪个上下文？   系统流程优先于业务任务
  2. 当前 step 要做什么？     start 跳转 / collect 收槽位 / action 执行 / end 收尾
  3. 什么时候停？             遇到 action_listen 就停，把控制权交回用户

整个推进是一个循环：一直走到"需要用户说话"为止。
一轮用户输入可能连续推进很多 step（开始 → 问 → 查接口 → 回复 → 结束）。
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.domain.state import DialogueState, TaskContext
from app.domain.system_contexts import CollectSystemContext, SystemContext
from app.infrastructure.prompts import render
from app.task.actions import ActionCall, ActionRunner, build_render_variables
from app.task.flow_models import (
    ActionFlowStep,
    CollectSlotStep,
    ConditionalLink,
    EndFlowStep,
    FallbackLink,
    Flow,
    FlowsList,
    FlowStep,
    StartFlowStep,
)


class FlowExecutor:
    # ------------------------------------------------------------------ 主循环
    async def run_task(
        self,
        state: DialogueState,
        flows: FlowsList,
        action_runner: ActionRunner,
        max_steps: int = 1000,
    ) -> list[Any]:
        messages: list[Any] = []
        for _ in range(max_steps):
            action_call = self.advance_until_action(state, flows)
            if action_call.action_name == "action_listen":
                break

            action_result = await action_runner.run(action_call, state)
            for slot_name, value in action_result.slot_updates.items():
                state.set_slot(slot_name, value)
            messages.extend(action_result.messages)
        else:
            raise RuntimeError(f"Flow execution exceeded {max_steps} steps.")
        return messages

    # -------------------------------------------------------------- 推进到动作
    def advance_until_action(
        self,
        state: DialogueState,
        flows: FlowsList,
        max_steps: int = 1000,
    ) -> ActionCall:
        for _ in range(max_steps):
            context, flow = self._current_context(state, flows)
            if context is None or flow is None:
                return ActionCall(action_name="action_listen")

            step = flow.get_step_by_id(context.step_id)
            if step is None:
                # 配置里指向了不存在的 step，安全收尾，避免死循环
                self._finish_context(state)
                continue

            action_call = self._run_step(step, flow, state, flows, context)
            if action_call is not None:
                return action_call
        raise RuntimeError(f"Flow advance exceeded {max_steps} steps.")

    # ------------------------------------------------------------ 选择上下文
    def _current_context(
        self,
        state: DialogueState,
        flows: FlowsList,
    ) -> tuple[TaskContext | SystemContext | None, Flow | None]:
        system_flow = state.active_system_flow
        if system_flow is not None:
            # 自愈：如果系统只是在问某个槽位，而该槽位其实已经有值了
            # （用户换了种说法回答，没被识别成 set_slots），
            # 就先把这条询问流程收掉，回到业务任务继续推进。
            if isinstance(system_flow, CollectSystemContext) and self._slot_filled(
                state, system_flow.slot_name
            ):
                state.end_system_flow()
            else:
                flow = flows.get_flow_by_id(system_flow.flow_id)
                return system_flow, flow

        if state.active_task is not None:
            flow = flows.get_flow_by_id(state.active_task.flow_id)
            return state.active_task, flow

        return None, None

    @staticmethod
    def _slot_filled(state: DialogueState, slot_name: str) -> bool:
        if not slot_name or state.active_task is None:
            return False
        value = state.active_task.slots.get(slot_name)
        return value not in (None, "")

    # ------------------------------------------------------------- step 分发
    def _run_step(
        self,
        step: FlowStep,
        flow: Flow,
        state: DialogueState,
        flows: FlowsList,
        context: TaskContext | SystemContext,
    ) -> ActionCall | None:
        variables = self._variables(state, context)

        if isinstance(step, StartFlowStep):
            self._advance_to_next_step(step, flow, state, context, variables)
            return None

        if isinstance(step, CollectSlotStep):
            return self._run_collect_step(step, flow, state, flows, context, variables)

        if isinstance(step, ActionFlowStep):
            return self._run_action_step(step, flow, state, context, variables)

        if isinstance(step, EndFlowStep):
            self._finish_context(state)
            return None

        raise TypeError(f"Unsupported step type: {type(step)!r}")

    # ------------------------------------------------------------- start step
    def _run_start_step(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        return None

    # ----------------------------------------------------------- collect step
    def _run_collect_step(
        self,
        step: CollectSlotStep,
        flow: Flow,
        state: DialogueState,
        flows: FlowsList,
        context: TaskContext | SystemContext,
        variables: dict[str, Any],
    ) -> ActionCall | None:
        slots = variables.get("slots") or {}
        value = slots.get(step.slot_name)

        if value not in (None, ""):
            # 有值了：先校验格式，通过就往下走
            if step.validation and step.validation.condition:
                if not self._eval(step.validation.condition, variables):
                    state.set_slot(step.slot_name, "")
                    failure = step.validation.failure_response
                    if failure and (failure.text or failure.prompt):
                        return ActionCall(
                            action_name="action_response",
                            action_kwargs={
                                "mode": failure.mode,
                                "text": failure.text or "",
                                "prompt": failure.prompt,
                            },
                        )
                    return None
            self._advance_to_next_step(step, flow, state, context, variables)
            return None

        # 没值：挂一条"请补充信息"的系统流程，然后停下等用户
        system_flow = flows.get_flow_by_id("system_collect_information")
        if system_flow is None:
            return ActionCall(action_name="action_listen")
        start_step = system_flow.start_step()

        collect_context = CollectSystemContext(
            slot_name=step.slot_name,
            response={
                "mode": step.response.mode,
                "text": step.response.text or "",
                "prompt": step.response.prompt,
            },
        )
        collect_context.step_id = start_step.id if start_step else None
        state.activate_system_flow(collect_context)
        return None

    # ------------------------------------------------------------ action step
    def _run_action_step(
        self,
        step: ActionFlowStep,
        flow: Flow,
        state: DialogueState,
        context: TaskContext | SystemContext,
        variables: dict[str, Any],
    ) -> ActionCall:
        # 先前进到下一步，再执行当前 action。
        # 这样 action 执行完下一轮循环自然落在后置 step 上，
        # 不会因为 action 里改了槽位而重复执行同一个动作。
        self._advance_to_next_step(step, flow, state, context, variables)

        action_name = render(step.action, variables)

        if isinstance(step.args, str):
            resolved = self._resolve_reference(step.args, variables)
            if isinstance(resolved, dict):
                action_kwargs = dict(resolved)
            else:
                action_kwargs = {"text": "" if resolved is None else str(resolved)}
        elif isinstance(step.args, dict):
            action_kwargs = render(step.args, variables)
        else:
            action_kwargs = {}

        return ActionCall(action_name=action_name, action_kwargs=action_kwargs)

    # --------------------------------------------------------------- end step
    def _finish_context(self, state: DialogueState) -> None:
        if state.active_system_flow is not None:
            state.end_system_flow()
        elif state.active_task is not None:
            state.finish_active_task()

    # ------------------------------------------------------------ next 解析
    def _advance_to_next_step(
        self,
        step: FlowStep,
        flow: Flow,
        state: DialogueState,
        context: TaskContext | SystemContext,
        variables: dict[str, Any],
    ) -> None:
        target = self._select_next(step, variables)
        if target is None:
            self._finish_context(state)
        else:
            context.step_id = target

    def _select_next(
        self,
        step: FlowStep,
        variables: dict[str, Any],
    ) -> str | None:
        for link in step.next:
            if isinstance(link, ConditionalLink):
                if self._eval(link.condition, variables):
                    return link.target
            elif isinstance(link, FallbackLink):
                return link.target
            else:
                return link.target
        return None

    # ------------------------------------------------------------ 表达式求值
    @staticmethod
    def _eval(condition: str, variables: dict[str, Any]) -> bool:
        """只在受限环境里求值，配置可信但也不放开内置函数。"""
        try:
            return bool(
                eval(  # noqa: S307 - 表达式来自本地 flow 配置，不可由用户输入
                    condition,
                    {"__builtins__": {}},
                    {
                        "slots": variables.get("slots") or {},
                        "context": variables.get("context") or {},
                        "len": len,
                        "bool": bool,
                        "any": any,
                        "all": all,
                    },
                )
            )
        except Exception:  # noqa: BLE001 - 条件写错时按 False 处理
            return False

    # ------------------------------------------------------------ 变量与引用
    @staticmethod
    def _variables(
        state: DialogueState,
        context: TaskContext | SystemContext,
    ) -> dict[str, Any]:
        variables = build_render_variables(state)
        if isinstance(context, SystemContext):
            variables["context"] = {
                k: v for k, v in asdict(context).items() if k != "kind"
            }
        return variables

    @staticmethod
    def _resolve_reference(reference: str, variables: dict[str, Any]) -> Any:
        """解析 "context.response" 这种点路径引用。"""
        current: Any = variables
        for part in reference.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                current = getattr(current, part, None)
            if current is None:
                return None
        return current
