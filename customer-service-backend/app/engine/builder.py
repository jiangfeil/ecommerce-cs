"""组装整个对话引擎。

这是唯一知道"有哪些组件、怎么拼起来"的地方。
DialogueEngine 只接收组装好的依赖，自己不 new 任何东西。
换一个 Provider、换一个 Action，都只改这个文件。
"""
from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.engine.dialogue_engine import DialogueEngine
from app.handlers.chitchat_handler import ChitchatHandler, ChitchatResponder
from app.handlers.knowledge_handler import KnowledgeHandler
from app.handlers.task_handler import TaskHandler
from app.knowledge.intents import KNOWLEDGE_INTENTS
from app.knowledge.providers import (
    FaqKnowledgeProvider,
    OrderApiProvider,
    ProductApiProvider,
    RagKnowledgeProvider,
)
from app.knowledge.registry import KnowledgeProviderRegistry
from app.knowledge.responder import KnowledgeResponder
from app.planning.clarify_responder import ClarifyResponder
from app.planning.turn_planner import TurnPlanner
from app.planning.validator import TurnPlanValidator
from app.task.actions import build_action_runner
from app.task.command_processor import CommandProcessor
from app.task.flow_executor import FlowExecutor
from app.task.flow_loader import FlowLoader

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FLOW_CONFIG_DIR = PROJECT_ROOT / "flow_config"
FLOW_CONFIG_FILES = ("user_flows.yml", "system_flows.yml")


def build_flow_list():
    paths = [FLOW_CONFIG_DIR / name for name in FLOW_CONFIG_FILES]
    return FlowLoader().load_many(paths)


def build_dialogue_engine() -> DialogueEngine:
    flows = build_flow_list()

    task_handler = TaskHandler(
        flows=flows,
        command_processor=CommandProcessor(),
        flow_executor=FlowExecutor(),
        action_runner=build_action_runner(),
        max_steps=settings.max_flow_steps,
    )

    knowledge_handler = KnowledgeHandler(
        knowledge_intents=KNOWLEDGE_INTENTS,
        responder=KnowledgeResponder(),
        registry=KnowledgeProviderRegistry(
            [
                ProductApiProvider(),
                OrderApiProvider(),
                FaqKnowledgeProvider(),
                RagKnowledgeProvider(),
            ]
        ),
    )

    return DialogueEngine(
        turn_planner=TurnPlanner(),
        task_handler=task_handler,
        knowledge_handler=knowledge_handler,
        chitchat_handler=ChitchatHandler(responder=ChitchatResponder()),
        clarify_responder=ClarifyResponder(),
        turn_plan_validator=TurnPlanValidator(),
    )
