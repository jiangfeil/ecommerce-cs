"""知识来源（Provider）。

系统把"知识"分成三路，因为它们的时效性和查询方式完全不同：

  api.*   实时业务数据，必须查接口（订单状态、物流、商品价格）
  faq.*   标准问答，一问一答，命中即用
  rag.*   规则文档，需要先检索段落再交给模型组织语言

三个 Provider 都实现同一个 retrieve()，所以 KnowledgeHandler 可以对它们一视同仁。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.domain.state import DialogueState
from app.infrastructure.commerce_client import get_commerce_client
from app.knowledge.retrieval import TextIndex, split_chunks

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "knowledge_base"


@dataclass(slots=True)
class KnowledgeChunk:
    content: str
    source: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"content": self.content, "source": self.source}


class KnowledgeProvider:
    provider_id = ""

    async def retrieve(self, state: DialogueState) -> list[KnowledgeChunk]:
        return []


# --------------------------------------------------------------------------
# 实时业务数据
# --------------------------------------------------------------------------
def _focused_id(state: DialogueState, expected_type: str) -> str:
    obj = state.focused_object
    if obj is None or obj.type != expected_type:
        return ""
    return obj.id


def _current_question(state: DialogueState) -> str:
    if state.pending_turn is None:
        return ""
    return (state.pending_turn.input_message.text or "").strip()


class ProductApiProvider(KnowledgeProvider):
    provider_id = "api.product"

    async def retrieve(self, state: DialogueState) -> list[KnowledgeChunk]:
        product_id = _focused_id(state, "product")
        if not product_id:
            return []

        payload = await get_commerce_client().get_product(product_id)
        if not payload:
            return [
                KnowledgeChunk(
                    content=f"未查询到商品 {product_id} 的信息。", source="api.product"
                )
            ]
        return [
            KnowledgeChunk(
                content="商品信息：\n"
                + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
                source="api.product",
            )
        ]


class OrderApiProvider(KnowledgeProvider):
    provider_id = "api.order"

    async def retrieve(self, state: DialogueState) -> list[KnowledgeChunk]:
        order_number = _focused_id(state, "order")
        if not order_number:
            return []

        client = get_commerce_client()
        order_payload, logistics_payload = await asyncio.gather(
            client.get_order(order_number),
            client.get_logistics(order_number),
        )
        return [
            KnowledgeChunk(
                content="订单与物流信息：\n"
                + yaml.safe_dump(
                    {
                        "order_number": order_number,
                        "order": order_payload,
                        "logistics": logistics_payload,
                    },
                    allow_unicode=True,
                    sort_keys=False,
                ),
                source="api.order",
            )
        ]


# --------------------------------------------------------------------------
# 标准问答
# --------------------------------------------------------------------------
class FaqKnowledgeProvider(KnowledgeProvider):
    provider_id = "faq.default"

    def __init__(self, faq_path: Path | None = None, top_k: int = 3) -> None:
        self.faq_path = faq_path or (KNOWLEDGE_BASE_DIR / "faq.yml")
        self.top_k = top_k
        self._entries: list[dict[str, Any]] = []
        self._index: TextIndex | None = None

    def _ensure_index(self) -> None:
        if self._index is not None:
            return
        raw = yaml.safe_load(self.faq_path.read_text(encoding="utf-8")) or {}
        self._entries = list(raw.get("faqs") or [])
        documents = [
            " ".join(
                [
                    str(entry.get("question") or ""),
                    " ".join(entry.get("tags") or []),
                    str(entry.get("answer") or ""),
                ]
            )
            for entry in self._entries
        ]
        self._index = TextIndex(documents=documents).build()

    async def retrieve(self, state: DialogueState) -> list[KnowledgeChunk]:
        query = _current_question(state)
        if not query:
            return []

        self._ensure_index()
        assert self._index is not None

        chunks: list[KnowledgeChunk] = []
        for index, _score in self._index.search(query, top_k=self.top_k):
            entry = self._entries[index]
            chunks.append(
                KnowledgeChunk(
                    content=f"问：{entry.get('question')}\n答：{entry.get('answer')}",
                    source=f"faq#{index + 1}",
                )
            )
        return chunks


# --------------------------------------------------------------------------
# 规则文档检索
# --------------------------------------------------------------------------
class RagKnowledgeProvider(KnowledgeProvider):
    provider_id = "rag.default"

    def __init__(self, docs_dir: Path | None = None, top_k: int = 3) -> None:
        self.docs_dir = docs_dir or (KNOWLEDGE_BASE_DIR / "docs")
        self.top_k = top_k
        self._chunks: list[KnowledgeChunk] = []
        self._index: TextIndex | None = None

    def _ensure_index(self) -> None:
        if self._index is not None:
            return
        chunks: list[KnowledgeChunk] = []
        for path in sorted(self.docs_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            for _, piece in enumerate(split_chunks(text)):
                chunks.append(
                    KnowledgeChunk(content=piece, source=f"rag:{path.stem}")
                )
        self._chunks = chunks
        self._index = TextIndex(documents=[c.content for c in chunks]).build()

    async def retrieve(self, state: DialogueState) -> list[KnowledgeChunk]:
        query = _current_question(state)
        if not query:
            return []

        self._ensure_index()
        assert self._index is not None

        results: list[KnowledgeChunk] = []
        for index, _score in self._index.search(query, top_k=self.top_k):
            results.append(self._chunks[index])
        return results
