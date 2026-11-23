"""切块单元测试：清洗、递归切分、重叠、父子块与统计。"""

from __future__ import annotations

import pytest

from app.rag.chunker import Chunk, chunk_document, chunk_stats, clean_text, split_recursive

pytestmark = pytest.mark.unit


def test_clean_text_normalizes_whitespace_and_control_chars():
    raw = "第一行\r\n第二行\x00\u3000结尾   \n\n\n\n第三段"
    cleaned = clean_text(raw)

    assert "\r" not in cleaned
    assert "\x00" not in cleaned
    assert "\n\n\n" not in cleaned
    assert cleaned.startswith("第一行")
    assert cleaned.endswith("第三段")


def test_empty_document_returns_no_chunks():
    assert chunk_document("   \n\n\t ") == []


def test_chunks_respect_size_boundary_and_keep_order():
    text = "。".join(f"这是第{i}句关于退货运费与退款时效的说明" for i in range(30)) + "。"
    chunks = chunk_document(text, size=60, overlap=10, parent_size=300)

    assert len(chunks) > 1
    assert all(isinstance(chunk, Chunk) for chunk in chunks)
    assert all(len(chunk.content) <= 60 + 10 for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.token_count > 0 for chunk in chunks)


def test_overlap_prepends_previous_tail():
    text = "。".join(f"第{i}段内容用于验证重叠逻辑是否生效" for i in range(12)) + "。"
    chunks = chunk_document(text, size=40, overlap=8, parent_size=400)

    assert len(chunks) >= 2
    assert chunks[1].content.startswith(chunks[0].content[-8:])
    # 重叠只是回填上下文，不会让块首尾颠倒
    assert chunks[0].content != chunks[1].content


def test_parent_content_contains_child_and_is_bounded():
    text = "\n\n".join(f"第{i}段说明：退货运费由买家承担。" for i in range(8))
    chunks = chunk_document(text, size=50, overlap=0, parent_size=200)

    assert chunks
    for chunk in chunks:
        assert chunk.content.strip() in chunk.parent_content
        assert len(chunk.parent_content) <= 200


def test_split_recursive_hard_splits_without_separators():
    pieces = split_recursive("x" * 250, 100, separators=("\n",))

    assert len(pieces) == 3
    assert all(len(piece) <= 100 for piece in pieces)
    assert "".join(pieces) == "x" * 250


def test_chunk_stats_reports_aggregates():
    chunks = chunk_document("你好。世界。这是一个测试文档。", size=20, overlap=0, parent_size=100)
    stats = chunk_stats(chunks)

    assert stats["count"] == len(chunks)
    assert stats["avgChars"] > 0
    assert stats["maxChars"] >= stats["minChars"] > 0
    assert stats["avgTokens"] > 0
    assert chunk_stats([])["count"] == 0
