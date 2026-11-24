"""API 契约 + LangChain 1.5 结构化输出 Schema。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ---------------- 请求 ----------------
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000, description="用户自然语言问题")
    thread_id: str = Field(default="default", max_length=64, description="会话 ID，对应 LangGraph thread")
    user_id: str = Field(default="u_1001", max_length=64, description="用于订单/优惠券鉴权的用户标识")

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message 不能为空或纯空白")
        return value


class ToolInfo(BaseModel):
    name: str
    description: str
    source: Literal["mcp", "local"] = "mcp"


# ---------------- SSE 事件（前后端协议） ----------------
class SSEEvent(BaseModel):
    event: Literal["meta", "token", "tool_start", "tool_end", "cards", "error", "done"]
    data: dict[str, Any] = Field(default_factory=dict)


# ---------------- 同步响应 ----------------
class ChatSyncResponse(BaseModel):
    thread_id: str
    answer: str
    tool_traces: list[dict[str, Any]] = Field(default_factory=list)
    cards: list[dict[str, Any]] = Field(default_factory=list)
    elapsed_ms: int = 0


class HealthResponse(BaseModel):
    status: str
    agent_mode: str
    model: str
    mcp_transport: str
    tool_count: int
    langchain_version: str


# ---------------- LangChain 1.5 response_format ----------------
class PurchaseIntent(BaseModel):
    """意图识别结构化输出：交给 create_agent(response_format=...) 校验并产出。"""

    intent: Literal["search_product", "order_query", "price_calc", "after_sale", "recommend", "other"] = Field(
        description="用户主意图"
    )
    keywords: list[str] = Field(default_factory=list, description="检索关键词")
    budget_max: float | None = Field(default=None, description="预算上限，未提及为 null")
    category: str | None = Field(default=None, description="商品类目，未提及为 null")
    needs_tool: bool = Field(default=True, description="是否需要调用 MCP 工具")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class AgentAnswer(BaseModel):
    """可选的强结构化回复（含商品卡与来源）。"""

    answer: str
    cited_skus: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
