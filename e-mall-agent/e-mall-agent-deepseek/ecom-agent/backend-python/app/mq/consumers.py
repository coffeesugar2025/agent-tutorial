"""MQ 消费者注册表。

所有 handler 都是**幂等**的：MQ 至少一次投递语义下，重复消费不能产生重复副作用。
- 索引：``ingest_document`` 内部按 checksum 判断是否需要重建；
- 删除：文档已软删时直接返回；
- 退款：``create_refund_request`` 用幂等键去重；
- 摘要：可重复生成，结果覆盖写。

handler 签名固定为 ``(payload: dict) -> None``（与 ``app.infra.rabbit.Handler`` 一致）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.infra.rabbit import register_handler

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 知识库
# ---------------------------------------------------------------------------
def handle_knowledge_index(payload: dict[str, Any]) -> None:
    """解析 → 切片 → 向量化 → 入库。"""
    from app.rag.ingest import ingest_document

    document_id = int(payload.get("documentId") or 0)
    job_id = payload.get("jobId")
    if not document_id:
        logger.warning("knowledge.index 缺少 documentId: %s", payload)
        return
    result = ingest_document(
        document_id,
        job_id=int(job_id) if job_id is not None else None,
        force=bool(payload.get("force")),
    )
    logger.info("知识索引完成 document=%s result=%s", document_id, result.get("ok"))


def handle_knowledge_delete(payload: dict[str, Any]) -> None:
    """软删 + 清理向量。"""
    from app.rag.ingest import delete_document

    document_id = int(payload.get("documentId") or 0)
    if not document_id:
        return
    delete_document(document_id, job_id=payload.get("jobId"))


# ---------------------------------------------------------------------------
# 会话摘要
# ---------------------------------------------------------------------------
def handle_session_summarize(payload: dict[str, Any]) -> None:
    """把会话压成摘要写回 ``chat_session.summary``。"""
    from app.memory import session as session_memory

    session_id = int(payload.get("sessionId") or 0)
    if not session_id:
        return

    history = session_memory.history_dicts(session_id, limit=40)
    if not history:
        return

    try:
        from app.infra.db import session_scope
        from app.infra.models import ChatSession

        with session_scope() as db:
            row = db.get(ChatSession, session_id)
            previous = row.summary if row else None
    except Exception:  # noqa: BLE001
        previous = None

    summary = session_memory.build_summary_text(history, previous)
    session_memory.update_summary(session_id, summary)
    logger.info("会话摘要已更新 session=%s length=%s", session_id, len(summary))


# ---------------------------------------------------------------------------
# 退款执行
# ---------------------------------------------------------------------------
def handle_refund_execute(payload: dict[str, Any]) -> None:
    """审批通过后的退款执行（异步消费）。"""
    from app.hitl.approval import execute_action

    try:
        result = asyncio.run(execute_action(payload))
        logger.info("退款执行完成 approval=%s result=%s", payload.get("approvalId"), result)
    except Exception as exc:  # noqa: BLE001 - 抛出让 MQ 走重试/死信
        logger.exception("退款执行失败 approval=%s", payload.get("approvalId"))
        raise RuntimeError(f"refund execute failed: {exc}") from exc


# ---------------------------------------------------------------------------
# 评测
# ---------------------------------------------------------------------------
def handle_eval_batch(payload: dict[str, Any]) -> None:
    """跑一批评测；评测模块缺失时把批次置为 FAILED，避免永远 RUNNING。"""
    run_id = int(payload.get("runId") or 0)
    suite = str(payload.get("suite") or "shopping")
    repeat = int(payload.get("repeat") or 1)
    try:
        from app.eval.runner import run_batch

        run_batch(run_id=run_id, suite=suite, repeat=repeat)
    except ImportError:
        logger.warning("评测模块未安装，批次标记失败 run=%s", run_id)
        _fail_eval_run(run_id, "评测模块不可用")
    except Exception as exc:  # noqa: BLE001
        logger.exception("评测批次失败 run=%s", run_id)
        _fail_eval_run(run_id, str(exc)[:500])


def _fail_eval_run(run_id: int, error: str) -> None:
    try:
        from app.common.timeutil import utcnow
        from app.infra.db import session_scope
        from app.infra.models_obs import EvalRun

        with session_scope() as db:
            row = db.get(EvalRun, run_id)
            if row is not None:
                row.status = "FAILED"
                row.report = {"error": error}
                row.finished_at = utcnow()
    except Exception as exc:  # noqa: BLE001
        logger.warning("标记评测失败出错: %s", exc)


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------
def register_all() -> None:
    """幂等注册（重复调用覆盖同名 handler，不会重复消费）。"""
    register_handler("knowledge.index", handle_knowledge_index)
    register_handler("knowledge.delete", handle_knowledge_delete)
    register_handler("session.summarize", handle_session_summarize)
    register_handler("refund.execute", handle_refund_execute)
    register_handler("eval.batch", handle_eval_batch)


register_all()

__all__ = [
    "handle_eval_batch",
    "handle_knowledge_delete",
    "handle_knowledge_index",
    "handle_refund_execute",
    "handle_session_summarize",
    "register_all",
]
