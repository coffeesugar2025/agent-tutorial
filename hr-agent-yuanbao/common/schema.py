"""统一契约的 Pydantic 模型（FastAPI 自动校验 + 自动生成 /docs）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DemoRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict, description="该章 Demo 的表单参数")


class ApproveRequest(BaseModel):
    case_id: str
    action: str = Field(default="approve", description="approve | reject")
    approver: str = "李四（主管）"


class DemoResponse(BaseModel):
    chapter: str
    mode: str
    trace_id: str
    answer: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    state: dict[str, Any] = Field(default_factory=dict)
    hitl: dict[str, Any] | None = None
