"""对话接口：会话管理、SSE 流式对话、中断、审批。

SSE 是本项目最关键的接口，几条硬约束：

* 事件名与 data 结构与 ``docs/03-API契约.md`` 逐字一致；
* ``meta`` 必须是第一个事件，且携带真实的 assistant ``messageId``；
* 空闲时由前端负责保活，服务端不主动发心跳（避免与业务事件竞争）；
* 客户端断开时取消运行时任务，避免后台空转烧 token；
* ``clientMsgId`` 用于幂等：同一 session 下重复提交不重复执行。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-01] 交互协议
# 职责：对话接口：会话管理、SSE 流式对话、中断、审批
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agents.runtime import AgentRuntime
from app.agents.state import AgentEvent
from app.api.deps import CurrentUser, get_current_user, get_db
from app.common.envelope import ok
from app.common.errors import conflict, not_found, param_invalid
from app.common.ids import new_trace_id
from app.hitl import approval as hitl
from app.infra.db import session_scope
from app.memory import session as session_memory
from app.security.ratelimit import limit_chat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["对话"])


# ---------------------------------------------------------------------------
# 中断控制
# ---------------------------------------------------------------------------
class RunRegistry:
    """进程内运行登记表。

    单机部署足够；多副本时把 ``interrupted`` 换成 Redis 标记即可（接口不变）。
    """

    def __init__(self) -> None:
        self._flags: dict[int, bool] = {}
        self._lock = threading.Lock()

    def start(self, session_id: int) -> None:
        with self._lock:
            self._flags[session_id] = False

    def interrupt(self, session_id: int) -> bool:
        with self._lock:
            if session_id not in self._flags:
                return False
            self._flags[session_id] = True
            return True

    def interrupted(self, session_id: int) -> bool:
        with self._lock:
            return self._flags.get(session_id, False)

    def finish(self, session_id: int) -> None:
        with self._lock:
            self._flags.pop(session_id, None)


runs = RunRegistry()


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class CreateSessionReq(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class StreamReq(BaseModel):
    session_id: int = Field(alias="sessionId")
    message: str = Field(min_length=1, max_length=4000)
    client_msg_id: str | None = Field(default=None, alias="clientMsgId")

    model_config = {"populate_by_name": True}


class ApprovalReq(BaseModel):
    decision: str = Field(description="APPROVE 或 REJECT")
    comment: str | None = Field(default=None, max_length=512)


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------
@router.post("/sessions", summary="新建会话")
def create_session(req: CreateSessionReq | None = None, user: CurrentUser = Depends(get_current_user)):
    title = req.title if req else None
    return ok(session_memory.create_session(user.id, title))


@router.get("/sessions", summary="我的会话列表")
def list_sessions(user: CurrentUser = Depends(get_current_user)):
    return ok(session_memory.list_sessions(user.id))


@router.get("/sessions/{session_id}", summary="会话详情")
def get_session(session_id: int, user: CurrentUser = Depends(get_current_user)):
    return ok(session_memory.get_session(session_id, user.id))


@router.delete("/sessions/{session_id}", summary="删除会话")
def delete_session(session_id: int, user: CurrentUser = Depends(get_current_user)):
    session_memory.delete_session(session_id, user.id)
    return ok(None)


@router.get("/sessions/{session_id}/messages", summary="会话消息")
def list_messages(
    session_id: int,
    limit: int = 50,
    user: CurrentUser = Depends(get_current_user),
):
    return ok(session_memory.list_messages(session_id, user.id, limit))


@router.post("/sessions/{session_id}/interrupt", summary="中断当前生成")
def interrupt(session_id: int, user: CurrentUser = Depends(get_current_user)):
    session_memory.get_session(session_id, user.id)  # 校验归属
    stopped = runs.interrupt(session_id)
    return ok({"interrupted": stopped})


# ---------------------------------------------------------------------------
# 流式对话
# ---------------------------------------------------------------------------
# ──────── [CAP-01] 交互协议 ────────
#   本处：SSE 流式（10 类事件 + 断开即停）
#   域约束：事件名与字段是前后端契约，改动必须同步 docs/03 与前端状态机
@router.post("/stream", summary="流式对话（SSE）")
async def stream(req: StreamReq, request: Request, user: CurrentUser = Depends(get_current_user)):
    """服务端事件流。事件序列见契约：meta → agent → delta/tool_* → usage → done。"""
    session_memory.get_session(req.session_id, user.id)  # 归属校验，失败抛 404
    limit_chat(user.id, req.session_id)

    trace_id = new_trace_id()
    duplicate = _claim_client_msg(req.session_id, req.client_msg_id)
    runs.start(req.session_id)

    async def event_stream():
        try:
            if duplicate:
                # 幂等命中：不重复执行，只回一个明确的结束事件
                yield AgentEvent(
                    "meta", {"traceId": trace_id, "messageId": 0, "sessionId": req.session_id}
                ).to_sse()
                yield AgentEvent("delta", {"text": "（重复提交已忽略，请勿重复发送）"}).to_sse()
                yield AgentEvent("done", {"messageId": 0, "finishReason": "stop"}).to_sse()
                return

            runtime = AgentRuntime()
            async for event in runtime.run(
                user_id=user.id,
                session_id=req.session_id,
                question=req.message.strip(),
                trace_id=trace_id,
            ):
                if await _disconnected(request):
                    logger.info("客户端断开，停止生成 session=%s", req.session_id)
                    break
                if runs.interrupted(req.session_id):
                    yield AgentEvent(
                        "done", {"messageId": 0, "finishReason": "interrupted"}
                    ).to_sse()
                    break
                yield event.to_sse()
        except asyncio.CancelledError:  # pragma: no cover - 客户端关闭连接
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("SSE 流异常 session=%s", req.session_id)
            yield AgentEvent("error", {"code": 50000, "message": f"服务内部错误：{type(exc).__name__}"}).to_sse()
        finally:
            runs.finish(req.session_id)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _disconnected(request: Request) -> bool:
    """检测客户端是否已断开（避免继续消耗模型调用）。"""
    try:
        return await request.is_disconnected()
    except Exception:  # noqa: BLE001
        return False


def _claim_client_msg(session_id: int, client_msg_id: str | None) -> bool:
    """记录 clientMsgId；返回 True 表示重复提交。"""
    if not client_msg_id:
        return False
    key = f"chat:{session_id}:{client_msg_id}"
    try:
        from app.infra.models_obs import IdempotencyRecord

        with session_scope() as db:
            if db.get(IdempotencyRecord, key) is not None:
                return True
            db.add(IdempotencyRecord(idem_key=key, scope="chat", result={"accepted": True}))
        return False
    except Exception as exc:  # noqa: BLE001 - 去重失败不阻断
        logger.warning("幂等记录失败 key=%s err=%s", key, exc)
        return False


# ---------------------------------------------------------------------------
# 审批
# ---------------------------------------------------------------------------
@router.get("/approvals", summary="我的审批任务")
def list_approvals(
    status: str = "PENDING",
    user: CurrentUser = Depends(get_current_user),
):
    return ok(hitl.list_tasks(user.id, status=status))
# ──────── [CAP-10] 人机协作 HITL ────────
#   本处：审批决策接口（透传角色）
#   域约束：工具本体无副作用，审批通过后才执行 approved_func；越权一律按不存在处理


@router.post("/approvals/{approval_id}", summary="提交审批决策")
async def decide_approval(
    approval_id: int,
    req: ApprovalReq,
    user: CurrentUser = Depends(get_current_user),
):
    """批准后立即触发动作执行（MQ 可用则异步，否则就地执行）。"""
    if req.decision.upper() not in ("APPROVE", "REJECT"):
        raise param_invalid("decision 只能是 APPROVE 或 REJECT")
    try:
        result = await hitl.decide(
            approval_id, user.id, req.decision, req.comment, roles=user.roles
        )
    except Exception as exc:  # noqa: BLE001 - 把业务异常透传为标准错误
        if exc.__class__.__name__ == "BizError":
            raise
        raise conflict(str(exc)) from exc
    return ok(result)


@router.get("/approvals/{approval_id}", summary="审批详情")
def get_approval(approval_id: int, user: CurrentUser = Depends(get_current_user)):
    task = hitl.get_task(approval_id)
    if task is None or task["sessionId"] == 0:
        raise not_found("审批任务不存在")
    return ok(task)


__all__ = ["router", "runs"]
