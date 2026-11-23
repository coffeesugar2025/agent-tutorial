"""Agent 运行态数据结构。

设计原则：
* **纯数据**：状态对象不持有数据库连接与模型句柄，便于序列化成 checkpoint 与单测；
* **可重放**：``snapshot()`` 输出的 JSON 足以还原一次运行（消息、步数、成本、工具签名）；
* **不可变常量**：终止原因用模块级字符串常量，两端（Python/Java）取值一致。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

# --- 终止原因（与 docs/03 SSE done.finishReason 对齐） ----------------------
FINISH_STOP = "stop"
FINISH_APPROVAL = "approval_required"
FINISH_MAX_STEPS = "max_steps"
FINISH_BUDGET = "budget"
FINISH_TIMEOUT = "timeout"
FINISH_STALLED = "stalled"
FINISH_LOOP = "loop"
FINISH_ERROR = "error"
FINISH_INTERRUPTED = "interrupted"

# 非正常终止原因集合（用于 trace 状态判定）
ABNORMAL_FINISH = {
    FINISH_MAX_STEPS,
    FINISH_BUDGET,
    FINISH_TIMEOUT,
    FINISH_STALLED,
    FINISH_LOOP,
    FINISH_ERROR,
}

# --- Agent 类型 --------------------------------------------------------------
AGENT_SUPERVISOR = "SUPERVISOR"
AGENT_SHOPPING = "SHOPPING"
AGENT_SERVICE = "SERVICE"
AGENT_OPS = "OPS"
AGENT_TYPES = (AGENT_SUPERVISOR, AGENT_SHOPPING, AGENT_SERVICE, AGENT_OPS)


@dataclass(slots=True)
class ToolCallRecord:
    """一次工具调用的落库/回放记录（对应 SSE tool_call + tool_result）。"""

    call_id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    ok: bool = True
    summary: str = ""
    latency_ms: int = 0
    risk: str = "READ"

    def to_dict(self) -> dict[str, Any]:
        return {
            "callId": self.call_id,
            "name": self.name,
            "args": self.args,
            "ok": self.ok,
            "summary": self.summary,
            "latencyMs": self.latency_ms,
            "risk": self.risk,
        }


@dataclass(slots=True)
class AgentState:
    """一次提问的完整运行态。

    ``messages`` 只存 LangChain 消息对象，序列化时由 ``snapshot()`` 转成纯文本结构。
    """

    trace_id: str
    session_id: int
    user_id: int
    question: str

    agent_type: str = AGENT_SUPERVISOR
    route_reason: str = ""

    messages: list[Any] = field(default_factory=list)
    step: int = 0

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_cents: int = 0

    started_at: float = field(default_factory=time.perf_counter)

    # 循环/无进展检测
    tool_signatures: list[str] = field(default_factory=list)
    progress_marks: list[str] = field(default_factory=list)

    citations: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    answer_parts: list[str] = field(default_factory=list)

    finish_reason: str | None = None
    approval_id: int | None = None
    model: str = ""

    # --- 派生 ---------------------------------------------------------------
    @property
    def answer(self) -> str:
        return "".join(self.answer_parts)

    @property
    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self.started_at

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def add_signature(self, name: str, args: dict[str, Any]) -> None:
        """记录工具签名（用于"同工具同参数连续两次"检测）。"""
        raw = json.dumps({"n": name, "a": args}, sort_keys=True, ensure_ascii=False, default=str)
        self.tool_signatures.append(hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16])

    def add_progress(self, payload: Any) -> None:
        """记录一步的"信息量"摘要（用于无进展检测）。"""
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        self.progress_marks.append(hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16])

    def snapshot(self) -> dict[str, Any]:
        """可重放快照：写入 ``agent_checkpoint.state``。"""
        return {
            "traceId": self.trace_id,
            "sessionId": self.session_id,
            "userId": self.user_id,
            "question": self.question,
            "agentType": self.agent_type,
            "routeReason": self.route_reason,
            "step": self.step,
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "costCents": self.cost_cents,
            "finishReason": self.finish_reason,
            "approvalId": self.approval_id,
            "model": self.model,
            "citations": self.citations,
            "toolCalls": [call.to_dict() for call in self.tool_calls],
            "toolSignatures": self.tool_signatures,
            "progressMarks": self.progress_marks,
            "answer": self.answer[:4000],
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> AgentState:
        """从 checkpoint 还原（不还原消息对象，续跑时由调用方重建历史）。"""
        state = cls(
            trace_id=str(data.get("traceId") or ""),
            session_id=int(data.get("sessionId") or 0),
            user_id=int(data.get("userId") or 0),
            question=str(data.get("question") or ""),
        )
        state.agent_type = str(data.get("agentType") or AGENT_SUPERVISOR)
        state.route_reason = str(data.get("routeReason") or "")
        state.step = int(data.get("step") or 0)
        state.prompt_tokens = int(data.get("promptTokens") or 0)
        state.completion_tokens = int(data.get("completionTokens") or 0)
        state.cost_cents = int(data.get("costCents") or 0)
        state.finish_reason = data.get("finishReason")
        state.approval_id = data.get("approvalId")
        state.model = str(data.get("model") or "")
        state.citations = list(data.get("citations") or [])
        state.tool_signatures = list(data.get("toolSignatures") or [])
        state.progress_marks = list(data.get("progressMarks") or [])
        answer = data.get("answer")
        if isinstance(answer, str) and answer:
            state.answer_parts.append(answer)
        return state


@dataclass(slots=True)
class AgentEvent:
    """SSE 事件（``name`` 直接作为 ``event:`` 行）。"""

    name: str
    data: dict[str, Any]

    def to_sse(self) -> str:
        """序列化为 SSE 文本块（含结尾空行）。"""
        payload = json.dumps(self.data, ensure_ascii=False, default=str)
        return f"event: {self.name}\ndata: {payload}\n\n"


__all__ = [
    "ABNORMAL_FINISH",
    "AGENT_OPS",
    "AGENT_SERVICE",
    "AGENT_SHOPPING",
    "AGENT_SUPERVISOR",
    "AGENT_TYPES",
    "FINISH_APPROVAL",
    "FINISH_BUDGET",
    "FINISH_ERROR",
    "FINISH_INTERRUPTED",
    "FINISH_LOOP",
    "FINISH_MAX_STEPS",
    "FINISH_STALLED",
    "FINISH_STOP",
    "FINISH_TIMEOUT",
    "AgentEvent",
    "AgentState",
    "ToolCallRecord",
]
