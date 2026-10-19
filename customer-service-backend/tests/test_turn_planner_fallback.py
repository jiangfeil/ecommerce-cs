"""TurnPlanner 的关键词兜底。

这是"没有 API Key 也能演示"的保底能力，也是模型超时时的降级路径，
所以它的映射关系值得钉死——改了关键词，测试会告诉你哪条主链路断了。
"""
from __future__ import annotations

from app.domain.state import DialogueState, TaskContext
from app.planning.turn_planner import TurnPlanner
from app.task.commands import CancelFlowCommand, StartFlowCommand


def _fallback(message: str, flows, state: DialogueState | None = None):
    state = state or DialogueState(sender_id="u_test")
    return TurnPlanner._fallback_plan({"user_message": message}, state, flows)


def test_maps_to_task_flow(flows):
    plan = _fallback("我想申请退款", flows)

    assert plan.task is not None
    command = plan.task.commands[0]
    assert isinstance(command, StartFlowCommand)
    assert command.flow == "refund_request"


def test_logistics_keyword_wins_over_order_keyword(flows):
    """「物流」比「订单」更具体，应该优先命中物流流程。"""
    plan = _fallback("我那个订单的物流到哪了", flows)

    assert plan.task.commands[0].flow == "logistics_tracking"


def test_maps_to_knowledge_intent(flows):
    plan = _fallback("运费怎么收", flows)

    assert plan.task is None
    assert plan.knowledge is not None
    assert plan.knowledge.intents == ["shipping_policy"]


def test_maps_to_chitchat(flows):
    plan = _fallback("你好", flows)

    assert plan.task is None
    assert plan.knowledge is None
    assert plan.chitchat is not None


def test_cancel_has_priority_over_new_intent(flows):
    """「不要退款了」不能被识别成"又要退款一次"。"""
    state = DialogueState(
        sender_id="u_test", active_task=TaskContext(flow_id="refund_request")
    )

    plan = _fallback("算了不要退款了", flows, state)

    assert plan.task is not None
    assert isinstance(plan.task.commands[0], CancelFlowCommand)


def test_cancel_only_applies_when_task_is_active(flows):
    plan = _fallback("算了不用了", flows)

    assert plan.task is None, "没有进行中的任务时，取消类话术不该开新流程"


def test_unknown_message_yields_empty_plan(flows):
    plan = _fallback("今天天气不错", flows)

    assert plan.task is None
    assert plan.knowledge is None
    assert plan.chitchat is None


def test_flow_keyword_is_ignored_when_flow_not_configured(flows):
    """配置里没这个 flow 时，不能返回一个指向空流程的计划。"""
    from app.task.flow_models import FlowsList

    plan = _fallback("我想催发货", FlowsList(flows=[], slots={}))

    assert plan.task is None
