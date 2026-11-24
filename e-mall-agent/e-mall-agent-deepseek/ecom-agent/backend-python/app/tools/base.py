"""工具基座：风险分级、超时、重试（仅 READ）、幂等、审计、span。

工具函数的签名统一为 ``def fn(ctx: ToolContext, **kwargs) -> dict``（或 async），
返回**可 JSON 序列化的 dict**。所有横切关注点由 :class:`ToolExecutor` 统一处理：

* ``READ``：直接执行，可重试，不写幂等与审计；
* ``WRITE``：执行 + 审计 + 幂等；
* ``IRREVERSIBLE``：先抛 :class:`ApprovalRequired`，人工通过后才真正执行。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-05] 工具治理
# 职责：工具基座：风险分级、超时、重试（仅 READ）、幂等、审计、span
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, ValidationError
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.common.errors import param_invalid
from app.common.ids import idempotency_key
from app.common.timeutil import utcnow
from app.infra import models_obs
from app.infra.db import session_scope
from app.infra.models_obs import IdempotencyRecord
from app.obs.metrics import record_tool_call
from app.obs.trace import SPAN_TOOL, TraceRecorder
from app.security.injection import sanitize_for_audit
from app.security.pii import mask_obj

logger = logging.getLogger(__name__)

# 可重试的异常（仅 READ 工具）
_RETRYABLE = (TimeoutError, ConnectionError, OSError)


class Risk(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    IRREVERSIBLE = "IRREVERSIBLE"


class ApprovalRequired(Exception):
    """IRREVERSIBLE 工具中断信号：由 runtime 捕获后创建 approval_task 并挂起。"""

    def __init__(
        self,
        tool: str,
        args: dict[str, Any],
        action_type: str,
        title: str,
        detail: dict[str, Any] | None = None,
        risk: Risk = Risk.IRREVERSIBLE,
    ) -> None:
        super().__init__(f"工具 {tool} 需要人工审批")
        self.tool = tool
        # 注意：不能用 self.args —— BaseException.args 是特殊属性，
        # 赋值会被强制转成 tuple，导致参数丢失成 ['orderNo', 'reason']。
        self.tool_args = args
        self.action_type = action_type
        self.title = title
        self.detail = detail or {}
        self.risk = risk


@dataclass
class ToolContext:
    """工具执行上下文（由 runtime 注入）。"""

    user_id: int
    session_id: int
    trace_id: str
    agent_type: str = "SUPERVISOR"
    recorder: TraceRecorder | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """工具执行结果。"""

    name: str
    call_id: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    latency_ms: int = 0
    error: str | None = None
    risk: str = Risk.READ.value
    cached: bool = False

    def to_event(self) -> dict[str, Any]:
        """SSE ``tool_result`` 事件体。"""
        return {
            "callId": self.call_id,
            "name": self.name,
            "ok": self.ok,
            "summary": self.summary,
            "latencyMs": self.latency_ms,
        }

    def to_content(self) -> str:
        """给模型看的工具消息正文（JSON，便于结构化引用）。"""
        payload: dict[str, Any] = {
            "ok": self.ok,
            "tool": self.name,
            "summary": self.summary,
            "data": mask_obj(self.data),
        }
        if self.error:
            payload["error"] = self.error
        return json.dumps(payload, ensure_ascii=False, default=str)
# ──────── [CAP-05] 工具治理 ────────
#   本处：工具定义（风险分级/schema/审批钩子）
#   域约束：READ 可重试、WRITE 幂等、IRREVERSIBLE 必须走审批；新增工具只注册不改管线


@dataclass
class ToolSpec:
    """工具定义。"""

    name: str
    description: str
    func: Callable[..., dict[str, Any]]
    risk: Risk = Risk.READ
    args_model: type[BaseModel] | None = None
    timeout_seconds: float = 15.0
    max_retries: int = 0
    summarize: Callable[[dict[str, Any]], str] | None = None
    action_type: str | None = None
    approval_title: str | None = None
    audit_target_fields: tuple[str, ...] = ()
    # 审批单富信息构造器：返回 {actionType, title, detail, risk}，把订单/金额等信息带给审批人
    approval_resolver: Callable[[ToolContext, dict[str, Any]], dict[str, Any]] | None = None
    # 审批通过后的真实执行函数。IRREVERSIBLE 工具的 ``func`` 通常只负责抛审批中断，
    # 真正的副作用写在 ``approved_func`` 里，由 HITL 在人工通过后调用。
    approved_func: Callable[..., dict[str, Any]] | None = None

    # --- 元信息 ------------------------------------------------------------
    def to_openai_tool(self) -> dict[str, Any]:
        """转 OpenAI function schema（供 bind_tools / MCP 描述）。"""
        parameters: dict[str, Any]
        if self.args_model is not None:
            parameters = self.args_model.model_json_schema(by_alias=True)
            parameters.pop("title", None)
        else:
            parameters = {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }

    def validate(self, raw: dict[str, Any]) -> dict[str, Any]:
        """参数校验并归一为工具函数可用的 kwargs。"""
        if self.args_model is None:
            return {"args": raw}
        try:
            model = self.args_model.model_validate(raw or {})
        except ValidationError as exc:
            raise param_invalid(
                f"工具 {self.name} 参数不合法: {_brief_validation(exc)}"
            ) from exc
        return model.model_dump(by_alias=False)

    def build_summary(self, data: dict[str, Any]) -> str:
        if self.summarize is not None:
            try:
                return str(self.summarize(data))[:300]
            except Exception:  # noqa: BLE001 - 摘要失败不影响主流程
                pass
        return f"{self.name} 执行完成"


def _brief_validation(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors()[:3]:
        location = ".".join(str(item) for item in error.get("loc", ()))
        parts.append(f"{location}: {error.get('msg')}")
    return "；".join(parts)


# ---------------------------------------------------------------------------
# 幂等 / 审计
# ---------------------------------------------------------------------------
def _load_idempotent(key: str) -> dict[str, Any] | None:
    try:
        with session_scope() as db:
            row = db.get(IdempotencyRecord, key)
            return dict(row.result) if row and row.result is not None else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取幂等记录失败: %s", exc)
        return None


def _save_idempotent(key: str, scope: str, result: dict[str, Any]) -> None:
    try:
        with session_scope() as db:
            if db.get(IdempotencyRecord, key) is not None:
                return
            db.add(
                IdempotencyRecord(
                    idem_key=key,
                    scope=scope,
                    result=mask_obj(result),
                    expires_at=None,
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("写入幂等记录失败: %s", exc)


# ──────── [CAP-15] 安全与合规 ────────
#   本处：写操作审计留痕（参数脱敏）
#   域约束：外部内容一律视为数据而非指令；PII 在统一出口脱敏，而非打印后再处理
def _audit(
    ctx: ToolContext,
    spec: ToolSpec,
    args: dict[str, Any],
    *,
    ok: bool,
    summary: str,
    error: str | None = None,
) -> None:
    target = ""
    for field_name in spec.audit_target_fields:
        value = args.get(field_name)
        if value:
            target = str(value)[:128]
            break
    try:
        with session_scope() as db:
            db.add(
                models_obs.AuditLog(
                    user_id=ctx.user_id,
                    action=f"tool.{spec.name}",
                    target=target or None,
                    detail={
                        "ok": ok,
                        "args": mask_obj(args),
                        "summary": sanitize_for_audit(summary, 300),
                        "error": sanitize_for_audit(error or "", 300) or None,
                        "sessionId": ctx.session_id,
                        "traceId": ctx.trace_id,
                        "risk": spec.risk.value,
                    },
                    ip=None,
                )
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("写审计日志失败: %s", exc)


# ---------------------------------------------------------------------------
# 执行器
# ---------------------------------------------------------------------------
class ToolExecutor:
    """统一的工具执行管线。"""

    # ──────── [CAP-05] 工具治理 ────────
    #   本处：统一执行管线（校验→审批→幂等→执行→审计）
    #   域约束：READ 可重试、WRITE 幂等、IRREVERSIBLE 必须走审批；新增工具只注册不改管线
    async def execute(
        self,
        spec: ToolSpec,
        args: dict[str, Any],
        ctx: ToolContext,
        call_id: str | None = None,
    ) -> ToolResult:
        call_id = call_id or f"call_{int(time.time() * 1000) % 10_000_000}"
        started = time.perf_counter()

        # 1) 参数校验
        try:
            kwargs = spec.validate(args)
        except Exception as exc:  # noqa: BLE001
            latency = int((time.perf_counter() - started) * 1000)
            record_tool_call(spec.name, spec.risk.value, "INVALID")
            return ToolResult(
                name=spec.name,
                call_id=call_id,
                ok=False,
                error=str(getattr(exc, "message", exc)),
                summary="参数不合法",
                latency_ms=latency,
                risk=spec.risk.value,
            )

        # 2) 不可逆操作：直接中断等审批
        if spec.risk is Risk.IRREVERSIBLE:
            resolved: dict[str, Any] = {}
            if spec.approval_resolver is not None:
                try:
                    resolved = await asyncio.to_thread(spec.approval_resolver, ctx, kwargs) or {}
                except Exception as exc:  # noqa: BLE001 - 解析失败也要中断，用原始参数兜底
                    logger.warning("审批详情构造失败 tool=%s err=%s", spec.name, exc)
            raise ApprovalRequired(
                tool=spec.name,
                args=args,
                action_type=str(resolved.get("actionType") or spec.action_type or spec.name.upper()),
                title=str(resolved.get("title") or spec.approval_title or f"{spec.name} 需要审批"),
                detail=resolved.get("detail") or mask_obj(args),
            )

        # 3) 幂等（WRITE 及以上）
        idem_key: str | None = None
        if spec.risk is Risk.WRITE:
            idem_key = idempotency_key(spec.name, ctx.user_id, json.dumps(args, sort_keys=True, default=str))
            cached = await asyncio.to_thread(_load_idempotent, idem_key)
            if cached is not None:
                latency = int((time.perf_counter() - started) * 1000)
                record_tool_call(spec.name, spec.risk.value, "CACHED")
                return ToolResult(
                    name=spec.name,
                    call_id=call_id,
                    ok=True,
                    data=cached,
                    summary="命中幂等记录：" + spec.build_summary(cached),
                    latency_ms=latency,
                    risk=spec.risk.value,
                    cached=True,
                )

        # 4) 执行（超时 + 仅 READ 重试）
        status = "OK"
        error: str | None = None
        data: dict[str, Any] = {}
        try:
            async with asyncio.timeout(spec.timeout_seconds):
                data = await self._invoke(spec, kwargs, ctx)
        except TimeoutError:
            status, error = "TIMEOUT", f"工具 {spec.name} 执行超时（{spec.timeout_seconds}s）"
        except Exception as exc:  # noqa: BLE001
            status, error = "ERROR", f"{type(exc).__name__}: {exc}"

        latency = int((time.perf_counter() - started) * 1000)
        ok = status == "OK" and isinstance(data, dict)
        summary = spec.build_summary(data) if ok else (error or "执行失败")

        # 5) 指标 / span / 审计 / 幂等
        record_tool_call(spec.name, spec.risk.value, status)
        if ctx.recorder is not None:
            ctx.recorder.record_span(
                name=f"tool.{spec.name}",
                span_type=SPAN_TOOL,
                inputs={"args": mask_obj(args), "risk": spec.risk.value},
                output={"ok": ok, "summary": summary[:200]},
                latency_ms=latency,
                status="OK" if ok else "ERROR",
                error=error,
            )
        if spec.risk in (Risk.WRITE, Risk.IRREVERSIBLE):
            await asyncio.to_thread(
                _audit, ctx, spec, args, ok=ok, summary=summary, error=error
            )
        if ok and idem_key:
            await asyncio.to_thread(_save_idempotent, idem_key, spec.name, data)

        return ToolResult(
            name=spec.name,
            call_id=call_id,
            ok=ok,
            data=data if ok else {},
            summary=summary,
            latency_ms=latency,
            error=error,
            risk=spec.risk.value,
        )

    # ──────── [CAP-14] 可靠性 / 降级 ────────
    #   本处：超时 + 仅 READ 重试（指数退避）
    #   域约束：降级必须可观测（指标 + degraded 标记）；重试只给幂等操作
    async def _invoke(self, spec: ToolSpec, kwargs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        """执行工具函数：同步函数丢线程池，READ 工具按配置重试。"""
        attempts = 1 + (spec.max_retries if spec.risk is Risk.READ else 0)
        if attempts > 1:
            retryer = AsyncRetrying(
                stop=stop_after_attempt(attempts),
                wait=wait_exponential(multiplier=0.2, max=2.0),
                retry=retry_if_exception_type(_RETRYABLE),
                reraise=True,
            )
            return await retryer(self._call_once, spec, kwargs, ctx)
        return await self._call_once(spec, kwargs, ctx)

    @staticmethod
    async def _call_once(spec: ToolSpec, kwargs: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        if inspect.iscoroutinefunction(spec.func):
            result = await spec.func(ctx, **kwargs)
        else:
            result = await asyncio.to_thread(spec.func, ctx, **kwargs)
        if not isinstance(result, dict):
            raise TypeError(f"工具 {spec.name} 必须返回 dict，实际为 {type(result).__name__}")
        return result


executor = ToolExecutor()


def default_summary(name: str, data: dict[str, Any]) -> str:
    """通用摘要（工具自定义摘要缺失时兜底）。"""
    for key in ("summary", "message", "latestEvent"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value[:200]
    if "items" in data and isinstance(data["items"], list):
        return f"命中 {len(data['items'])} 条"
    return f"{name} 完成"


def now_stamp() -> str:
    """审计/流水号用的时间戳。"""
    return utcnow().strftime("%Y%m%d%H%M%S")


__all__ = [
    "ApprovalRequired",
    "Risk",
    "ToolContext",
    "ToolExecutor",
    "ToolResult",
    "ToolSpec",
    "default_summary",
    "executor",
    "now_stamp",
]
