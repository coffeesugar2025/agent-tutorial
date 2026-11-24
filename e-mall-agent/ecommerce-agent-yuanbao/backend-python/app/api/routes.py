"""HTTP / SSE 接口层。"""
from __future__ import annotations

import json
from importlib.metadata import version
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.agent.builder import rule_based_intent
from app.agent.middleware import get_audit_log
from app.agent.runtime import run_sync, stream_events
from app.config import settings
from app.schemas import ChatRequest, ChatSyncResponse, HealthResponse, PurchaseIntent, ToolInfo
from app.services import catalog

router = APIRouter()


def _state(request: Request) -> Any:
    return request.app.state


def _model_desc(request: Request) -> str:
    if settings.agent_mode == "real":
        return settings.model_name
    return f"mock/{settings.model_name}"


@router.get("/health", response_model=HealthResponse, summary="健康检查与运行时信息")
async def health(request: Request) -> HealthResponse:
    st = _state(request)
    return HealthResponse(
        status="ok",
        agent_mode=settings.agent_mode,
        model=_model_desc(request),
        mcp_transport=settings.mcp_transport,
        tool_count=len(st.provider.tools),
        langchain_version=version("langchain"),
    )


@router.get("/v1/tools", response_model=list[ToolInfo], summary="列出当前 Agent 可调用的 MCP 工具")
async def list_tools(request: Request) -> list[ToolInfo]:
    st = _state(request)
    return [
        ToolInfo(name=t["name"], description=t["description"],
                 source="mcp" if "mcp" in t["source"] else "local")
        for t in st.provider.describe()
    ]


@router.get("/v1/catalog/products", summary="商品目录快照（前端首屏展示用）")
async def products() -> dict[str, Any]:
    return catalog.search_products(limit=8, sort_by="rating")


@router.get("/v1/audit", summary="最近的工具调用审计记录")
async def audit(limit: int = 50) -> dict[str, Any]:
    return {"total": len(get_audit_log(limit)), "records": get_audit_log(limit)}


@router.post("/v1/chat/sync", response_model=ChatSyncResponse, summary="一次性返回完整回复（便于测试/脚本调用）")
async def chat_sync(req: ChatRequest, request: Request) -> ChatSyncResponse:
    return await run_sync(_state(request).agent, req)


@router.post("/v1/chat", summary="SSE 流式对话：token / tool_start / tool_end / cards / done")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    agent = _state(request).agent
    desc = _model_desc(request)

    async def event_source():
        async for event, data in stream_events(agent, req, desc):
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/v1/intent", response_model=PurchaseIntent, summary="结构化意图识别（response_format 演示）")
async def intent(req: ChatRequest, request: Request) -> PurchaseIntent:
    """real 模式走 create_agent(response_format=ToolStrategy(...))；
    mock 模式走规则兜底，保证无 Key 也能返回同样契约。"""
    st = _state(request)
    if settings.agent_mode == "real" and getattr(st, "intent_agent", None):
        try:
            result = await st.intent_agent.ainvoke(
                {"messages": [{"role": "user", "content": req.message}]},
                config={"configurable": {"thread_id": f"intent-{req.thread_id}"}},
            )
            parsed = result.get("structured_response")
            if isinstance(parsed, PurchaseIntent):
                return parsed
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"意图识别失败: {exc}") from exc
    return rule_based_intent(req.message)


@router.delete("/v1/sessions/{thread_id}", summary="清除某会话的服务端记忆（演示用）")
async def clear_session(thread_id: str, request: Request) -> dict[str, str]:
    """InMemorySaver 的 thread 数据由 checkpointer 管理，这里返回重置指引。"""
    return {"thread_id": thread_id, "status": "ok", "note": "新 thread_id 即开启全新会话"}
