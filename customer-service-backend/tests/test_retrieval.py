"""中文检索器：分词、打分排序、切块。"""
from __future__ import annotations

from app.knowledge.retrieval import TextIndex, ngrams, normalize, split_chunks


def test_normalize_removes_punct_and_lowercases():
    assert normalize("七天无理由，怎么算？ABC") == "七天无理由怎么算abc"
    assert normalize("") == ""
    assert normalize("  ") == ""


def test_ngrams_uses_char_bigram():
    assert ngrams("退货") == ["退货"]
    # 两个字以内整体算一个 token，避免短词被切碎
    assert ngrams("退") == ["退"]
    assert ngrams("退款时效") == ["退款", "款时", "时效"]
    assert ngrams("  ") == []


def test_search_ranks_the_relevant_doc_first():
    docs = [
        "七天无理由退货从签收次日零时起算，连续七个自然日。",
        "退货运费由谁承担，要看是不是质量问题。",
        "单笔订单满 99 元包邮，未满收 8 元运费。",
    ]
    index = TextIndex(documents=docs).build()

    hits = index.search("七天无理由怎么算", top_k=2)

    assert hits, "相关文档必须能被召回"
    assert hits[0][0] == 0, "最相关的是第一条"
    assert 0 < hits[0][1] <= 1.0, "余弦相似度应落在 (0, 1]"


def test_search_returns_nothing_when_no_overlap():
    index = TextIndex(documents=["七天无理由退货"]).build()
    assert index.search("zzz") == []


def test_search_on_empty_index_is_safe():
    assert TextIndex().build().search("退款") == []
    assert TextIndex(documents=[]).search("退款") == []


def test_split_chunks_splits_on_blank_lines():
    assert split_chunks("第一段。\n\n第二段。") == ["第一段。", "第二段。"]


def test_split_chunks_splits_long_block_by_sentence():
    long_text = "这是一句用来测试切块的话。" * 60
    chunks = split_chunks(long_text, max_chars=100)

    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)
    # 不能丢内容
    assert sum(len(chunk) for chunk in chunks) >= len(long_text.strip()) - 1
