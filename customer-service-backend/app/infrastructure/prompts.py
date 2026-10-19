"""提示词加载与渲染。

提示词统一放在 app/prompts/*.jinja2，改文案不用改代码。

系统里存在两种占位符风格，必须都支持：
  1. Jinja2 风格  {{ slots.order_number }}   —— flow 配置里的 text 模板
  2. format 风格  {history}                  —— flow 配置里的 prompt 模板

第二种不能用 str.format()，因为提示词里经常出现 JSON 花括号，
str.format 会把 JSON 的 { 当成占位符起始，直接抛 KeyError。
所以这里用正则精确替换“{合法标识符}”。
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, Undefined

PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"

_env = Environment(
    autoescape=False,
    # flow 模板里的 {{ slots.xxx }} 允许槽位尚未填充，
    # 未定义时渲染成空串，而不是抛异常中断整轮对话
    undefined=Undefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

_FORMAT_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


@lru_cache(maxsize=64)
def load_prompt(name: str) -> str:
    """按名字读取提示词模板，例如 load_prompt('turn_plan')。"""
    path = PROMPT_DIR / f"{name}.jinja2"
    if not path.exists():
        raise FileNotFoundError(f"提示词模板不存在: {path}")
    return path.read_text(encoding="utf-8")


def render_jinja(template: str, variables: dict[str, Any]) -> str:
    """用 Jinja2 渲染（支持 {{ }} 和 {# #}）。"""
    return _env.from_string(template).render(**variables)


def render_format(template: str, variables: dict[str, Any]) -> str:
    """只替换 {name} 形式的占位符，其余花括号原样保留。"""
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in variables:
            value = variables[key]
            return "" if value is None else str(value)
        return match.group(0)

    return _FORMAT_PATTERN.sub(_replace, template)


def render(value: Any, variables: dict[str, Any]) -> Any:
    """递归渲染 str / dict / list，flow 的 args 结构可以直接丢进来。"""
    if isinstance(value, str):
        rendered = render_jinja(value, variables) if "{{" in value or "{%" in value else value
        return render_format(rendered, variables)
    if isinstance(value, dict):
        return {k: render(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, variables) for v in value]
    return value
