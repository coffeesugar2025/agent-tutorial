from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_core.vectorstores import InMemoryVectorStore

from common.lc import MockChatModel, TracerCallbackHandler, final_text, run_agent, tool_names


@tool
def get_leave_balance(employee_id: str) -> str:
    """查询员工年假余额。"""
    return f"{employee_id} 年假剩余 13 天"


def test_create_agent_with_mock_model() -> None:
    state = run_agent(
        tools=[get_leave_balance],
        messages=[HumanMessage(content="我还有几天年假？")],
        script=[
            {"tool_calls": [{"name": "get_leave_balance", "args": {"employee_id": "E1001"}}]},
            {"content": "你还有 13 天年假。"},
        ],
        system_prompt="你是 HR 助手。",
    )
    assert tool_names(state) == ["get_leave_balance"]
    assert "13" in final_text(state)
    assert any(message.type == "tool" for message in state["messages"])


def test_callback_summary() -> None:
    handler = TracerCallbackHandler()
    model = MockChatModel(script=[{"content": "你好"}])
    model.invoke("你好", config={"callbacks": [handler]})
    summary = handler.summary()
    assert summary["llm_calls"] == 1
    assert summary["total_tokens"] > 0


class HashEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    @staticmethod
    def _embed(text: str) -> list[float]:
        vector = [0.0] * 32
        for char in text:
            vector[ord(char) % 32] += 1.0
        return vector


def test_in_memory_vector_store() -> None:
    store = InMemoryVectorStore(embedding=HashEmbeddings())
    store.add_documents(
        [
            Document(page_content="年假最多结转 5 天至次年 3 月 31 日", metadata={"doc_id": "leave-2025"}),
            Document(page_content="远程办公每周最多 2 天", metadata={"doc_id": "remote-2025"}),
        ]
    )
    results = store.similarity_search("年假结转", k=1)
    assert results[0].metadata["doc_id"] == "leave-2025"
