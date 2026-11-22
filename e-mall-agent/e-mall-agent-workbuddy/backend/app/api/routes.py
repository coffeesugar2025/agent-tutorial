"""REST + SSE API surface."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..agents.supervisor import run_agent, stream_agent
from ..config import get_settings
from ..context.engine import ContextEngine
from ..domain.models import User
from ..domain.repository import get_repository
from ..mcp.tools import ALL_TOOL_FUNCTIONS
from ..observability.tracer import describe_graphs, get_tracer
from ..rag.pipeline import get_rag_pipeline
from ..security.audit import get_audit_logger
from ..security.rbac import (
    decode_token,
    has_permission,
    issue_token,
    permissions_for,
    require_customer_scope,
    require_permission,
    reset_current_user,
    set_current_user,
    user_from_payload,
)
from ..workflows.fulfillment import resume_fulfillment, run_fulfillment
from .schemas import (
    ApprovalRequest,
    ChatRequest,
    ChatResponse,
    FulfillmentRequest,
    LoginRequest,
    OrderCreateRequest,
    RefundRequest,
)

router = APIRouter(prefix="/api")


async def current_user(authorization: str | None = Header(default=None)) -> AsyncIterator[User]:
    user = User(id="anonymous", name="访客", role="guest")
    if authorization and authorization.startswith("Bearer "):
        payload = decode_token(authorization.removeprefix("Bearer ").strip(),
                               get_settings().secret_key)
        if payload:
            user = user_from_payload(payload)
    marker = set_current_user(user)
    try:
        yield user
    finally:
        reset_current_user(marker)


def require(permission: str):
    def dependency(user: User = Depends(current_user)) -> User:
        require_permission(user, permission)
        return user
    return dependency


def _deny_if(condition: bool, message: str, status: int = 403) -> None:
    if condition:
        raise HTTPException(status_code=status, detail=message)


# ---------- auth ----------
@router.post("/auth/login")
async def login(payload: LoginRequest) -> dict[str, Any]:
    user = get_repository().authenticate(payload.username, payload.password)
    if not user:
        get_audit_logger().record(payload.username, "auth.login", "token", "deny", "凭证错误")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = issue_token(user, get_settings().secret_key, get_settings().token_ttl_seconds)
    get_audit_logger().record(user.id, "auth.login", "token", "allow")
    return {"token": token, "user_id": user.id, "role": user.role,
            "permissions": permissions_for(user.role)}


@router.get("/auth/me")
async def me(user: User = Depends(current_user)) -> dict[str, Any]:
    return {"id": user.id, "name": user.name, "role": user.role,
            "permissions": permissions_for(user.role)}


# ---------- chat ----------
@router.post("/chat", response_model=ChatResponse)
async def chat(payload: ChatRequest, user: User = Depends(require("chat:use")),
               authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = authorization.removeprefix("Bearer ").strip() if authorization else None
    result = await run_agent(payload.message, user, payload.thread_id, token)
    return {"answer": result["answer"], "route": result["route"],
            "trace_id": result["trace_id"], "context": result.get("context", {})}


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest, user: User = Depends(require("chat:use")),
                      authorization: str | None = Header(default=None)) -> StreamingResponse:
    token = authorization.removeprefix("Bearer ").strip() if authorization else None

    async def events() -> AsyncIterator[str]:
        marker = set_current_user(user)
        try:
            async for event in stream_agent(payload.message, user, payload.thread_id, token):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            reset_current_user(marker)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- catalog ----------
@router.get("/products")
async def products(query: str = "", category: str | None = None,
                   user: User = Depends(require("product:read"))) -> list[dict[str, Any]]:
    repo = get_repository()
    items = repo.search_products(query) if query else repo.list_products(category)
    return [p.model_dump() for p in items]


@router.get("/products/{product_id}")
async def product(product_id: str,
                  user: User = Depends(require("product:read"))) -> dict[str, Any]:
    item = get_repository().get_product(product_id)
    _deny_if(item is None, "商品不存在", 404)
    return item.model_dump()


# ---------- orders ----------
@router.get("/orders")
async def orders(customer_id: str | None = None,
                 user: User = Depends(require("order:read"))) -> list[dict[str, Any]]:
    target = customer_id or user.id
    try:
        require_customer_scope(user, target)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return [o.model_dump() for o in get_repository().list_orders(target)]


@router.post("/orders", status_code=201)
async def create_order(payload: OrderCreateRequest,
                       user: User = Depends(require("order:create"))) -> dict[str, Any]:
    try:
        order = get_repository().create_order(user.id, [i.model_dump() for i in payload.items])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    get_audit_logger().record(user.id, "api.create_order", order.id, "allow", f"total={order.total}")
    return order.model_dump()


@router.get("/orders/{order_id}")
async def get_order(order_id: str,
                    user: User = Depends(require("order:read"))) -> dict[str, Any]:
    order = get_repository().get_order(order_id)
    _deny_if(order is None, "订单不存在", 404)
    try:
        require_customer_scope(user, order.customer_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return order.model_dump()


@router.post("/orders/{order_id}/refund")
async def refund(order_id: str, payload: RefundRequest,
                 user: User = Depends(require("order:refund"))) -> dict[str, Any]:
    order = get_repository().get_order(order_id)
    _deny_if(order is None, "订单不存在", 404)
    try:
        require_customer_scope(user, order.customer_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    updated = get_repository().request_refund(order_id, payload.reason)
    get_audit_logger().record(user.id, "api.refund", order_id, "allow", payload.reason)
    return {"order_id": order_id, "status": updated.status if updated else "unknown"}


# ---------- workflow ----------
@router.post("/workflows/fulfillment/run")
async def fulfillment_run(payload: FulfillmentRequest,
                          user: User = Depends(require("order:manage"))) -> dict[str, Any]:
    order = get_repository().get_order(payload.order_id)
    _deny_if(order is None, "订单不存在", 404)
    try:
        require_customer_scope(user, order.customer_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return await run_fulfillment(payload.order_id, order.customer_id, payload.thread_id)


@router.post("/workflows/fulfillment/resume")
async def fulfillment_resume(payload: ApprovalRequest,
                             user: User = Depends(require("order:manage"))) -> dict[str, Any]:
    get_audit_logger().record(user.id, "workflow.approve", payload.thread_id,
                              "allow", f"approved={payload.approved}")
    return await resume_fulfillment(payload.thread_id, payload.approved)


# ---------- observability / context ----------
@router.get("/graphs")
async def graphs(user: User = Depends(current_user)) -> dict[str, Any]:
    return describe_graphs()


@router.get("/traces")
async def traces(limit: int = 50, trace_id: str | None = None,
                 user: User = Depends(current_user)) -> list[dict[str, Any]]:
    if not has_permission(user, "trace:read"):
        raise HTTPException(status_code=403, detail="需要 trace:read 权限")
    return get_tracer().query(limit, trace_id)


@router.get("/audit")
async def audit(limit: int = 50, decision: str | None = None,
                user: User = Depends(require("audit:read"))) -> list[dict[str, Any]]:
    return get_audit_logger().query(limit, decision=decision)


@router.get("/context/preview")
async def context_preview(message: str = "我想买降噪耳机",
                          user: User = Depends(current_user)) -> dict[str, Any]:
    docs = get_rag_pipeline().retrieve(message)
    messages, snapshot = ContextEngine().build(
        persona="你是电商智能助手，只基于事实回答。", user=user,
        retrieved_docs=docs, tools=ALL_TOOL_FUNCTIONS,
        history=[], user_input=message,
    )
    return {"snapshot": snapshot.as_dict(),
            "messages": [{"role": type(m).__name__, "content": str(m.content)} for m in messages]}


@router.get("/rag/search")
async def rag_search(q: str = Query(default="退货政策"),
                     user: User = Depends(current_user)) -> list[dict[str, Any]]:
    return get_rag_pipeline().retrieve(q)


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": get_settings().app_name,
            "llm_provider": get_settings().llm_provider, "mcp_mode": get_settings().mcp_mode}


__all__ = ["router", "current_user"]
