"""LangChain 1.x 公共适配层。

全书所有 demo 都基于 LangChain / LangGraph 编写：
- 模型：`BaseChatModel`（离线用 `MockChatModel`，真实模型用 `ChatOpenAI`）
- 工具：`@tool` / `BaseTool` / `StructuredTool`
- 编排：`create_agent`、`StateGraph`、`ToolNode`、checkpointer
- 提示词：`ChatPromptTemplate`、`MessagesPlaceholder`
- 检索：`RecursiveCharacterTextSplitter`、`InMemoryVectorStore`、`BM25Retriever`

这个文件只做两件事：让离线 Mock 模型符合 LangChain 接口；统一真实模型的创建方式。
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Sequence

from langchain.agents import create_agent
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from pydantic import Field

from .text import estimate_tokens, messages_tokens


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return "" if content is None else str(content)


class MockChatModel(BaseChatModel):
    """按脚本返回的 LangChain ChatModel。

    脚本元素：
      {"content": "最终回答"}
      {"tool_calls": [{"name": "get_leave_balance", "args": {"employee_id": "E1001"}}]}
    也可以是函数：fn(messages, tools) -> dict。
    """

    script: Any = Field(default_factory=list)
    index: int = 0
    model_name: str = "mock-hr"
    calls: list[dict] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "mock-hr"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable:
        # Mock 不真正理解 tools，只记录；真实模型会在这里绑定 schema。
        return self.bind(tools=tools, **kwargs)

    def _next(self, messages: list[BaseMessage], tools: Any) -> dict:
        if callable(self.script):
            return self.script(messages, tools) or {"content": ""}
        if self.index < len(self.script):
            item = dict(self.script[self.index])
            self.index += 1
            return item
        return {"content": "（演示脚本已结束。真实模型会在这里继续推理。）"}

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        tools = kwargs.get("tools")
        item = self._next(messages, tools)
        content = item.get("content", "")
        tool_calls = []
        for raw in item.get("tool_calls", []):
            tool_calls.append(
                {
                    "name": raw["name"],
                    "args": raw.get("args", raw.get("arguments", {})),
                    "id": raw.get("id", f"call_{self.index}"),
                    "type": "tool_call",
                }
            )
        prompt_tokens = messages_tokens(
            [{"role": "user", "content": _content_text(message.content)} for message in messages]
        )
        completion_tokens = estimate_tokens(content) + estimate_tokens(json.dumps(tool_calls, ensure_ascii=False))
        message = AIMessage(
            content=content,
            tool_calls=tool_calls,
            usage_metadata={
                "input_tokens": prompt_tokens,
                "output_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            response_metadata={"model_name": self.model_name},
        )
        self.calls.append({"messages": messages, "tools": tools, "response": message})
        return ChatResult(generations=[ChatGeneration(message=message)])


def get_chat_model(script: Any = None, model: str | None = None, temperature: float = 0.0) -> BaseChatModel:
    """有 Key 用真实 OpenAI 兼容模型，否则用离线 Mock。"""
    api_key = "sk-ddfe7280bbbd47ba965a42b584b01aac"
    if api_key:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model or os.getenv("HR_LLM_MODEL", "deepseek-flash"),
            api_key=api_key,
            base_url="https://api.deepseek.com",
            temperature=temperature,
        )
    return MockChatModel(script=script or [], model_name=model or "mock-hr")


def run_agent(
    tools: Sequence[Any],
    messages: list[BaseMessage],
    script: Any = None,
    system_prompt: str | None = None,
    max_steps: int = 8,
    model: BaseChatModel | None = None,
) -> dict:
    """用 LangChain 1.x 的 create_agent 跑一次 Agent，返回最终 state。"""
    agent = create_agent(
        model=model or get_chat_model(script=script),
        tools=list(tools),
        system_prompt=system_prompt,
    )
    return agent.invoke(
        {"messages": messages},
        config={"recursion_limit": max(2 * max_steps + 2, 6)},
    )


def final_text(state: dict) -> str:
    messages = state.get("messages", [])
    if not messages:
        return ""
    return _content_text(messages[-1].content)


def tool_names(state: dict) -> list[str]:
    names = []
    for message in state.get("messages", []):
        if isinstance(message, AIMessage):
            names.extend(call["name"] for call in message.tool_calls)
    return names


class TracerCallbackHandler(BaseCallbackHandler):
    """把 LangChain 的 LLM/工具回调汇总成一个小报告。"""

    def __init__(self) -> None:
        self.llm_calls = 0
        self.tool_calls = 0
        self.tool_errors = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.tools: list[str] = []
        self.events: list[dict] = []

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        self.llm_calls += 1
        for generation_list in getattr(response, "generations", []) or []:
            for generation in generation_list:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None) or {}
                self.prompt_tokens += usage.get("input_tokens", 0)
                self.completion_tokens += usage.get("output_tokens", 0)
        self.events.append({"event": "llm_end", "calls": self.llm_calls})

    def on_tool_start(self, serialized: dict, input_str: str, **kwargs: Any) -> None:
        self.tool_calls += 1
        name = serialized.get("name", "tool")
        self.tools.append(name)
        self.events.append({"event": "tool_start", "tool": name, "input": input_str[:120]})

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        self.events.append({"event": "tool_end", "output": str(output)[:120]})

    def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        self.tool_errors += 1
        self.events.append({"event": "tool_error", "error": repr(error)})

    def summary(self) -> dict:
        return {
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "tools": list(self.tools),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
        }


__all__ = [
    "MockChatModel",
    "TracerCallbackHandler",
    "final_text",
    "get_chat_model",
    "run_agent",
    "tool_names",
]
