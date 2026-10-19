"""TurnPlanValidator：六种"为什么不能执行"的判定。

这个模块是"模型负责理解、代码负责执行"这条设计的分界线，
所以每一种拒绝理由都值得钉住，避免以后改提示词时悄悄退化。
"""
from __future__ import annotations

import pytest
from app.domain.messages import FocusedObject
from app.domain.state import DialogueState
from app.knowledge.intents import KnowledgeIntent
from app.planning.turn_plan import (
    ChitchatTurnPlan,
    KnowledgeTurnPlan,
    TaskTurnPlan,
    TurnPlan,
)
from app.planning.validator import ClarifyReason, TurnPlanValidator
from app.task.commands import StartFlowCommand

INTENTS = {
    "refund_policy": KnowledgeIntent(id="refund_policy", description="退款政策"),
    "product_info": KnowledgeIntent(
        id="product_info", description="商品咨询", provider_ids=["api.product"], requires_object="product"
    ),
}


@pytest.fixture
def validator() -> TurnPlanValidator:
    return TurnPlanValidator()


@pytest.fixture
def state() -> DialogueState:
    return DialogueState(sender_id="u_test")


def test_empty_plan_asks_for_clarification(validator, state):
    result = validator.validate(TurnPlan(), state, INTENTS)

    assert result.valid is False
    assert result.reason is ClarifyReason.MISSING_TRACK


def test_two_tracks_at_once_is_rejected(validator, state):
    plan = TurnPlan(
        task=TaskTurnPlan(commands=[StartFlowCommand(command="start_flow", flow="refund_request")]),
        knowledge=KnowledgeTurnPlan(intents=["refund_policy"]),
    )

    result = validator.validate(plan, state, INTENTS)

    assert result.valid is False
    assert result.reason is ClarifyReason.MULTIPLE_TRACKS


def test_task_without_commands_is_rejected(validator, state):
    result = validator.validate(TurnPlan(task=TaskTurnPlan(commands=[])), state, INTENTS)

    assert result.valid is False
    assert result.reason is ClarifyReason.MISSING_TASK_COMMANDS


def test_task_with_command_is_valid(validator, state):
    plan = TurnPlan(
        task=TaskTurnPlan(commands=[StartFlowCommand(command="start_flow", flow="refund_request")])
    )

    assert validator.validate(plan, state, INTENTS).valid is True


def test_chitchat_alone_is_valid(validator, state):
    assert validator.validate(TurnPlan(chitchat=ChitchatTurnPlan()), state, INTENTS).valid is True


def test_knowledge_without_intent_is_rejected(validator, state):
    result = validator.validate(TurnPlan(knowledge=KnowledgeTurnPlan(intents=[])), state, INTENTS)

    assert result.valid is False
    assert result.reason is ClarifyReason.MISSING_KNOWLEDGE_INTENT


def test_unknown_intent_from_model_is_treated_as_misunderstood(validator, state):
    """模型编了一个不存在的意图，不能让流程空转。"""
    result = validator.validate(
        TurnPlan(knowledge=KnowledgeTurnPlan(intents=["不存在的意图"])), state, INTENTS
    )

    assert result.valid is False
    assert result.reason is ClarifyReason.MISSING_KNOWLEDGE_INTENT


def test_intent_requiring_object_without_focus_is_rejected(validator, state):
    result = validator.validate(
        TurnPlan(knowledge=KnowledgeTurnPlan(intents=["product_info"])), state, INTENTS
    )

    assert result.valid is False
    assert result.reason is ClarifyReason.MISSING_FOCUSED_OBJECT


def test_intent_requiring_object_with_wrong_focus_type_is_rejected(validator, state):
    state.focused_object = FocusedObject(type="order", id="A20260410001")

    result = validator.validate(
        TurnPlan(knowledge=KnowledgeTurnPlan(intents=["product_info"])), state, INTENTS
    )

    assert result.valid is False
    assert result.reason is ClarifyReason.MISSING_FOCUSED_OBJECT


def test_intent_with_matching_focus_object_is_valid(validator, state):
    state.focused_object = FocusedObject(type="product", id="P1001")

    result = validator.validate(
        TurnPlan(knowledge=KnowledgeTurnPlan(intents=["product_info"])), state, INTENTS
    )

    assert result.valid is True
