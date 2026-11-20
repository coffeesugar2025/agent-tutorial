from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from common.data import all_policy_documents, employee, employees
from common.llm import MockLLM, ToolCall, assistant, tool_message, user
from common.text import chunk_markdown, estimate_tokens, mask_pii, truncate_tokens
from common.trace import Tracer


def test_data_loads() -> None:
    assert len(employees()) >= 12
    assert employee("E1001")["name"] == "张伟"
    docs = all_policy_documents()
    assert len(docs) >= 8
    assert all(doc["content"].strip() for doc in docs)


def test_token_estimate_and_truncate() -> None:
    assert estimate_tokens("你好 world") > 0
    text = "年假" * 1000
    shortened = truncate_tokens(text, 100)
    assert estimate_tokens(shortened) <= 105


def test_chunk_markdown() -> None:
    doc = next(doc for doc in all_policy_documents() if doc["doc_id"] == "leave-2025")
    chunks = chunk_markdown(doc["content"], max_chars=300)
    assert len(chunks) >= 3
    assert any("3 月 31 日" in chunk["text"] for chunk in chunks)


def test_mock_llm_tool_flow() -> None:
    llm = MockLLM(
        [
            {"tool_calls": [{"name": "get_leave_balance", "arguments": {"employee_id": "E1001"}}]},
            {"content": "你还有 13 天年假。"},
        ]
    )
    messages = [user("我还有几天年假？")]
    first = llm.chat(messages, tools=[])
    assert first.tool_calls[0].name == "get_leave_balance"
    messages.append(assistant(first.content, first.tool_calls))
    messages.append(tool_message(first.tool_calls[0], {"annual_remaining": 13}))
    second = llm.chat(messages, tools=[])
    assert "13" in (second.content or "")
    assert second.usage.total_tokens > 0


def test_tracer_summary() -> None:
    tracer = Tracer("test")
    with tracer.span("llm"):
        tracer.event("start")
    summary = tracer.summary()
    assert summary["trace_id"]
    assert summary["spans"][0]["name"] == "test"
    assert summary["spans"][1]["name"] == "llm"


def test_mask_pii() -> None:
    masked = mask_pii("电话 13800001001 邮箱 zhangwei@acme.example")
    assert "13800001001" not in masked
    assert "zhangwei@acme.example" not in masked
