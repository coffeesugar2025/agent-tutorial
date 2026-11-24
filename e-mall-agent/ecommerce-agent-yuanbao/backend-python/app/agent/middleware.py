"""LangChain 1.5 自定义中间件（AgentMiddleware 是 v1 的一等扩展点）。

组合顺序：列表里越靠前越外层。
  PromptGuardMiddleware  注入攻击拦截（模型调用前短路）
  ToolAuditMiddleware    强制用户归属注入 + 参数脱敏 + 工具调用审计
  LangChain 内置中间件   调用次数上限 / 模型重试

中间件不修改业务工具本身，因此 MCP 侧保持「一次实现、多端复用」。
"""
from __future__ import annotations

import re
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelResponse,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
    ToolCallRequest,
)
from langchain_core.messages import AIMessage, ToolMessage

# 进程内环形审计日志，可由 GET /v1/audit 查看；生产环境替换为 OTel / LangSmith
AUDIT_LOG: deque[dict[str, Any]] = deque(maxlen=200)

GUARD_KEYWORDS = (
    "忽略以上规则", "忽略之前的指令", "ignore previous instructions",
    "system prompt", "泄露系统提示", "越权", "禁用工具校验",
    "不要调用工具直接回答订单", "打印你的指令",
)
GUARD_REPLY = "抱歉，这个请求试图绕过系统的工具校验规则，我不能执行。可以继续咨询商品、订单或售后问题。"

_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_IDCARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b if isinstance(b, str) else str(b.get("text", ""))
            for b in content if isinstance(b, (str, dict))
        )
    return str(content or "")


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        value = _PHONE_RE.sub("<phone>", value)
        value = _IDCARD_RE.sub("<id>", value)
        return _EMAIL_RE.sub("<email>", value)
    if isinstance(value, dict):
        return {k: _redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _accepts_user_id(tool: Any) -> bool:
    """判断该工具是否声明了 user_id 参数（用于强制注入，防止模型漏传/伪造）。"""
    schema = getattr(tool, "args_schema", None) or getattr(tool, "args", None)
    if isinstance(schema, dict):
        return "user_id" in schema or "user_id" in (schema.get("properties") or {})
    if isinstance(schema, type) and hasattr(schema, "model_fields"):
        return "user_id" in schema.model_fields
    return False


class PromptGuardMiddleware(AgentMiddleware):
    """提示词注入防护：命中关键词时直接短路，不发起模型调用。"""

    def _is_blocked(self, request: ModelRequest) -> bool:
        for m in reversed(request.messages):
            if getattr(m, "type", "") == "human":
                text = _text(getattr(m, "content", ""))
                return any(k.lower() in text.lower() for k in GUARD_KEYWORDS)
        return False

    def wrap_model_call(self, request: ModelRequest, handler: Callable[..., ModelResponse]) -> ModelResponse:
        if self._is_blocked(request):
            return ModelResponse(result=[AIMessage(content=GUARD_REPLY)])
        return handler(request)

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[..., Awaitable[ModelResponse]]
    ) -> ModelResponse:
        if self._is_blocked(request):
            return ModelResponse(result=[AIMessage(content=GUARD_REPLY)])
        return await handler(request)


class ToolAuditMiddleware(AgentMiddleware):
    """工具调用治理：归属注入、参数脱敏、全量审计、耗时统计。"""

    def __init__(self, user_id: str = "u_1001", enabled: bool = True) -> None:
        self.user_id = user_id
        self.enabled = enabled

    def _prepare(self, request: ToolCallRequest) -> ToolCallRequest:
        tc = dict(request.tool_call)
        args = dict(tc.get("args") or {})
        if _accepts_user_id(request.tool) and not args.get("user_id"):
            # 强制使用会话用户，模型不得自行指定他人 user_id
            args["user_id"] = self.user_id
            tc["args"] = args
            return request.override(tool_call=tc)
        return request

    @staticmethod
    def _record(name: str, args: dict[str, Any], started: float, status: str, error: str = "") -> None:
        AUDIT_LOG.append({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": name,
            "args": _redact(args),
            "status": status,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "error": error[:200],
        })

    def wrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[..., ToolMessage]
    ) -> ToolMessage:
        request = self._prepare(request)
        name = request.tool_call.get("name", "")
        args = dict(request.tool_call.get("args") or {})
        started = time.perf_counter()
        try:
            result = handler(request)
            self._record(name, args, started, "success")
            return result
        except Exception as exc:
            self._record(name, args, started, "error", str(exc))
            raise

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[..., Awaitable[ToolMessage]]
    ) -> ToolMessage:
        request = self._prepare(request)
        name = request.tool_call.get("name", "")
        args = dict(request.tool_call.get("args") or {})
        started = time.perf_counter()
        try:
            result = await handler(request)
            self._record(name, args, started, "success")
            return result
        except Exception as exc:
            self._record(name, args, started, "error", str(exc))
            raise


def default_middleware(user_id: str = "u_1001", max_calls: int = 8) -> list[AgentMiddleware]:
    """按外层 → 内层顺序组装；内置中间件体现 1.5 的可插拔治理能力。"""
    return [
        PromptGuardMiddleware(),
        ToolAuditMiddleware(user_id=user_id),
        ModelCallLimitMiddleware(run_limit=max_calls * 2, exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=max_calls, exit_behavior="end"),
        ModelRetryMiddleware(max_retries=1, on_failure="continue", backoff_factor=0.0),
    ]


def get_audit_log(limit: int = 50) -> list[dict[str, Any]]:
    return list(AUDIT_LOG)[-max(1, min(limit, 200)):]
