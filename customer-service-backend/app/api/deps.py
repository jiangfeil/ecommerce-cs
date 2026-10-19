"""依赖注入装配。

FastAPI 的 Depends 让"每个请求该拿到什么对象"变成声明式的：
接口函数只写下自己要什么，不关心怎么造出来、什么时候销毁。
"""
from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.engine.builder import build_dialogue_engine
from app.engine.dialogue_engine import DialogueEngine
from app.repositories.dialogue_state_repository import DialogueStateRepository
from app.services.dialogue_service import DialogueService

# 引擎是无状态的（状态都在 DialogueState 里），进程内单例即可，
# 不必每个请求重建一遍 flow、索引和 LLM 客户端。
_dialogue_engine: DialogueEngine | None = None


def init_dialogue_engine() -> DialogueEngine:
    global _dialogue_engine
    _dialogue_engine = build_dialogue_engine()
    return _dialogue_engine


def get_engine() -> DialogueEngine:
    if _dialogue_engine is None:
        return init_dialogue_engine()
    return _dialogue_engine


async def get_repository(
    db: AsyncSession = Depends(get_db),
) -> DialogueStateRepository:
    return DialogueStateRepository(db)


async def get_dialogue_service(
    engine: DialogueEngine = Depends(get_engine),
    repository: DialogueStateRepository = Depends(get_repository),
) -> DialogueService:
    return DialogueService(
        dialogue_state_repository=repository,
        dialogue_engine=engine,
    )
