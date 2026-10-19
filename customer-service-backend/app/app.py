from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.deps import init_dialogue_engine
from app.config import settings
from app.database import close_db, init_db
from app.infrastructure.commerce_client import close_commerce_client, init_commerce_client
from app.infrastructure.llm import init_llm

logger = logging.getLogger("customer-service")

openapi_tags = [
    {"name": "对话", "description": "发送消息、拉取历史对话。"},
    {"name": "系统", "description": "服务可用性检查。"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时把"贵"的东西一次性建好，关闭时统一释放。

    - LLM 客户端：连接池复用
    - 中台 HTTP 客户端：连接池复用
    - 对话引擎：加载 flow 配置、构建知识索引
    - 数据库：建表
    """
    llm = init_llm()
    init_commerce_client()
    init_dialogue_engine()
    await init_db()

    logger.info("客服后端已启动 http://%s:%s", settings.app_host, settings.app_port)
    logger.info("模型: %s | 可用: %s", settings.llm_model, llm.available)
    logger.info("中台地址: %s", settings.commerce_api_base_url)
    if not llm.available:
        logger.warning("LLM_API_KEY 未配置，意图识别将走规则兜底")

    yield

    await close_db()
    await close_commerce_client()


app = FastAPI(
    title="电商小二 · 智能客服后端",
    version="1.0.0",
    description=(
        "基于大模型的电商智能客服：意图规划 + 流程编排 + 知识问答三轨并行。\n\n"
        "配套模拟电商中台服务（默认 http://127.0.0.1:18081）提供订单、物流、商品数据。"
    ),
    openapi_tags=openapi_tags,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)


@app.get("/health", tags=["系统"], summary="健康检查")
async def health() -> dict[str, object]:
    from app.infrastructure.llm import get_llm

    llm = get_llm()
    return {
        "status": "ok",
        "llm_model": llm.model,
        "llm_available": llm.available,
        "commerce_api": settings.commerce_api_base_url,
    }
