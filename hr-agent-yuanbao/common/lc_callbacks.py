"""LangChain 可观测层：用 BaseCallbackHandler 把框架内部事件翻译成统一 Trace。

第 14 章手写 Tracer，这里换成 LangChain 官方回调接口：
  on_chat_model_start / on_llm_end   → LLM 调用与 Token
  on_tool_start / on_tool_end        → 工具调用
  on_retriever_start / on_retriever_end → 检索
  on_chain_start / on_chain_error    → 图节点与异常

回调收集到的 steps 与第 0.5 节的统一契约完全一致，前端不用改一行。
生产里把这个 handler 换成 LangfuseCallbackHandler / LangSmith 的 tracer 即可。
"""
from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from .context import Step


def _short(value: Any, n: int = 160) -> str:
    s = str(value)
    return s if len(s) <= n else s[:n] + "…"


class TraceCallbackHandler(BaseCallbackHandler):
    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.metrics: dict[str, Any] = {
            "llm_calls": 0, "tool_calls": 0, "retriever_calls": 0,
            "tokens_est": 0, "errors": 0, "node_events": 0,
        }
        self.node_path: list[str] = []
        self._starts: dict[str, float] = {}

    def _add(self, type_: str, content: str, **meta: Any) -> None:
        self.steps.append(asdict(Step(type=type_, content=content, meta=meta)))

    # ---- 模型 ----
    def on_chat_model_start(self, serialized: dict, messages: list,
                            *, run_id, **kwargs: Any) -> None:
        self.metrics["llm_calls"] += 1
        self._starts[str(run_id)] = time.perf_counter()
        last = ""
        if messages:
            for msg_list in messages[:1]:
                last = _short(getattr(msg_list[-1], "content", ""), 120) if msg_list else ""
        self._add("llm", "LangChain ChatModel 调用", model=(serialized or {}).get("name", "chat_model"),
                  last_message=last)

    def on_llm_end(self, response: Any, *, run_id, **kwargs: Any) -> None:
        dt = round((time.perf_counter() - self._starts.pop(str(run_id), time.perf_counter())) * 1000, 2)
        text = ""
        try:
            gen = response.generations[0][0]
            text = _short(getattr(gen, "text", "") or getattr(getattr(gen, "message", None), "content", ""), 140)
            calls = getattr(getattr(gen, "message", None), "tool_calls", None)
            if calls:
                text = "tool_calls → " + ", ".join(c.get("name", "?") for c in calls)
        except Exception:
            pass
        self.metrics["tokens_est"] += len(text)
        self._add("observation", f"LLM 返回（{dt} ms）：{text or '（空）'}", ms=dt)

    # ---- 工具 ----
    def on_tool_start(self, serialized: dict, input_str: str, *, run_id, **kwargs: Any) -> None:
        self.metrics["tool_calls"] += 1
        self._add("tool", f"ToolNode 执行 {_short((serialized or {}).get('name', 'tool'), 60)}",
                  args=_short(input_str, 200))

    def on_tool_end(self, output: str, *, run_id, **kwargs: Any) -> None:
        self._add("observation", f"工具返回：{_short(output, 220)}")

    def on_tool_error(self, error: BaseException, *, run_id, **kwargs: Any) -> None:
        self.metrics["errors"] += 1
        self._add("error", f"工具异常：{_short(error, 160)}")

    # ---- 检索 ----
    def on_retriever_start(self, serialized: dict, query: str, *, run_id, **kwargs: Any) -> None:
        self.metrics["retriever_calls"] += 1
        self._add("retrieve", f"混合检索器召回：{_short(query, 100)}")

    def on_retriever_end(self, documents: list, *, run_id, **kwargs: Any) -> None:
        self._add("observation", f"检索返回 {len(documents)} 个 Document（带版本与引用编号）",
                  count=len(documents),
                  sources=[d.metadata.get("sources") for d in documents[:3]])

    # ---- 图 / 链 ----
    def on_chain_start(self, serialized: dict, inputs: dict, *, run_id, **kwargs: Any) -> None:
        name = (serialized or {}).get("name", "") if serialized else ""
        metadata = kwargs.get("metadata") or {}
        node = metadata.get("langgraph_node") or name
        if node and node not in {"LangGraph", "RunnableSequence", "RunnableLambda"}:
            self.metrics["node_events"] += 1
            if not self.node_path or self.node_path[-1] != node:
                self.node_path.append(node)
            self._add("state", f"进入 LangGraph 节点：{node}", node=node)

    def on_chain_error(self, error: BaseException, *, run_id, **kwargs: Any) -> None:
        self.metrics["errors"] += 1
        self._add("error", f"链路异常：{_short(error, 160)}")
