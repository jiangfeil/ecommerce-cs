"""TaskHandler：任务轨道的总入口。

它只做三件事，顺序固定：
  1. 把 LLM 给出的命令应用到状态上（CommandProcessor）
  2. 推进流程直到需要用户说话（FlowExecutor + ActionRunner）
  3. 把这一轮产生的消息返回给上层

注意：这里不写 pending_turn。写轮次是 DialogueEngine 的职责，
     避免两条路径都往里塞消息导致重复回复。
"""
from __future__ import annotations

from app.domain.messages import BotMessage
from app.domain.state import DialogueState
from app.task.actions import ActionRunner
from app.task.command_processor import CommandProcessor
from app.task.commands import Command
from app.task.flow_executor import FlowExecutor
from app.task.flow_models import FlowsList


class TaskHandler:
    def __init__(
        self,
        flows: FlowsList,
        command_processor: CommandProcessor,
        flow_executor: FlowExecutor,
        action_runner: ActionRunner,
        max_steps: int = 1000,
    ) -> None:
        self.flows = flows
        self.command_processor = command_processor
        self.flow_executor = flow_executor
        self.action_runner = action_runner
        self.max_steps = max_steps

    async def handle(
        self,
        commands: list[Command],
        state: DialogueState,
    ) -> list[BotMessage]:
        if state.pending_turn is None:
            raise ValueError("No pending turn available for task handling.")

        if commands:
            self.command_processor.run(commands, state, self.flows)

        messages = await self.flow_executor.run_task(
            state,
            self.flows,
            self.action_runner,
            max_steps=self.max_steps,
        )
        return [m for m in messages if (m.text or "").strip()]
