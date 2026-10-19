"""pytest 共享配置。

这里的测试只覆盖"不需要起服务、不需要联网"的纯逻辑：
意图兜底、流程推进、计划校验、检索打分、动作的错误翻译。
端到端场景仍然由 scripts/smoke_test.py 负责。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 让 tests/ 里可以直接 import app.*（pytest 默认只把 rootdir 加进 sys.path）
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.task.flow_loader import FlowLoader  # noqa: E402

FLOW_DIR = BACKEND_DIR / "flow_config"


@pytest.fixture(scope="session")
def flows():
    """加载真实的 flow 配置，测的是"配置 + 引擎"的契约，不是假数据。"""
    return FlowLoader().load_many(
        [FLOW_DIR / "user_flows.yml", FLOW_DIR / "system_flows.yml"]
    )
