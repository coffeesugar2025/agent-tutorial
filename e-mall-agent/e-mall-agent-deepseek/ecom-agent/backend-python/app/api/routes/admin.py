"""运营与可观测接口：概览、链路、成本、模型健康、评测。"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db, require_admin
from app.common.envelope import ok
from app.common.errors import not_found
from app.common.timeutil import utcnow
from app.infra.models import ChatMessage, ChatSession
from app.infra.models_obs import AgentSpan, AgentTrace, EvalCaseResult, EvalRun, LlmCall

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["运营与可观测"])

SPAN_TOOL = "TOOL"


class EvalRunReq(BaseModel):
    suite: str = Field(default="shopping", max_length=64)
    repeat: int = Field(default=3, ge=1, le=10)


@router.get("/overview", summary="概览指标")
def overview(days: int = Query(default=7, ge=1, le=90), db: Session = Depends(get_db), user: CurrentUser = Depends(require_admin)):
    since = utcnow() - timedelta(days=days)

    total_sessions = _scalar(db.query(func.count(ChatSession.id)))
    total_messages = _scalar(db.query(func.count(ChatMessage.id)))

    trace_q = db.query(AgentTrace).filter(AgentTrace.created_at >= since)
    traces = trace_q.all()
    total_traces = len(traces)
    success = len([t for t in traces if t.status == "SUCCESS"])
    latencies = sorted(int(t.total_latency_ms or 0) for t in traces)
    costs = sum(int(t.total_cost_cents or 0) for t in traces)

    tool_total = _scalar(
        db.query(func.count(AgentSpan.id)).filter(
            AgentSpan.span_type == SPAN_TOOL, AgentSpan.started_at >= since
        )
    )
    tool_error = _scalar(
        db.query(func.count(AgentSpan.id)).filter(
            AgentSpan.span_type == SPAN_TOOL,
            AgentSpan.started_at >= since,
            AgentSpan.status != "OK",
        )
    )

    top_tools = [
        {"name": name, "count": count}
        for name, count in (
            db.query(AgentSpan.name, func.count(AgentSpan.id))
            .filter(AgentSpan.span_type == SPAN_TOOL, AgentSpan.started_at >= since)
            .group_by(AgentSpan.name)
            .order_by(func.count(AgentSpan.id).desc())
            .limit(5)
            .all()
        )
    ]

    return ok(
        {
            "totalSessions": total_sessions,
            "totalMessages": total_messages,
            "successRate": round(success / total_traces, 4) if total_traces else 0.0,
            "avgLatencyMs": int(sum(latencies) / len(latencies)) if latencies else 0,
            "p95LatencyMs": _percentile(latencies, 0.95),
            "totalCostCents": costs,
            "costPerSuccessCents": round(costs / success, 2) if success else 0.0,
            "approvalPending": _pending_approvals(),
            "toolErrorRate": round(tool_error / tool_total, 4) if tool_total else 0.0,
            "topTools": top_tools,
            "trend": _trend(db, days),
            "windowDays": days,
        }
    )


@router.get("/traces", summary="链路列表")
def list_traces(
    session_id: int | None = Query(default=None, alias="sessionId"),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_admin),
):
    query = db.query(AgentTrace)
    if session_id:
        query = query.filter(AgentTrace.session_id == session_id)
    if status:
        query = query.filter(AgentTrace.status == status.upper())
    rows = query.order_by(AgentTrace.id.desc()).limit(limit).all()
    return ok([_trace_vo(row) for row in rows])


@router.get("/traces/{trace_id}", summary="链路详情（可重放）")
def get_trace(trace_id: str, db: Session = Depends(get_db), user: CurrentUser = Depends(require_admin)):
    row = db.query(AgentTrace).filter(AgentTrace.trace_id == trace_id).one_or_none()
    if row is None:
        raise not_found("链路不存在")
    spans = (
        db.query(AgentSpan)
        .filter(AgentSpan.trace_id == trace_id)
        .order_by(AgentSpan.seq.asc())
        .all()
    )
    replayable = any(span.span_type in ("LLM", SPAN_TOOL) for span in spans)
    return ok(
        {
            "trace": _trace_vo(row),
            "spans": [
                {
                    "spanId": span.span_id,
                    "parentSpanId": span.parent_span_id,
                    "name": span.name,
                    "spanType": span.span_type,
                    "seq": span.seq,
                    "input": span.input or {},
                    "output": span.output or {},
                    "latencyMs": span.latency_ms,
                    "status": span.status,
                    "error": span.error,
                }
                for span in spans
            ],
            "replayable": replayable,
        }
    )


@router.get("/costs", summary="成本分析")
def costs(days: int = Query(default=7, ge=1, le=90), db: Session = Depends(get_db), user: CurrentUser = Depends(require_admin)):
    since = utcnow() - timedelta(days=days)
    rows = db.query(LlmCall).filter(LlmCall.created_at >= since).all()
    total = sum(int(r.cost_cents or 0) for r in rows)

    by_model: dict[str, dict[str, Any]] = {}
    by_provider: dict[str, dict[str, Any]] = {}
    daily: dict[str, int] = {}
    for row in rows:
        m = by_model.setdefault(row.model, {"model": row.model, "calls": 0, "costCents": 0, "tokens": 0})
        m["calls"] += 1
        m["costCents"] += int(row.cost_cents or 0)
        m["tokens"] += int(row.prompt_tokens or 0) + int(row.completion_tokens or 0)

        p = by_provider.setdefault(row.provider, {"provider": row.provider, "calls": 0, "costCents": 0})
        p["calls"] += 1
        p["costCents"] += int(row.cost_cents or 0)

        day = row.created_at.strftime("%Y-%m-%d") if row.created_at else "-"
        daily[day] = daily.get(day, 0) + int(row.cost_cents or 0)

    return ok(
        {
            "total": total,
            "byModel": sorted(by_model.values(), key=lambda x: x["costCents"], reverse=True),
            "byProvider": sorted(by_provider.values(), key=lambda x: x["costCents"], reverse=True),
            "daily": [{"date": k, "costCents": v} for k, v in sorted(daily.items())],
        }
    )


@router.get("/models", summary="模型健康与熔断状态")
def models(db: Session = Depends(get_db), user: CurrentUser = Depends(require_admin)):
    from app.llm.cost import model_call_stats
    from app.llm.fallback import health_snapshot

    try:
        rows = health_snapshot(model_call_stats(7))
    except Exception as exc:  # noqa: BLE001 - 统计失败不能影响接口
        logger.warning("模型健康快照失败: %s", exc)
        rows = []
    normalised = [
        {
            "provider": item.get("provider"),
            "model": item.get("model"),
            "role": item.get("role") or item.get("tier") or "fallback",
            "healthy": bool(item.get("healthy", True)),
            "circuit": item.get("circuit") or item.get("state") or "CLOSED",
            "avgLatencyMs": int(item.get("avgLatencyMs") or item.get("avgLatencyMs", 0) or 0),
            "calls": int(item.get("calls") or 0),
        }
        for item in (rows or [])
    ]
    return ok(normalised)


@router.post("/evals/run", summary="触发评测批次")
def run_eval(req: EvalRunReq, db: Session = Depends(get_db), user: CurrentUser = Depends(require_admin)):
    """建批次并投递 MQ；真正执行由 eval 消费者完成（可离线跑）。"""
    row = EvalRun(suite=req.suite, status="QUEUED", total=0, passed=0, repeat_times=req.repeat)
    db.add(row)
    db.flush()
    db.commit()

    try:
        from app.infra.rabbit import message_bus

        message_bus.publish("eval.batch", {"runId": int(row.id), "suite": req.suite, "repeat": req.repeat})
    except Exception as exc:  # noqa: BLE001
        logger.warning("评测任务投递失败 run=%s err=%s", row.id, exc)

    return ok({"runId": row.id, "status": "QUEUED"})


@router.get("/evals/runs", summary="评测批次列表")
def list_eval_runs(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db), user: CurrentUser = Depends(require_admin)):
    rows = db.query(EvalRun).order_by(EvalRun.id.desc()).limit(limit).all()
    return ok([_eval_vo(row) for row in rows])


@router.get("/evals/runs/{run_id}", summary="评测详情")
def get_eval_run(run_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(require_admin)):
    row = db.get(EvalRun, run_id)
    if row is None:
        raise not_found("评测批次不存在")
    cases = db.query(EvalCaseResult).filter(EvalCaseResult.run_id == run_id).all()
    payload = _eval_vo(row)
    payload["cases"] = [
        {
            "caseId": c.case_id,
            "question": c.question,
            "expected": c.expected,
            "actual": (c.actual or "")[:800],
            "passed": bool(c.passed),
            "score": float(c.score or 0),
            "attempts": c.attempts,
        }
        for c in cases
    ]
    return ok(payload)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _scalar(query: Any) -> int:
    try:
        return int(query.scalar() or 0)
    except Exception:  # noqa: BLE001
        return 0


def _percentile(sorted_values: list[int], ratio: float) -> int:
    if not sorted_values:
        return 0
    index = min(len(sorted_values) - 1, int(round(ratio * (len(sorted_values) - 1))))
    return int(sorted_values[index])


def _pending_approvals() -> int:
    try:
        from app.hitl.approval import pending_count

        return pending_count()
    except Exception:  # noqa: BLE001
        return 0


def _trend(db: Session, days: int) -> list[dict[str, Any]]:
    since = utcnow() - timedelta(days=days)
    sessions = (
        db.query(func.date(ChatSession.created_at), func.count(ChatSession.id))
        .filter(ChatSession.created_at >= since)
        .group_by(func.date(ChatSession.created_at))
        .all()
    )
    costs = (
        db.query(func.date(LlmCall.created_at), func.sum(LlmCall.cost_cents))
        .filter(LlmCall.created_at >= since)
        .group_by(func.date(LlmCall.created_at))
        .all()
    )
    cost_map = {str(day): int(total or 0) for day, total in costs}
    return [
        {"date": str(day), "sessions": int(count), "costCents": cost_map.get(str(day), 0)}
        for day, count in sessions
    ]


def _trace_vo(row: AgentTrace) -> dict[str, Any]:
    return {
        "traceId": row.trace_id,
        "sessionId": row.session_id,
        "userId": row.user_id,
        "agentType": row.agent_type,
        "question": row.question,
        "status": row.status,
        "totalLatencyMs": row.total_latency_ms,
        "totalCostCents": row.total_cost_cents,
        "stepCount": row.step_count,
        "createdAt": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
    }


def _eval_vo(row: EvalRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "suite": row.suite,
        "status": row.status,
        "total": row.total,
        "passed": row.passed,
        "passRate": float(row.pass_rate or 0),
        "passK": float(row.pass_k or 0),
        "repeat": row.repeat_times,
        "avgCostCents": row.avg_cost_cents,
        "avgLatencyMs": row.avg_latency_ms,
        "startedAt": row.started_at.isoformat(timespec="seconds") if row.started_at else None,
        "finishedAt": row.finished_at.isoformat(timespec="seconds") if row.finished_at else None,
    }


__all__ = ["router"]
