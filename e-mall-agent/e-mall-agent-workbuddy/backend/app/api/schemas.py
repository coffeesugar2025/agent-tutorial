"""API request/response schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    role: str
    permissions: list[str]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str = "default"


class ChatResponse(BaseModel):
    answer: str
    route: str
    trace_id: str
    context: dict[str, Any] = Field(default_factory=dict)


class OrderItemRequest(BaseModel):
    product_id: str
    quantity: int = 1


class OrderCreateRequest(BaseModel):
    items: list[OrderItemRequest]


class RefundRequest(BaseModel):
    reason: str = "用户申请"


class FulfillmentRequest(BaseModel):
    order_id: str
    thread_id: str | None = None


class ApprovalRequest(BaseModel):
    thread_id: str
    approved: bool
