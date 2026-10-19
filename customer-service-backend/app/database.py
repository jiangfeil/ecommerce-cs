from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings


class Base(DeclarativeBase):
    pass


class DialogueStateRecord(Base):
    """对话状态持久化表：一个用户一行，整份状态以 JSON 存放。

    之所以整份存 JSON 而不是拆成多张表，是因为 DialogueState
    本质上是一棵会频繁整体读写的运行时上下文树（任务、槽位、
    挂起任务、聚焦对象、会话历史），拆表会带来大量无意义的
    关联查询，而按 sender_id 整存取反而最贴合它的使用方式。
    """

    __tablename__ = "dialogue_states"

    sender_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_pre_ping=True,
)

session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    await engine.dispose()


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
