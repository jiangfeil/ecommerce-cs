"""业务动作的行为契约。

重点覆盖"接口报错怎么翻译成人话"——
这块以前散在两个动作各自的 try/except 里，现在收敛在 _CommerceWriteAction，
所以用测试把它钉住，保证重构前后话术一字不差。
"""
from __future__ import annotations

import pytest
from app.domain.state import DialogueState, TaskContext
from app.infrastructure.commerce_client import CommerceApiError
from app.task import actions as actions_module
from app.task.actions import ActionSubmitRefund, ActionUrgeShipping


class _FakeClient:
    """只实现被测动作用到的方法；出错就抛传进来的异常。"""

    def __init__(self, *, result=None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls: list[dict] = []

    async def apply_refund(self, order_number, reason, submitted_by):
        self.calls.append(
            {"order_number": order_number, "reason": reason, "submitted_by": submitted_by}
        )
        if self._error:
            raise self._error
        return self._result

    async def urge_shipping(self, order_number, submitted_by, note):
        self.calls.append({"order_number": order_number, "submitted_by": submitted_by, "note": note})
        if self._error:
            raise self._error
        return self._result


@pytest.fixture
def state() -> DialogueState:
    return DialogueState(
        sender_id="u_test",
        active_task=TaskContext(
            flow_id="refund_request",
            slots={"order_number": "A20260410001", "refund_reason": "买错了"},
        ),
    )


def _use(monkeypatch, client: _FakeClient) -> _FakeClient:
    monkeypatch.setattr(actions_module, "get_commerce_client", lambda: client)
    return client


# ------------------------------------------------------------------ 退款成功
async def test_refund_success_writes_all_slots(state, monkeypatch):
    client = _use(
        monkeypatch,
        _FakeClient(result={"request_id": "R123", "status": "submitted", "status_desc": "审核中"}),
    )

    result = await ActionSubmitRefund().run(state, {})

    assert result.messages == []
    assert result.slot_updates == {
        "refund_ok": True,
        "refund_status": "submitted",
        "refund_id": "R123",
        "refund_status_desc": "审核中",
    }
    assert client.calls[0]["order_number"] == "A20260410001"
    assert client.calls[0]["reason"] == "买错了"
    assert client.calls[0]["submitted_by"] == "u_test"


async def test_refund_without_reason_uses_placeholder(state, monkeypatch):
    state.active_task.slots.pop("refund_reason")
    client = _use(monkeypatch, _FakeClient(result={"request_id": "R1"}))

    await ActionSubmitRefund().run(state, {})

    assert client.calls[0]["reason"] == "用户未说明原因"


# ------------------------------------------------------------ 退款失败的各种姿势
async def test_refund_conflict_409_is_translated(state, monkeypatch):
    _use(monkeypatch, _FakeClient(error=CommerceApiError("conflict", status_code=409, detail="dup")))

    result = await ActionSubmitRefund().run(state, {})

    assert result.slot_updates["refund_ok"] is False
    message = result.slot_updates["refund_message"]
    assert "已经有一笔进行中的退款申请" in message
    assert "不用重复提交" in message


async def test_refund_server_error_keeps_detail_and_retry_hint(state, monkeypatch):
    _use(monkeypatch, _FakeClient(error=CommerceApiError("boom", status_code=500, detail="服务开小差")))

    result = await ActionSubmitRefund().run(state, {})

    assert result.slot_updates["refund_message"] == (
        "退款申请暂时没有提交成功：服务开小差。稍后再试或联系人工客服。"
    )


async def test_refund_unexpected_exception_is_swallowed(state, monkeypatch):
    _use(monkeypatch, _FakeClient(error=RuntimeError("连接超时")))

    result = await ActionSubmitRefund().run(state, {})

    assert result.slot_updates["refund_ok"] is False
    assert result.slot_updates["refund_message"] == "退款申请暂时没有提交成功：连接超时。"


async def test_refund_empty_response_is_treated_as_failure(state, monkeypatch):
    _use(monkeypatch, _FakeClient(result=None))

    result = await ActionSubmitRefund().run(state, {})

    assert result.slot_updates["refund_message"] == "退款申请暂时没有提交成功，请稍后再试。"


# ------------------------------------------------------------------ 催发货
async def test_urge_success_writes_slots(state, monkeypatch):
    _use(monkeypatch, _FakeClient(result={"status": "submitted", "status_desc": "已通知商家"}))

    result = await ActionUrgeShipping().run(state, {})

    assert result.slot_updates == {
        "urge_ok": True,
        "urge_status": "submitted",
        "urge_status_desc": "已通知商家",
    }


async def test_urge_400_uses_server_detail(state, monkeypatch):
    _use(
        monkeypatch,
        _FakeClient(error=CommerceApiError("bad", status_code=400, detail="运输中的订单不能催发货")),
    )

    result = await ActionUrgeShipping().run(state, {})

    assert result.slot_updates["urge_ok"] is False
    assert result.slot_updates["urge_message"] == "运输中的订单不能催发货"


async def test_urge_400_without_detail_falls_back_to_generic_wording(state, monkeypatch):
    _use(monkeypatch, _FakeClient(error=CommerceApiError("bad", status_code=400, detail="")))

    result = await ActionUrgeShipping().run(state, {})

    assert result.slot_updates["urge_message"] == "订单 A20260410001 当前状态不支持催发货。"


async def test_urge_server_error_has_no_retry_hint(state, monkeypatch):
    """催发货的兜底话术和退款不同：不追加"联系人工客服"。"""
    _use(monkeypatch, _FakeClient(error=CommerceApiError("boom", status_code=500, detail="接口异常")))

    result = await ActionUrgeShipping().run(state, {})

    assert result.slot_updates["urge_message"] == "催发货暂时没有提交成功：接口异常。"
