"""HITL 补全（总纲 3.6）：事前批准 / 事中打断 / 事后审核 + 超时默认拒绝 + 自包含交接。

之前 hitl.py 有 approve/reject/edit/resume，但状态枚举里的 expired 没有扫描器，
也没有事中打断与事后审核，人工输入也没回注上下文。
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.capabilities.hitl import ApprovalStore, STORE


@dataclass
class ReviewItem:
    id: str
    kind: str                 # pre_approval | interrupt | post_review
    summary: str              # 自包含：不点开轨迹也能看懂
    trace_id: str
    decision_context: dict[str, Any]
    created_at: float = field(default_factory=time.time)
    timeout_seconds: float = 300.0
    status: str = "pending"
    decided_by: str = ""
    decision: str = ""
    reviewer_note: str = ""

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > self.timeout_seconds

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "summary": self.summary,
                "trace_id": self.trace_id, "decision_context": self.decision_context,
                "status": self.status, "decided_by": self.decided_by,
                "decision": self.decision, "reviewer_note": self.reviewer_note,
                "expired": self.expired, "timeout_seconds": self.timeout_seconds}


class HITLManager:
    def __init__(self, approvals: ApprovalStore | None = None) -> None:
        self.approvals = approvals or STORE
        self._items: dict[str, ReviewItem] = {}
        self._lock = threading.RLock()

    @staticmethod
    def self_contained_summary(tool: str, args: dict[str, Any], risk: str,
                               reason: str, trace_id: str) -> str:
        """交接摘要必须自包含：谁、什么操作、参数、风险、依据、轨迹号。"""
        return (f"【待审批】工具={tool}；参数={args}；风险={risk}；原因={reason}；"
                f"轨迹={trace_id}。该操作不可自动执行，请核对金额与归属后批准/拒绝/改写。")

    def submit(self, kind: str, tool: str, args: dict[str, Any], risk: str,
               reason: str, trace_id: str, timeout_seconds: float = 300.0) -> ReviewItem:
        item = ReviewItem("rev_" + uuid.uuid4().hex[:10], kind,
                          self.self_contained_summary(tool, args, risk, reason, trace_id),
                          trace_id, {"tool": tool, "args": args, "risk": risk, "reason": reason},
                          timeout_seconds=timeout_seconds)
        with self._lock:
            self._items[item.id] = item
        return item

    def scan_timeouts(self) -> dict[str, Any]:
        """超时策略：默认拒绝 > 放行（3.6 明确）。"""
        with self._lock:
            expired = []
            for it in self._items.values():
                if it.status == "pending" and it.expired:
                    it.status, it.decision, it.decided_by = "rejected", "timeout_default_reject", "system"
                    expired.append(it.id)
            return {"scanned": len(self._items), "expired_rejected": expired,
                    "default_action": "reject"}

    def decide(self, item_id: str, decision: str, reviewer: str = "reviewer",
               note: str = "", edited_args: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            it = self._items.get(item_id)
            if not it:
                return {"ok": False, "error": "审批项不存在"}
            if it.status != "pending":
                return {"ok": False, "error": f"已处理：{it.status}"}
            it.status = {"approve": "approved", "reject": "rejected", "edit": "edited"}.get(decision, "rejected")
            it.decision, it.decided_by, it.reviewer_note = decision, reviewer, note
        # 人工输入回注上下文：不是一句「继续」，而是结构化 decision_context
        injected = {"role": "system",
                    "content": f"人工审批结果：{it.decision}；审核人={reviewer}；备注={note}；"
                               f"后续参数={edited_args or it.decision_context['args']}。"
                               "请据此继续，不得重复提交原审批。"}
        return {"ok": True, "item": it.to_dict(), "context_injection": injected}

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"items": len(self._items),
                    "by_kind": {k: sum(1 for i in self._items.values() if i.kind == k)
                                for k in ("pre_approval", "interrupt", "post_review")},
                    "pending": sum(1 for i in self._items.values() if i.status == "pending")}


MANAGER = HITLManager()
