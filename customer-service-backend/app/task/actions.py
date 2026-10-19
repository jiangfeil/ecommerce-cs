"""Action：flow 里真正"干活"的节点。

内置两类：
  1. 通用动作  action_response（发消息）、action_listen（停下等用户）
  2. 业务动作  action_lookup_order_status / action_lookup_logistics /
               action_submit_refund / action_urge_shipping /
               action_recommend_similar_products

新增业务能力只需要继承 Action、实现 run()、在 build_action_runner() 里注册，
flow 配置里写 action 名字即可，不用改执行引擎。
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.domain.messages import BotMessage
from app.domain.state import DialogueState
from app.infrastructure.commerce_client import (
    CommerceApiError,
    CommerceClient,
    get_commerce_client,
)
from app.infrastructure.history import HistoryBuilder
from app.infrastructure.llm import LLMError, get_llm
from app.infrastructure.prompts import load_prompt, render


@dataclass
class ActionResult:
    messages: list[BotMessage] = field(default_factory=list)
    slot_updates: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionCall:
    action_name: str
    action_kwargs: dict[str, Any] = field(default_factory=dict)


class Action(ABC):
    name: str

    @abstractmethod
    async def run(
        self,
        state: DialogueState,
        action_kwargs: dict[str, Any],
    ) -> ActionResult:
        raise NotImplementedError


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, Action] = {}

    def register(self, action: Action) -> None:
        self._actions[action.name] = action

    def get(self, name: str) -> Action:
        if name not in self._actions:
            raise KeyError(f"Unknown action '{name}'.")
        return self._actions[name]

    @property
    def names(self) -> list[str]:
        return sorted(self._actions)


class ActionRunner:
    def __init__(self, registry: ActionRegistry) -> None:
        self.registry = registry

    async def run(self, action_call: ActionCall, state: DialogueState) -> ActionResult:
        action = self.registry.get(action_call.action_name)
        return await action.run(state, action_call.action_kwargs)


# --------------------------------------------------------------------------
# 渲染上下文
# --------------------------------------------------------------------------
def build_render_variables(state: DialogueState) -> dict[str, Any]:
    """flow 模板里能用的变量：slots 和 context。"""
    from dataclasses import asdict

    slots = dict(state.active_task.slots) if state.active_task else {}
    context: dict[str, Any] = {}
    system_flow = state.active_system_flow
    if system_flow is not None:
        context = {k: v for k, v in asdict(system_flow).items() if k != "kind"}
    return {"slots": slots, "context": context}


# --------------------------------------------------------------------------
# 通用动作
# --------------------------------------------------------------------------
class ActionResponse(Action):
    """发一条客服回复。

    mode:
      static   只渲染 text，不调模型（最快、最可控）
      rephrase 先渲染 text，再让模型改写得更自然
      generate 直接让模型根据 prompt 生成
    """

    name = "action_response"

    async def run(
        self,
        state: DialogueState,
        action_kwargs: dict[str, Any],
    ) -> ActionResult:
        args = action_kwargs or {}
        mode = str(args.get("mode") or "static")
        text_template = args.get("text") or ""
        prompt_template = args.get("prompt")

        variables = build_render_variables(state)
        current_response = (
            render(text_template, variables) if isinstance(text_template, str) else ""
        )

        user_message = (
            HistoryBuilder.render_user_message(state.pending_turn.input_message)
            if state.pending_turn
            else ""
        )
        history = HistoryBuilder.build(state.recent_turns(settings.history_turns))

        if mode == "generate":
            result = await self._generate(
                prompt_template, user_message=user_message, history=history
            )
        elif mode == "rephrase":
            result = await self._rephrase(
                current_response,
                prompt_template=prompt_template,
                user_message=user_message,
                history=history,
            )
        else:
            result = current_response

        result = (result or "").strip()
        if not result:
            return ActionResult()
        return ActionResult(messages=[BotMessage(text=result)])

    @staticmethod
    async def _rephrase(
        current_response: str,
        prompt_template: str | None,
        user_message: str,
        history: str,
    ) -> str:
        """让模型润色；模型不可用就退回原文，保证对话不中断。"""
        llm = get_llm()
        if not llm.available:
            return current_response

        variables = {
            "current_response": current_response,
            "user_message": user_message,
            "history": history,
        }
        try:
            if prompt_template:
                prompt = render(prompt_template, variables)
            else:
                prompt = render(load_prompt("action_rephrase"), variables)
            return await llm.complete(prompt)
        except LLMError:
            return current_response

    @staticmethod
    async def _generate(
        prompt_template: str | None,
        user_message: str,
        history: str,
    ) -> str:
        llm = get_llm()
        variables = {"user_message": user_message, "history": history}
        template = prompt_template or load_prompt("action_generate")
        prompt = render(template, variables)
        if not llm.available:
            return ""
        try:
            return await llm.complete(prompt)
        except LLMError:
            return ""


class ActionListen(Action):
    """什么都不做，表示"该等用户说话了"。"""

    name = "action_listen"

    async def run(
        self,
        state: DialogueState,
        action_kwargs: dict[str, Any],
    ) -> ActionResult:
        return ActionResult()


# --------------------------------------------------------------------------
# 业务动作
# --------------------------------------------------------------------------
class _CommerceAction(Action):
    async def _client(self) -> CommerceClient:
        return get_commerce_client()

    @staticmethod
    def _slot(state: DialogueState, name: str) -> str:
        if state.active_task is None:
            return ""
        return str(state.active_task.slots.get(name) or "").strip()

    @staticmethod
    def _focused_id(state: DialogueState) -> str:
        return state.focused_object.id if state.focused_object else ""

    @staticmethod
    def _missing_order_number() -> ActionResult:
        return ActionResult(
            messages=[BotMessage(text="我这边还没有拿到订单号，麻烦你再提供一下。")]
        )


class _CommerceWriteAction(_CommerceAction):
    """写操作类业务动作的公共骨架（退款、催发货）。

    这类动作除了"调哪个接口、认哪些错误码"之外流程完全一样：
      取槽位 → 调接口 → 按状态码翻译成人话 → 成功写回槽位。
    公共部分收敛在这里，子类只声明差异：label / ok_slot / message_slot /
    retry_hint，以及 _call()、_http_error()、_success_slots() 三个钩子。
    """

    label: str
    ok_slot: str
    message_slot: str
    retry_hint: str = ""

    async def run(
        self,
        state: DialogueState,
        action_kwargs: dict[str, Any],
    ) -> ActionResult:
        order_number = self._slot(state, "order_number")
        try:
            data = await self._call(state, order_number, action_kwargs)
        except CommerceApiError as exc:
            custom = self._http_error(exc, order_number)
            if custom:
                return self._failed(custom)
            detail = exc.detail or "接口异常"
            return self._failed(f"{self.label}暂时没有提交成功：{detail}。{self.retry_hint}")
        except Exception as exc:  # noqa: BLE001
            return self._failed(f"{self.label}暂时没有提交成功：{exc}。")

        if not data:
            return self._failed(f"{self.label}暂时没有提交成功，请稍后再试。")

        slots = {self.ok_slot: True}
        slots.update(self._success_slots(data))
        return ActionResult(slot_updates=slots)

    def _failed(self, message: str) -> ActionResult:
        return ActionResult(slot_updates={self.ok_slot: False, self.message_slot: message})

    async def _call(
        self,
        state: DialogueState,
        order_number: str,
        action_kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    def _http_error(self, exc: CommerceApiError, order_number: str) -> str | None:
        return None

    def _success_slots(self, data: dict[str, Any]) -> dict[str, Any]:
        return {}



class ActionLookupOrderStatus(_CommerceAction):
    name = "action_lookup_order_status"

    async def run(
        self,
        state: DialogueState,
        action_kwargs: dict[str, Any],
    ) -> ActionResult:
        order_number = self._slot(state, "order_number")
        if not order_number:
            return self._missing_order_number()

        client = await self._client()
        data = await client.get_order_status(order_number)
        if not data:
            return ActionResult(
                messages=[BotMessage(text=f"没有查到订单 {order_number}，你确认一下订单号是否正确？")],
                slot_updates={"order_status": "未查到", "order_summary": ""},
            )

        status = str(data.get("status") or "")
        status_desc = str(data.get("status_desc") or "")
        return ActionResult(
            slot_updates={"order_status": status, "order_summary": status_desc}
        )


class ActionLookupLogistics(_CommerceAction):
    name = "action_lookup_logistics"

    async def run(
        self,
        state: DialogueState,
        action_kwargs: dict[str, Any],
    ) -> ActionResult:
        order_number = self._slot(state, "order_number")
        if not order_number:
            return self._missing_order_number()

        client = await self._client()
        data = await client.get_logistics(order_number)
        if not data:
            return ActionResult(
                messages=[BotMessage(text=f"订单 {order_number} 暂时还没有物流信息。")],
                slot_updates={
                    "tracking_number": "",
                    "logistics_company": "",
                    "logistics_status": "暂无物流信息",
                },
            )

        traces = data.get("traces") or []
        latest = traces[0].get("desc") if traces else ""
        status_desc = str(data.get("status_desc") or data.get("status") or "")
        progress = latest or status_desc
        if latest and status_desc and latest != status_desc:
            progress = f"{status_desc}（最新：{latest}）"

        return ActionResult(
            slot_updates={
                "tracking_number": str(data.get("tracking_number") or ""),
                "logistics_company": str(data.get("logistics_company") or ""),
                "logistics_status": progress,
            }
        )


class ActionSubmitRefund(_CommerceWriteAction):
    """真正调用中台接口提交退款申请，形成业务闭环。

    中台对"已存在进行中的退款申请"返回 409，
    这里把它翻译成用户能理解的话，而不是把 HTTP 报错抛给用户。
    """

    name = "action_submit_refund"
    label = "退款申请"
    ok_slot = "refund_ok"
    message_slot = "refund_message"
    retry_hint = "稍后再试或联系人工客服。"

    async def _call(
        self,
        state: DialogueState,
        order_number: str,
        action_kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        reason = self._slot(state, "refund_reason") or "用户未说明原因"
        client = await self._client()
        return await client.apply_refund(
            order_number,
            reason,
            submitted_by=state.sender_id or "system",
        )

    def _http_error(self, exc: CommerceApiError, order_number: str) -> str | None:
        if exc.status_code == 409:
            return (
                f"订单 {order_number} 已经有一笔进行中的退款申请了，不用重复提交。"
                "审核结果会同步到订单详情，你可以过一会儿再看。"
            )
        return None

    def _success_slots(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "refund_status": str(data.get("status") or "已提交"),
            "refund_id": str(data.get("request_id") or ""),
            "refund_status_desc": str(data.get("status_desc") or ""),
        }


class ActionUrgeShipping(_CommerceWriteAction):
    """催发货。中台只允许"待发货/待揽收"的订单催发货，其余返回 400。"""

    name = "action_urge_shipping"
    label = "催发货"
    ok_slot = "urge_ok"
    message_slot = "urge_message"

    async def _call(
        self,
        state: DialogueState,
        order_number: str,
        action_kwargs: dict[str, Any],
    ) -> dict[str, Any] | None:
        client = await self._client()
        return await client.urge_shipping(
            order_number,
            submitted_by=state.sender_id or "system",
            note=str(action_kwargs.get("note") or "用户希望尽快发货"),
        )

    def _http_error(self, exc: CommerceApiError, order_number: str) -> str | None:
        if exc.status_code == 400:
            return exc.detail or f"订单 {order_number} 当前状态不支持催发货。"
        return None

    def _success_slots(self, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "urge_status": str(data.get("status") or "已提交"),
            "urge_status_desc": str(data.get("status_desc") or ""),
        }


class ActionRecommendSimilarProducts(_CommerceAction):
    """相似商品推荐。

    中台没有专门的"相似推荐"接口，这里用价格区间 + 属性重合度做一个轻量近似，
    重点是演示"业务动作如何读取参数、调用接口、把结果转成话术"。
    """

    name = "action_recommend_similar_products"

    async def run(
        self,
        state: DialogueState,
        action_kwargs: dict[str, Any],
    ) -> ActionResult:
        product_id = self._slot(state, "product_id") or self._focused_id(state)
        if not product_id:
            return ActionResult(
                messages=[BotMessage(text="你还没选商品，先选一个商品我再帮你推荐。")]
            )

        client = await self._client()
        product, catalog = await asyncio.gather(
            client.get_product(product_id),
            client.get_user_products(settings.demo_user_id),
        )
        if not product:
            return ActionResult(
                messages=[BotMessage(text=f"没有找到商品 {product_id}。")]
            )

        price = float(product.get("price") or 0)
        candidates = [
            item
            for item in (catalog or {}).get("products", [])
            if item.get("product_id") != product_id
        ]
        candidates.sort(key=lambda item: abs(float(item.get("price") or 0) - price))
        picked = candidates[:3]

        if not picked:
            return ActionResult(
                messages=[BotMessage(text=f"和「{product.get('title')}」相似的同类商品暂时没有货了。")]
            )

        lines = [
            f"{index}. {item.get('title')}（¥{item.get('price')}）"
            for index, item in enumerate(picked, start=1)
        ]
        text = (
            f"和「{product.get('title')}」比较接近的有这几款：\n"
            + "\n".join(lines)
            + "\n需要我把其中某一款的详细信息发给你吗？"
        )
        return ActionResult(messages=[BotMessage(text=text)])


# --------------------------------------------------------------------------
# 组装
# --------------------------------------------------------------------------
def build_action_runner() -> ActionRunner:
    registry = ActionRegistry()
    registry.register(ActionResponse())
    registry.register(ActionListen())
    registry.register(ActionLookupOrderStatus())
    registry.register(ActionLookupLogistics())
    registry.register(ActionSubmitRefund())
    registry.register(ActionUrgeShipping())
    registry.register(ActionRecommendSimilarProducts())
    return ActionRunner(registry)
