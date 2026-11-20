"""LangChain 公共工具箱：15 章共用的框架构建块。

教程里每一章都只依赖这一层 + common/context.py，不自己发明编排结构：
  - ChatModel      BaseChatModel（ChatOllama / TeachingChatModel）
  - Tools          @tool → bind_tools → ToolNode
  - Retriever      BaseRetriever（InMemoryVectorStore + 三路 RRF）
  - Graph          StateGraph + MemorySaver + InMemoryStore + interrupt
  - StructuredOut  PydanticOutputParser / with_structured_output
  - Context        trim_messages / ChatPromptTemplate / LCEL Runnable
  - Trace          BaseCallbackHandler → 统一 steps[] 契约
  - Guardrails     Runnable.with_retry / with_fallbacks / 超时 / 幂等
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, trim_messages
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

from .context import Context
from .lc_callbacks import TraceCallbackHandler

CHECKPOINTER = MemorySaver()
STORE = InMemoryStore()


def callback(ctx: Context) -> TraceCallbackHandler:
    """每章一个回调实例：把框架内部事件翻译成统一 Trace。"""
    return TraceCallbackHandler()


def config(thread_id: str, cb: TraceCallbackHandler | None = None,
           *, recursion_limit: int = 24) -> dict:
    cfg: dict[str, Any] = {"configurable": {"thread_id": thread_id},
                           "recursion_limit": recursion_limit}
    if cb:
        cfg["callbacks"] = [cb]
    return cfg


def token_counter(x: Any) -> int:
    """trim_messages 的 token_counter：教学用字符估算，生产换 tiktoken。"""
    ms = x if isinstance(x, list) else [x]
    return sum(max(1, len(str(getattr(m, "content", ""))) // 2) for m in ms)


def trim(messages: list, budget: int, keep_recent: int = 2) -> list:
    """LangChain trim_messages：滚动窗口 + 预算裁剪，P0 系统消息不进裁剪列表。"""
    return trim_messages(messages, max_tokens=max(40, budget), strategy="last",
                         token_counter=token_counter, include_system=False,
                         allow_partial=False) or messages[-keep_recent:]


def prompt_chain(ctx: Context, template: str, role: str = "compose",
                 *, parser: PydanticOutputParser | None = None):
    """LCEL 链：ChatPromptTemplate | ChatModel | (OutputParser)。

    这是全书反复出现的最小单元：`|` 管道符就是 LangChain 的 RunnableSequence。
    """
    msgs = [("system", template)]
    if parser:
        msgs[0] = ("system", template + "\n\n{format_instructions}")
    p = ChatPromptTemplate.from_messages(msgs + [("human", "{input}")])
    if parser:
        p = p.partial(format_instructions=parser.get_format_instructions())
    chain = p | ctx.chat_model(role)
    return chain | parser if parser else chain


def invoke(chain, inputs: dict, cfg: dict, ctx: Context, *, label: str = "LCEL 链") -> Any:
    """统一调用入口：LangChain 的 invoke 一律带 config，让回调能采集 Trace。"""
    try:
        return chain.invoke(inputs, config=cfg)
    except Exception as exc:
        ctx.bump("errors")
        ctx.trace("error", f"{label} 调用失败：{exc}")
        raise


def finish(ctx: Context, cb: TraceCallbackHandler, answer: str, *,
           state: dict | None = None, hitl: dict | None = None,
           extra_steps: list[dict] | None = None) -> dict:
    """合并「节点手写 Trace」+「LangChain 回调 Trace」，按时间排序后统一交付。"""
    steps = [asdict(s) for s in ctx.steps] + [dict(s) for s in cb.steps]
    steps += [dict(s) for s in (extra_steps or [])]
    steps.sort(key=lambda s: s.get("ts", ""))
    for k in ("llm_calls", "tool_calls", "retriever_calls", "tokens_est",
              "errors", "node_events"):
        ctx.metrics[k] = ctx.metrics.get(k, 0) + cb.metrics.get(k, 0)
    result = ctx.result(answer, state=state or {}, hitl=hitl)
    result["steps"] = steps
    return result


def seed_store() -> None:
    """预置长期 / 用户记忆（InMemoryStore 是 LangGraph 的跨会话存储）。"""
    pairs = [
        (("user", "E1001"), "interview_pref", {"value": "偏好上午 9:00–10:00 面试", "importance": 0.9}),
        (("user", "E1001"), "health", {"value": "对海鲜过敏，接待订餐需避开", "importance": 0.85}),
        (("user", "E1001"), "noise", {"value": "上一轮随口提到的数字 42", "importance": 0.1}),
        (("long", "org"), "calibration", {"value": "2026-10 产品部绩效校准会结论：晋升名额 2 个", "importance": 0.8}),
    ]
    for ns, key, value in pairs:
        if not STORE.get(ns, key):
            STORE.put(ns, key, value)


def ctx_message(payload: dict) -> SystemMessage:
    """把结构化上下文塞进一条 SystemMessage，供 LangChain 模型读取。"""
    return SystemMessage(content="HR_CTX:" + json.dumps(payload, ensure_ascii=False))


def short(value: Any, n: int = 180) -> str:
    s = str(value)
    return s if len(s) <= n else s[:n] + "…"
