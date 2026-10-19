"""FlowExecutor：流程推进的四个关键行为。

用真实的 flow_config 来测，而不是造假的 Flow 对象——这样配置改坏了测试会先报错，
而不是等线上跑起来才发现。
"""
from __future__ import annotations

import pytest
from app.domain.state import DialogueState, TaskContext
from app.domain.system_contexts import CollectSystemContext
from app.task.flow_executor import FlowExecutor


def _state(**kwargs) -> DialogueState:
    return DialogueState(sender_id="u_test", **kwargs)


# --------------------------------------------------------------- 条件跳转
def test_refund_flow_takes_success_branch(flows):
    state = _state(
        active_task=TaskContext(
            flow_id="refund_request",
            step_id="check_refund_result",
            slots={
                "order_number": "A20260410001",
                "refund_id": "R001",
                "refund_status": "submitted",
                "refund_reason": "买错了",
                "refund_ok": True,
            },
        )
    )

    call = FlowExecutor().advance_until_action(state, flows)

    assert call.action_name == "action_response"
    assert "退款单号R001" in call.action_kwargs["text"]


def test_refund_flow_takes_failure_branch(flows):
    state = _state(
        active_task=TaskContext(
            flow_id="refund_request",
            step_id="check_refund_result",
            slots={"order_number": "A20260410001", "refund_ok": False, "refund_message": "提交失败了"},
        )
    )

    call = FlowExecutor().advance_until_action(state, flows)

    assert call.action_name == "action_response"
    assert call.action_kwargs["text"] == "提交失败了"


# --------------------------------------------------------- 收集槽位 / 系统流程
def test_collect_step_activates_system_flow_and_asks(flows):
    state = _state(active_task=TaskContext(flow_id="refund_request", step_id="start"))

    call = FlowExecutor().advance_until_action(state, flows)

    assert call.action_name == "action_response"
    assert call.action_kwargs["text"] == "请告诉我你的订单号。"
    assert isinstance(state.active_system_flow, CollectSystemContext)
    assert state.active_system_flow.slot_name == "order_number"


def test_system_flow_self_heals_when_slot_already_filled(flows):
    """用户用别的方式把槽位填上了，询问流程必须自己收掉，否则会一直卡在同一个问题。"""
    state = _state(
        active_task=TaskContext(
            flow_id="refund_request",
            step_id="ask_order_number",
            slots={"order_number": "A20260410001"},
        )
    )
    state.activate_system_flow(
        CollectSystemContext(slot_name="order_number", response={"text": "请告诉我你的订单号。"})
    )

    call = FlowExecutor().advance_until_action(state, flows)

    # 自愈后应当跳过订单号，直接问退款原因
    assert call.action_kwargs["text"] == "请简单说一下退款原因。"
    assert isinstance(state.active_system_flow, CollectSystemContext)
    assert state.active_system_flow.slot_name == "refund_reason"


# ------------------------------------------------------------------ 异常兜底
def test_unknown_step_id_finishes_context_instead_of_looping(flows):
    state = _state(active_task=TaskContext(flow_id="refund_request", step_id="不存在的步骤"))

    call = FlowExecutor().advance_until_action(state, flows)

    assert call.action_name == "action_listen"
    assert state.active_task is None, "配置指向不存在的 step 时应安全收尾"


def test_no_active_context_means_listen(flows):
    call = FlowExecutor().advance_until_action(_state(), flows)

    assert call.action_name == "action_listen"


# ------------------------------------------------------------- 表达式求值沙箱
@pytest.mark.parametrize(
    ("condition", "variables", "expected"),
    [
        ("slots.get('refund_ok')", {"slots": {"refund_ok": True}}, True),
        ("slots.get('refund_ok')", {"slots": {"refund_ok": False}}, False),
        ("len(slots) == 0", {"slots": {}}, True),
        ("1 / 0", {}, False),
        ("__import__('os').system('echo hacked')", {}, False),
        ("unknown_name", {}, False),
    ],
)
def test_condition_eval_is_sandboxed(condition, variables, expected):
    assert FlowExecutor._eval(condition, variables) is expected
