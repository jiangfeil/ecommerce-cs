"""一个不依赖第三方库的中文检索器。

为什么不用向量库？
  这个项目的重点是"对话编排"，知识检索只要能在几十条 FAQ / 几篇规则文档里
  找到最相关的那几条就够了。为此引入 embedding 服务会让离线运行变复杂。

实现要点：
  1. 中文没有空格分词，按 **字符 bigram** 切，比单字更能表达词序
  2. 用 IDF 给区分度高的 bigram 加权（"退货"比"的"重要）
  3. 余弦相似度排序，取 top_k

这套东西在千级文档内完全够用；要升级成向量检索，
只需要替换 KnowledgeProvider 的实现，上层完全不用改。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

_PUNCT = re.compile(r"[\s，。！？、；：\"'（）()【】\[\]{}<>《》,.!?;:\-—_/\\|*#`~]+")


def normalize(text: str) -> str:
    return _PUNCT.sub("", (text or "").lower())


def ngrams(text: str, n: int = 2) -> list[str]:
    clean = normalize(text)
    if not clean:
        return []
    if len(clean) <= n:
        return [clean]
    return [clean[i : i + n] for i in range(len(clean) - n + 1)]


@dataclass
class TextIndex:
    documents: list[str] = field(default_factory=list)
    _vectors: list[Counter[str]] = field(default_factory=list, repr=False)
    _idf: dict[str, float] = field(default_factory=dict, repr=False)
    _norms: list[float] = field(default_factory=list, repr=False)

    def build(self) -> TextIndex:
        self._vectors = [Counter(ngrams(doc)) for doc in self.documents]
        total = len(self._vectors) or 1

        df: Counter[str] = Counter()
        for vector in self._vectors:
            df.update(set(vector))
        self._idf = {
            term: math.log((total + 1) / (freq + 0.5)) + 1.0 for term, freq in df.items()
        }

        self._norms = []
        for vector in self._vectors:
            norm = math.sqrt(sum((count * self._weight(term)) ** 2 for term, count in vector.items()))
            self._norms.append(norm or 1.0)
        return self

    def _weight(self, term: str) -> float:
        return self._idf.get(term, 1.0)

    def search(self, query: str, top_k: int = 3, min_score: float = 0.05) -> list[tuple[int, float]]:
        if not self.documents:
            return []
        query_vector = Counter(ngrams(query))
        if not query_vector:
            return []

        query_norm = math.sqrt(
            sum((count * self._weight(term)) ** 2 for term, count in query_vector.items())
        ) or 1.0

        scored: list[tuple[int, float]] = []
        for index, vector in enumerate(self._vectors):
            dot = sum(
                count * vector.get(term, 0) * (self._weight(term) ** 2)
                for term, count in query_vector.items()
            )
            if dot <= 0:
                continue
            scored.append((index, dot / (query_norm * self._norms[index])))

        scored.sort(key=lambda item: item[1], reverse=True)
        return [(index, score) for index, score in scored[:top_k] if score >= min_score]


def split_chunks(text: str, max_chars: int = 420) -> list[str]:
    """按空行/标题切块，过长再按句子切。"""
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    chunks: list[str] = []
    for block in blocks:
        if len(block) <= max_chars:
            chunks.append(block)
            continue
        buffer = ""
        for sentence in re.split(r"(?<=[。！？\n])", block):
            if len(buffer) + len(sentence) > max_chars and buffer:
                chunks.append(buffer.strip())
                buffer = ""
            buffer += sentence
        if buffer.strip():
            chunks.append(buffer.strip())
    return chunks
