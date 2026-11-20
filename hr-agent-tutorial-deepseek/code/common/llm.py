"""旧版 LLM 适配层（原理示意用）。

> 新代码请使用 `common.lc.MockChatModel` / `get_chat_model()`，它们是 LangChain 原生
> `BaseChatModel`，可直接接入 `create_agent`、`StateGraph`、Callback。
> 这个文件保留给章节正文中的“原理示意（旧版手写实现）”，不再作为 demo 的主实现。

为什么要适配层？
- 教程默认不花钱、不联网也能跑：MockLLM 按脚本返回固定的工具调用。
- 想接真实模型时只改环境变量，Agent 循环、工具、RAG 代码一行都不用动。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .text import estimate_tokens, messages_tokens


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"call_{uuid.uuid4().hex[:8]}")

    def to_openai(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }

    @classmethod
    def from_openai(cls, raw: dict) -> "ToolCall":
        function = raw.get("function") or raw
        arguments = function.get("arguments") or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                arguments = {"_raw": arguments}
        return cls(
            name=function.get("name", ""),
            arguments=arguments if isinstance(arguments, dict) else {"value": arguments},
            id=raw.get("id") or f"call_{uuid.uuid4().hex[:8]}",
        )


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = "mock"
    raw: dict | None = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def __str__(self) -> str:
        return self.content or ""


class BaseLLM:
    model = "base"

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        raise NotImplementedError


class MockLLM(BaseLLM):
    """按脚本逐条返回的假模型，用来做确定性演示与测试。

    脚本元素可以是：
      {"content": "你好"}                                  -> 纯文本回答
      {"tool_calls": [{"name": "get_leave_balance",
                       "arguments": {"employee_id": "E1001"}}]}  -> 发起工具调用
    也可以传一个函数：fn(messages, tools) -> dict，实现按输入动态决策。
    """

    def __init__(self, script: list[dict] | dict | Callable | None = None, model: str = "mock-hr"):
        if script is None:
            script = [{"content": "（MockLLM 未配置脚本：这是离线演示模式）"}]
        if isinstance(script, dict):
            script = [script]
        self.script = script
        self.model = model
        self.calls: list[dict] = []
        self.index = 0

    def reset(self) -> None:
        self.index = 0
        self.calls.clear()

    def _next(self, messages: list[dict], tools: list[dict] | None) -> dict:
        if callable(self.script):
            return self.script(messages, tools) or {"content": ""}
        if self.index < len(self.script):
            item = dict(self.script[self.index])
            self.index += 1
            return item
        return {"content": "（演示脚本已结束。真实模型会在这里继续推理。）"}

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, "response_format": response_format})
        item = self._next(messages, tools)
        content = item.get("content")
        tool_calls = [ToolCall.from_openai(call) for call in item.get("tool_calls", [])]
        completion_text = content or ""
        completion_text += json.dumps([call.to_openai() for call in tool_calls], ensure_ascii=False)
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=Usage(messages_tokens(messages), estimate_tokens(completion_text)),
            model=self.model,
            raw=item,
        )


class OpenAICompatLLM(BaseLLM):
    """调用 OpenAI 风格的 /chat/completions 接口。

    已验证的兼容服务：OpenAI、DeepSeek、Qwen(DashScope compatible-mode)、GLM、Ollama、vLLM。
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 60,
    ):
        self.model = model or os.getenv("HR_LLM_MODEL", "gpt-4o-mini")
        self.api_key = api_key or os.getenv("HR_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        self.base_url = (base_url or os.getenv("HR_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise RuntimeError("缺少 API Key：请设置 HR_LLM_API_KEY 或 OPENAI_API_KEY，或使用 MockLLM。")

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if response_format:
            payload["response_format"] = response_format

        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"LLM 接口返回 {exc.code}: {body}") from exc

        message = data["choices"][0]["message"]
        usage = data.get("usage") or {}
        return LLMResponse(
            content=message.get("content"),
            tool_calls=[ToolCall.from_openai(call) for call in message.get("tool_calls") or []],
            usage=Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)),
            model=data.get("model", self.model),
            raw=data,
        )


def get_llm(
    script: list[dict] | dict | Callable | None = None,
    model: str | None = None,
    mode: str | None = None,
) -> BaseLLM:
    """根据环境变量选择 Mock 或真实模型。

    HR_LLM_MODE=mock   强制离线
    HR_LLM_MODE=openai 强制真实（需要 Key）
    未设置时：有 Key 就用真实模型，没有就用 Mock。
    """
    mode = (mode or os.getenv("HR_LLM_MODE") or "auto").lower()
    has_key = bool(os.getenv("HR_LLM_API_KEY") or os.getenv("OPENAI_API_KEY"))
    if mode == "openai" or (mode == "auto" and has_key):
        return OpenAICompatLLM(model=model)
    return MockLLM(script, model=model or "mock-hr")


def system(content: str) -> dict:
    return {"role": "system", "content": content}


def user(content: str) -> dict:
    return {"role": "user", "content": content}


def assistant(content: str | None = None, tool_calls: list[ToolCall] | None = None) -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = [call.to_openai() for call in tool_calls]
    return message


def tool_message(call: ToolCall, content: Any) -> dict:
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": content}


def tool_schema(
    name: str,
    description: str,
    properties: dict[str, dict],
    required: list[str] | None = None,
) -> dict:
    """生成 OpenAI Function Calling 的工具描述。"""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }
