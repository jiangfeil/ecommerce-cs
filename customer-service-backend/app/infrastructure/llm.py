"""大模型访问层。

全项目只有这里知道"模型是哪家的、怎么调"。
上层组件（TurnPlanner / 各个 Responder）只调用 `get_llm()`，
因此把 Qwen 换成别的模型、或者换成 mock，只要改这一个文件。

同时提供一个重要能力：**可用性探测与降级**。
如果 Key 没配、网络不通、模型报错，`available` 会是 False，
上层可以据此走规则兜底，而不是让整条对话链路直接 500。
"""
from __future__ import annotations

import json
import re
from typing import Any

from openai import AsyncOpenAI

from app.config import settings


class LLMError(RuntimeError):
    """模型调用失败。"""


def _strip_code_fence(text: str) -> str:
    """模型有时不听话，会给 JSON 套一层 ```json，这里兜底剥掉。"""
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        return fence.group(1).strip()
    return text


class LLMClient:
    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str,
        temperature: float = 0.3,
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self._api_key = (api_key or "").strip()
        self._client = (
            AsyncOpenAI(api_key=self._api_key, base_url=base_url, timeout=timeout)
            if self._api_key
            else None
        )
        self.last_error: str | None = None

    @property
    def available(self) -> bool:
        return self._client is not None

    async def complete(self, prompt: str, system: str | None = None) -> str:
        """最基础的一次补全。"""
        if self._client is None:
            raise LLMError("LLM_API_KEY 未配置")

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=self.temperature,
            )
        except Exception as exc:  # noqa: BLE001 - 统一收敛成 LLMError
            self.last_error = str(exc)
            raise LLMError(str(exc)) from exc

        content = (response.choices[0].message.content or "").strip()
        if not content:
            raise LLMError("模型返回空内容")
        return content

    async def complete_json(self, prompt: str, system: str | None = None) -> dict[str, Any]:
        """要求模型输出 JSON，并解析成字典。"""
        raw = await self.complete(prompt, system=system)
        cleaned = _strip_code_fence(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            self.last_error = f"JSON 解析失败: {raw[:200]}"
            raise LLMError(self.last_error) from exc
        if not isinstance(data, dict):
            raise LLMError(f"模型输出的不是一个 JSON 对象: {cleaned[:200]}")
        return data


_llm: LLMClient | None = None


def build_llm() -> LLMClient:
    return LLMClient(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout,
    )


def init_llm() -> LLMClient:
    global _llm
    _llm = build_llm()
    return _llm


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = build_llm()
    return _llm
