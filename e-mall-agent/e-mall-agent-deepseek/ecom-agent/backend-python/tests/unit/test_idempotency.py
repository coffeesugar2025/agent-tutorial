"""幂等与审批单元测试：幂等键、WRITE 去重、READ 不去重、IRREVERSIBLE 中断与审计。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-17] 评测与迭代  （支撑）
# 职责：幂等与审批单元测试：幂等键、WRITE 去重、READ 不去重、IRREVERSIBLE 中断与审计
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import asyncio
import uuid

import pytest
from pydantic import BaseModel

from app.common.ids import idempotency_key
from app.infra.models_obs import AuditLog, IdempotencyRecord
from app.tools.base import ApprovalRequired, Risk, ToolContext, ToolExecutor, ToolSpec

pytestmark = pytest.mark.unit


class _Args(BaseModel):
    value: int = 1


def _ctx(user_id: int) -> ToolContext:
    return ToolContext(user_id=user_id, session_id=1, trace_id=f"trace-{uuid.uuid4().hex[:8]}")


def _make_spec(risk: Risk, *, name: str | None = None) -> tuple[ToolSpec, dict[str, int]]:
    calls = {"n": 0}

    def _run(ctx: ToolContext, value: int = 1) -> dict[str, object]:
        calls["n"] += 1
        return {"value": value, "calls": calls["n"], "tool": name or "demo"}

    spec = ToolSpec(
        name=name or f"demo_{risk.value.lower()}",
        description="幂等测试工具",
        func=_run,
        risk=risk,
        args_model=_Args,
        action_type="REFUND" if risk is Risk.IRREVERSIBLE else None,
        approval_title="退款需要审批" if risk is Risk.IRREVERSIBLE else None,
    )
    return spec, calls


@pytest.fixture
def executor() -> ToolExecutor:
    return ToolExecutor()


@pytest.fixture
def user_id() -> int:
    # 每个用例独立用户，避免幂等记录串味
    return int(uuid.uuid4().hex[:8], 16)


def test_idempotency_key_is_stable_and_scoped():
    first = idempotency_key("create_refund_request", 1, '{"orderNo":"SO1"}')
    second = idempotency_key("create_refund_request", 1, '{"orderNo":"SO1"}')
    other_user = idempotency_key("create_refund_request", 2, '{"orderNo":"SO1"}')

    assert first == second
    assert first != other_user
    assert first.startswith("create_refund_request:")
    assert len(first) <= 160


def test_write_tool_hits_idempotency_on_second_call(executor, user_id):
    spec, calls = _make_spec(Risk.WRITE)
    ctx = _ctx(user_id)

    first = asyncio.run(executor.execute(spec, {"value": 7}, ctx))
    second = asyncio.run(executor.execute(spec, {"value": 7}, ctx))

    assert first.ok is True
    assert first.cached is False
    assert second.ok is True
    assert second.cached is True
    assert second.data["calls"] == 1
    assert calls["n"] == 1


def test_write_tool_different_args_are_not_cached(executor, user_id):
    spec, calls = _make_spec(Risk.WRITE)
    ctx = _ctx(user_id)

    asyncio.run(executor.execute(spec, {"value": 1}, ctx))
    asyncio.run(executor.execute(spec, {"value": 2}, ctx))

    assert calls["n"] == 2


def test_read_tool_is_not_idempotent_cached(executor, user_id):
    from app.infra.db import session_scope

    spec, calls = _make_spec(Risk.READ)
    ctx = _ctx(user_id)

    first = asyncio.run(executor.execute(spec, {"value": 3}, ctx))
    second = asyncio.run(executor.execute(spec, {"value": 3}, ctx))

    assert first.cached is False and second.cached is False
    assert calls["n"] == 2
    with session_scope() as db:
        assert db.query(IdempotencyRecord).filter(IdempotencyRecord.scope == spec.name).count() == 0


def test_irreversible_tool_raises_approval_required(executor, user_id):
    spec, calls = _make_spec(Risk.IRREVERSIBLE)

    with pytest.raises(ApprovalRequired) as excinfo:
        asyncio.run(executor.execute(spec, {"value": 1}, _ctx(user_id)))

    assert excinfo.value.tool == spec.name
    assert excinfo.value.action_type == "REFUND"
    assert excinfo.value.title == "退款需要审批"
    assert calls["n"] == 0  # 未审批不执行


def test_write_tool_writes_audit_log(executor, user_id):
    spec, _ = _make_spec(Risk.WRITE)
    asyncio.run(executor.execute(spec, {"value": 5}, _ctx(user_id)))

    from app.infra.db import session_scope

    with session_scope() as db:
        rows = db.query(AuditLog).filter(AuditLog.action == f"tool.{spec.name}").all()
    assert rows
    assert rows[-1].detail["args"]["value"] == 5
    assert rows[-1].detail["risk"] == "WRITE"


def test_invalid_args_are_rejected_before_execution(executor, user_id):
    spec, calls = _make_spec(Risk.WRITE)

    result = asyncio.run(executor.execute(spec, {"value": "not-a-number"}, _ctx(user_id)))

    assert result.ok is False
    assert result.error
    assert "参数" in result.error
    assert calls["n"] == 0
