from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """客服后端配置。全部可通过 .env 覆盖。"""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ===== 大模型 =====
    llm_model: str = "qwen-plus"
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_api_key: str = ""
    llm_temperature: float = 0.3
    llm_timeout: float = 60.0

    # ===== 下游电商业务服务 =====
    commerce_api_base_url: str = "http://127.0.0.1:18081"
    commerce_api_timeout: float = 10.0

    # ===== 数据库：默认 SQLite，零安装；改 DATABASE_URL 即可切 MySQL =====
    database_url: str = "sqlite+aiosqlite:///./customer_service.db"
    database_echo: bool = False

    # ===== 服务监听 =====
    app_host: str = "127.0.0.1"
    app_port: int = 18082

    # ===== 对话行为 =====
    # 会话空闲多久后开启新会话（秒），默认 1 小时
    session_timeout_seconds: int = 60 * 60
    # 单轮最多推进多少个 flow step，防止配置写错导致死循环
    max_flow_steps: int = 1000
    # 提示词里带多少轮历史
    history_turns: int = 10
    # 演示用用户 ID（中台只有 3 个用户，商品推荐等场景需要它）
    demo_user_id: str = "u1001"
    # 流式输出（前端未使用，保留开关）
    stream: bool = False


settings = Settings()
