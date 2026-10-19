"""TurnPlanner：把用户这句话翻译成 TurnPlan。

它是整个系统里唯一"必须依赖大模型"的地方，因为只有它要处理开放的自然语言。
其余所有组件都是确定性的代码，模型再怎么出错也影响不到流程执行。

内置两级策略：
  1. 正常走模型（结构化输出 JSON）
  2. 模型不可用 / 输出不合法 / Key 没配 → 走规则兜底，保证 demo 可跑
"""
from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.domain.state import DialogueState
from app.infrastructure.history import HistoryBuilder
from app.infrastructure.llm import LLMError, get_llm
from app.infrastructure.prompts import load_prompt, render
from app.knowledge.intents import KnowledgeIntent
from app.planning.turn_plan import (
    ChitchatTurnPlan,
    KnowledgeTurnPlan,
    TaskTurnPlan,
    TurnPlan,
)
from app.task.commands import StartFlowCommand
from app.task.flow_models import FlowsList


class TurnPlanner:
    async def predict(
        self,
        state: DialogueState,
        flows: FlowsList,
        knowledge_intents: dict[str, KnowledgeIntent],
    ) -> TurnPlan:
        prompt_inputs = self._build_prompt_inputs(state, flows, knowledge_intents)
        return await self._predict_from_prompt_inputs(prompt_inputs, state, flows)

    # ------------------------------------------------------- 构造提示词输入
    def _build_prompt_inputs(
        self,
        state: DialogueState,
        flows: FlowsList,
        knowledge_intents: dict[str, KnowledgeIntent],
    ) -> dict[str, Any]:
        pending = state.pending_turn
        user_message = (
            HistoryBuilder.render_user_message(pending.input_message) if pending else ""
        )
        history = HistoryBuilder.build(state.recent_turns(settings.history_turns))

        active_task = state.active_task
        active_task_json: dict[str, Any] | None = None
        if active_task is not None:
            flow = flows.get_flow_by_id(active_task.flow_id)
            active_task_json = {
                "flow_id": active_task.flow_id,
                "flow_name": (flow.name if flow else None) or active_task.flow_id,
                "step_id": active_task.step_id,
                "slots": active_task.slots,
            }

        interrupted: list[dict[str, Any]] = []
        for task in state.paused_tasks:
            flow = flows.get_flow_by_id(task.flow_id)
            interrupted.append(
                {
                    "flow_id": task.flow_id,
                    "flow_name": (flow.name if flow else None) or task.flow_id,
                    "step_id": task.step_id,
                    "slots": task.slots,
                }
            )

        focused_object = state.focused_object

        return {
            "current_conversation": history,
            "user_message": user_message,
            "available_flows_json": json.dumps(
                {"flows": flows.summary()}, ensure_ascii=False
            ),
            "knowledge_intents_json": json.dumps(
                [
                    {"id": intent.id, "description": intent.description}
                    for intent in knowledge_intents.values()
                ],
                ensure_ascii=False,
            ),
            "active_task_json": json.dumps(active_task_json, ensure_ascii=False),
            "interrupted_tasks_json": json.dumps(interrupted, ensure_ascii=False),
            "focused_object_json": json.dumps(
                focused_object.to_dict() if focused_object else None,
                ensure_ascii=False,
            ),
        }

    # ------------------------------------------------------------- 调用模型
    async def _predict_from_prompt_inputs(
        self,
        prompt_inputs: dict[str, Any],
        state: DialogueState,
        flows: FlowsList,
    ) -> TurnPlan:
        llm = get_llm()
        if not llm.available:
            return self._fallback_plan(prompt_inputs, state, flows)

        prompt = render(load_prompt("turn_plan"), prompt_inputs)
        try:
            payload = await llm.complete_json(prompt)
            return TurnPlan.from_dict(payload)
        except LLMError:
            return self._fallback_plan(prompt_inputs, state, flows)

    # ------------------------------------------------------------- 规则兜底
    @staticmethod
    def _fallback_plan(
        prompt_inputs: dict[str, Any],
        state: DialogueState,
        flows: FlowsList,
    ) -> TurnPlan:
        """模型不可用时的关键词兜底。

        能力肯定不如模型，但足以让"查订单 / 查物流 / 退款 / 转人工"这几条主链路跑通，
        也让这个项目在没有 API Key 的机器上依然可以演示。
        """
        text = str(prompt_inputs.get("user_message") or "")
        lowered = text.lower()

        def has(*words: str) -> bool:
            return any(word in lowered for word in words)

        # 先判断撤销类，避免"不要退款了"被识别成退款
        if state.active_task is not None and has("取消", "算了", "不用了", "别弄了"):
            from app.task.commands import CancelFlowCommand

            return TurnPlan(task=TaskTurnPlan(commands=[CancelFlowCommand(command="cancel_flow")]))

        flow_keywords: list[tuple[str, tuple[str, ...]]] = [
            ("human_handoff", ("人工", "转客服", "真人")),
            ("logistics_tracking", ("物流", "快递", "到哪", "运单", "签收")),
            ("refund_request", ("退款", "退钱", "退一下")),
            ("shipping_urge", ("催发货", "催一下", "快点发货", "还没发货", "尽快发货")),
            ("similar_product_recommendation", ("推荐", "类似", "相似", "同款")),
            ("order_status_query", ("订单", "状态", "买了什么", "发货了吗")),
        ]
        for flow_id, keywords in flow_keywords:
            if has(*keywords) and flows.get_flow_by_id(flow_id) is not None:
                return TurnPlan(
                    task=TaskTurnPlan(
                        commands=[StartFlowCommand(command="start_flow", flow=flow_id)]
                    )
                )

        knowledge_keywords: list[tuple[str, tuple[str, ...]]] = [
            ("refund_policy", ("退款多久", "退款到账", "退款时效", "怎么退")),
            ("return_policy", ("七天", "无理由", "退货", "退换")),
            ("shipping_policy", ("运费", "包邮", "配送", "多久发货", "发货时效")),
            ("platform_rule", ("发票", "价保", "优惠券", "积分", "会员")),
        ]
        for intent_id, keywords in knowledge_keywords:
            if has(*keywords):
                return TurnPlan(knowledge=KnowledgeTurnPlan(intents=[intent_id]))

        if has("你好", "在吗", "hi", "hello", "谢谢", "你是谁"):
            return TurnPlan(chitchat=ChitchatTurnPlan())

        return TurnPlan()
