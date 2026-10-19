from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _default_database_url() -> str:
    """默认使用项目内置的 SQLite，无需安装数据库即可跑通。

    想切回 MySQL，只需在 .env 里设置：
        DATABASE_URL=mysql+pymysql://root:<密码>@127.0.0.1:3306/commerce?charset=utf8mb4
    """
    return "sqlite:///" + (BASE_DIR / "commerce.db").as_posix()


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL") or _default_database_url()
    )
    app_host: str = field(default_factory=lambda: os.getenv("APP_HOST") or "127.0.0.1")
    app_port: int = field(default_factory=lambda: int(os.getenv("APP_PORT") or "18081"))


settings = Settings()
