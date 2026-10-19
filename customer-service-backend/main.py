#!/usr/bin/env python3
"""电商小二 · 智能客服后端启动入口。

    python main.py
"""
from __future__ import annotations

import uvicorn
from app.config import settings


def main() -> None:
    print("正在启动 电商小二 · 智能客服后端")
    print(f"  接口地址: http://{settings.app_host}:{settings.app_port}")
    print(f"  接口文档: http://{settings.app_host}:{settings.app_port}/docs")
    print(f"  中台服务: {settings.commerce_api_base_url}")

    uvicorn.run(
        "app.app:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
