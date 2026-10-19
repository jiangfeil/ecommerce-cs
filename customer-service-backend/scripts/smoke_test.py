#!/usr/bin/env python3
"""端到端冒烟测试：用真实 HTTP 请求跑一遍客服主要链路。

用法（先启动中台 18081 和客服 18082）：
    python scripts/smoke_test.py
    python scripts/smoke_test.py --sender u_test_01
"""
from __future__ import annotations

import argparse
import sys
import uuid

import httpx

BASE_URL = "http://127.0.0.1:18082"

# 每一组是「一段连续对话」，组间换一个 sender_id，互不干扰
SCENARIOS: list[tuple[str, list[str]]] = [
    (
        "① 闲聊 + 身份",
        ["你好", "你是谁"],
    ),
    (
        "② 查订单状态（槽位收集）",
        ["帮我查一下订单状态", "A20260410001"],
    ),
    (
        "③ 查物流",
        ["我想查物流", "A20260408002"],
    ),
    (
        "④ 知识问答（规则/政策）",
        ["退款多久能到账", "七天无理由怎么算", "运费怎么收"],
    ),
    (
        "⑤ 退款申请（真实落库）",
        ["我要申请退款", "A20260410001", "不想要了，买错了"],
    ),
    (
        "⑥ 催发货",
        ["帮我催一下发货", "A20260407004"],
    ),
    (
        "⑦ 对象消息（点订单卡片）",
        [],
    ),
]


def chat(client: httpx.Client, sender_id: str, text: str | None = None, obj: dict | None = None) -> str:
    payload: dict = {"sender_id": sender_id, "message_id": f"m_{uuid.uuid4().hex[:8]}"}
    if text is not None:
        payload["text"] = text
    if obj is not None:
        payload["object"] = obj

    response = client.post(f"{BASE_URL}/api/chat", json=payload)
    response.raise_for_status()
    data = response.json()
    return "\n".join("   BOT> " + m.get("text", "") for m in data.get("messages", []))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sender", default=f"smoke_{uuid.uuid4().hex[:6]}")
    args = parser.parse_args()

    try:
        health = httpx.get(f"{BASE_URL}/health", timeout=5, trust_env=False).json()
    except Exception as exc:  # noqa: BLE001
        print(f"客服后端不可达: {exc}")
        return 1

    print("=" * 72)
    print(f"客服后端: {BASE_URL}  模型: {health['llm_model']}  可用: {health['llm_available']}")
    print("=" * 72)

    with httpx.Client(timeout=120, trust_env=False) as client:
        for index, (title, messages) in enumerate(SCENARIOS, start=1):
            sender_id = f"{args.sender}_{index}"
            print(f"\n【{title}】 sender={sender_id}")
            if not messages:
                # 对象消息：模拟前端点击订单卡片
                order = {
                    "type": "order",
                    "id": "A20260410001",
                    "title": "iPhone 15 Pro 256G 远峰蓝",
                    "attributes": {"status": "待发货"},
                }
                print("   USER> [点击订单卡片] A20260410001")
                print(chat(client, sender_id, obj=order))
                continue

            for text in messages:
                print(f"   USER> {text}")
                try:
                    print(chat(client, sender_id, text=text))
                except Exception as exc:  # noqa: BLE001
                    print(f"   ERROR> {exc}")

        # 历史接口
        history = client.get(f"{BASE_URL}/api/chat/history", params={"sender_id": f"{args.sender}_2"})
        history.raise_for_status()
        messages = history.json().get("messages", [])
        print("\n【历史接口】 GET /api/chat/history")
        print(f"   返回 {len(messages)} 条消息")
        for item in messages[:4]:
            print(f"   {item['role']:>4}: {item['text'][:60]}")

    print("\n完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
