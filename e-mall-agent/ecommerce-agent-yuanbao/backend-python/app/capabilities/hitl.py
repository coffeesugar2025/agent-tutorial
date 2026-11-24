"""Human-in-the-loop：审批队列 / interrupt-resume 语义。

与 1.4.6+ HumanInTheLoopMiddleware(interrupt_on, interrupt_mode) 的关系：
  内置件依赖 LangGraph interrupt + checkpointer，在真实图里挂起等待 Command(resume=...)。
  本模块提供等价的、可脱离具体图运行时的审批存储与恢复语义（便于离线测试与 API 演示），
  生产可直接替换为内置件 + 同一个 ApprovalStore 作为外部工单系统。

流程：submit（挂起，返回 task_id）→ decide（approve / reject / edit）→ resume（执行或丢弃）。
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from app.services import catalog

WRITE_TOOLS = {"place_order", "apply_refund", "change_address", "cancel_order"}
HIGH_RISK_WORDS = ("下单", "支付", "退款", "改地址", "取消订单")


@dataclass
class ApprovalRequest:
    id: str
    tool: str
    args: dict[str, Any]
    reason: str
    risk: str
    status: str = "pending"       # pending / approved / rejected / edited / executed / expired
    created_at: float = field(default_factory=time.time)
    decided_at: float | None = None
    decided_by: str = ""
    edited_args: dict[str, Any] | None = None
    result: Any = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "tool": self.tool, "args": self.args,
                "reason": self.reason, "risk": self.risk, "status": self.status,
                "created_at": self.created_at, "decided_at": self.decided_at,
                "decided_by": self.decided_by, "edited_args": self.edited_args,
                "result": self.result, "error": self.error}


class ApprovalStore:
    def __init__(self) -> None:
        self._items: dict[str, ApprovalRequest] = {}
        self._lock = threading.RLock()

    def submit(self, tool: str, args: dict[str, Any], reason: str,
               risk: str = "high") -> ApprovalRequest:
        with self._lock:
            req = ApprovalRequest(id="apr_" + uuid.uuid4().hex[:10], tool=tool,
                                  args=dict(args), reason=reason, risk=risk)
            self._items[req.id] = req
            return req

    def get(self, req_id: str) -> ApprovalRequest | None:
        with self._lock:
            return self._items.get(req_id)

    def list_pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return [r.to_dict() for r in self._items.values() if r.status == "pending"]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {}
            for r in self._items.values():
                counts[r.status] = counts.get(r.status, 0) + 1
            return {"total": len(self._items), "by_status": counts}

    def decide(self, req_id: str, decision: str, decided_by: str = "reviewer",
               edited_args: dict[str, Any] | None = None) -> ApprovalRequest:
        """decision: approve | reject | edit（edit 必须给 edited_args）。"""
        with self._lock:
            req = self._items.get(req_id)
            if req is None:
                raise KeyError(f"审批单不存在：{req_id}")
            if req.status != "pending":
                raise ValueError(f"审批单已处理：{req.status}")
            if decision not in ("approve", "reject", "edit"):
                raise ValueError("decision 必须是 approve / reject / edit")
            if decision == "edit" and not edited_args:
                raise ValueError("edit 必须提供 edited_args")
            req.status = {"approve": "approved", "reject": "rejected", "edit": "edited"}[decision]
            req.decided_at = time.time()
            req.decided_by = decided_by
            req.edited_args = edited_args
            return req

    def mark_executed(self, req_id: str, result: Any = None, error: str = "") -> None:
        with self._lock:
            req = self._items[req_id]
            req.status = "executed" if not error else "rejected"
            req.result, req.error = result, error


STORE = ApprovalStore()

_SAFE_EXECUTORS: dict[str, Callable[..., dict[str, Any]]] = {
    # 演示用的「写操作」执行器：仍然只读，避免真的改数据
    "place_order": lambda **kw: {"ok": True, "message": "已登记下单意向（演示不落库）", "args": kw},
    "apply_refund": lambda **kw: {"ok": True, "message": "已登记退款申请（演示不落库）", "args": kw},
    "change_address": lambda **kw: {"ok": True, "message": "已登记改址申请（演示不落库）", "args": kw},
    "cancel_order": lambda **kw: {"ok": True, "message": "已登记取消申请（演示不落库）", "args": kw},
}


def requires_approval(tool: str, args: dict[str, Any] | None = None,
                      message: str = "") -> tuple[bool, str, str]:
    """风险判定：写工具、高风险词、超大金额都需人工审批。"""
    args = args or {}
    if tool in WRITE_TOOLS:
        return True, f"工具 {tool} 属于写操作", "high"
    if any(w in message for w in HIGH_RISK_WORDS):
        return True, "用户请求包含写操作关键词", "high"
    qty = args.get("quantity")
    amount = args.get("amount")
    if isinstance(amount, (int, float)) and amount > 5000:
        return True, f"金额 {amount} 超过自动执行阈值", "high"
    if isinstance(qty, int) and qty > 50:
        return True, f"数量 {qty} 超过自动执行阈值", "medium"
    return False, "", "low"


def submit_if_needed(tool: str, args: dict[str, Any], message: str = "",
                     store: ApprovalStore | None = None) -> dict[str, Any]:
    """工具调用前置闸门：只读自动放行，高风险挂起。"""
    s = store or STORE
    needed, reason, risk = requires_approval(tool, args, message)
    if not needed:
        return {"requires_approval": False, "risk": risk, "status": "auto_allowed"}
    req = s.submit(tool, args, reason, risk)
    return {"requires_approval": True, "risk": risk, "reason": reason,
            "status": "pending", "approval_id": req.id,
            "resume_hint": f"POST /v2/approvals/{req.id}/decide 然后 /resume"}


def resume(approval_id: str, store: ApprovalStore | None = None) -> dict[str, Any]:
    """审批通过后恢复执行；拒绝则丢弃；edit 用改写后的参数执行。"""
    s = store or STORE
    req = s.get(approval_id)
    if req is None:
        raise KeyError(f"审批单不存在：{approval_id}")
    if req.status == "pending":
        return {"status": "still_pending", "approval_id": approval_id}
    if req.status == "rejected":
        return {"status": "discarded", "reason": "人工拒绝", "approval_id": approval_id}
    if req.status == "executed":
        return {"status": "already_executed", "result": req.result,
                "approval_id": approval_id,
                "idempotent_hit": True}

    eff_args = req.edited_args if req.status == "edited" and req.edited_args else req.args
    was_edited = req.status == "edited"
    executor = _SAFE_EXECUTORS.get(req.tool)
    if executor is None:
        # 非写工具走只读领域函数，演示统一映射到商品检索
        result = catalog.search_products(keyword=str(eff_args.get("keyword", "")), limit=1)
    else:
        result = executor(**eff_args)
    s.mark_executed(approval_id, result=result)
    return {"status": "executed", "approval_id": approval_id,
            "tool": req.tool, "effective_args": eff_args,
            "original_args": req.args, "result": result,
            "edited": was_edited}


def hitl_spec() -> dict[str, Any]:
    return {
        "builtin_equivalent": "HumanInTheLoopMiddleware(interrupt_on={...}, interrupt_mode='per_call')",
        "flow": ["submit（interrupt）", "decide（approve/reject/edit）", "resume（Command(resume=...)）"],
        "policy": "10 个 MCP 工具全部只读 → 自动放行；place_order/apply_refund/change_address/cancel_order → 挂起",
        "store": "ApprovalStore（生产替换为工单系统 / 持久化 DB）",
    }
