"""会话、审批、审计与幂等存储。

设计取舍（教程项目，够用且可讲清）：

- 默认全部放内存，进程重启即清空；设置环境变量 ``HR_APP_STATE_FILE``
  后会把状态写入一个 JSON 文件，便于本地演示“重启不丢数据”。
- 所有写操作都经过 ``threading.RLock``，因为 FastAPI 的同步路由运行在线程池里。
- 审计日志只追加，每条记录用 SHA-256 把上一条的 hash 串起来，
  ``verify_audit_chain()`` 可以发现任何篡改。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

try:  # 作为包导入（pytest / uvicorn）
    from . import config
except ImportError:  # python app/backend/main.py
    import config  # type: ignore[no-redef]

from common.data import employee as find_employee
from common.text import mask_pii

GENESIS_HASH = "0" * 64


def _short_id(prefix: str, length: int = 4) -> str:
    return f"{prefix}{uuid.uuid4().hex[:length]}"


@dataclass
class Session:
    id: str
    employee_id: str
    messages: list[dict] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    approval_id: str | None = None
    created_at: str = ""
    updated_at: str = ""


class Store:
    """内存存储 + 可选 JSON 落盘。"""

    def __init__(
        self,
        clock: Callable[[], datetime] | None = None,
        state_path: str | Path | None = None,
    ) -> None:
        self._clock = clock or config.now
        env_path = os.getenv("HR_APP_STATE_FILE", "").strip()
        self._state_path = Path(state_path) if state_path else (Path(env_path) if env_path else None)
        self._lock = threading.RLock()

        self.sessions: dict[str, Session] = {}
        self.approvals: dict[str, dict] = {}
        self.audits: list[dict] = []
        self.idempotency: dict[str, str] = {}
        self.leave_requests: dict[str, dict] = {}
        self.interviews: dict[str, dict] = {}
        self.onboardings: dict[str, dict] = {}
        self.escalations: dict[str, dict] = {}
        self.salary_overrides: dict[str, str] = {}

        self._leave_seq = 0
        self._onboarding_seq = 0
        self._escalation_seq = 900
        self._load()

    # ------------------------------------------------------------------
    # 时间与基础工具
    # ------------------------------------------------------------------
    def now(self) -> datetime:
        return self._clock()

    def stamp(self, moment: datetime | None = None) -> str:
        return config.iso(moment or self.now())

    @staticmethod
    def _digest(prev_hash: str, payload: dict) -> str:
        material = prev_hash + "|" + json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # 会话
    # ------------------------------------------------------------------
    def get_session(self, session_id: str) -> Session | None:
        with self._lock:
            return self.sessions.get(session_id)

    def get_or_create_session(self, session_id: str | None, employee_id: str) -> Session:
        with self._lock:
            if session_id and session_id in self.sessions:
                session = self.sessions[session_id]
                session.employee_id = employee_id
                session.updated_at = self.stamp()
                return session
            sid = session_id or _short_id("s_", 8)
            timestamp = self.stamp()
            session = Session(
                id=sid,
                employee_id=employee_id,
                created_at=timestamp,
                updated_at=timestamp,
            )
            self.sessions[sid] = session
            self._persist()
            return session

    def append_turn(self, session: Session, user_text: str, assistant_text: str) -> None:
        with self._lock:
            session.messages.append({"role": "user", "content": user_text})
            session.messages.append({"role": "assistant", "content": assistant_text})
            overflow = len(session.messages) - config.SESSION_MAX_MESSAGES
            if overflow > 0:
                del session.messages[:overflow]
            session.updated_at = self.stamp()
            self._persist()

    def add_fact(self, session: Session, fact: str) -> None:
        if not fact:
            return
        with self._lock:
            if fact in session.facts:
                session.facts.remove(fact)
            session.facts.append(fact)
            if len(session.facts) > config.MEMORY_MAX_FACTS:
                del session.facts[: len(session.facts) - config.MEMORY_MAX_FACTS]
            session.updated_at = self.stamp()
            self._persist()

    def memory_payload(self, employee_id: str, facts: list[str] | None = None) -> dict:
        person = find_employee(employee_id)
        if person:
            employee = {
                "id": person["id"],
                "name": person["name"],
                "department": person["department"],
                "city": person["city"],
            }
        else:
            employee = {}
        return {"employee": employee, "facts": list(facts or [])}

    def session_payload(self, session_id: str) -> dict | None:
        with self._lock:
            session = self.sessions.get(session_id)
            if session is None:
                return None
            approval = None
            if session.approval_id:
                candidate = self.approvals.get(session.approval_id)
                if candidate and candidate.get("status") == "pending":
                    approval = dict(candidate)
            return {
                "session_id": session.id,
                "messages": [dict(message) for message in session.messages],
                "approval": approval,
                "memory": self.memory_payload(session.employee_id, session.facts),
            }

    # ------------------------------------------------------------------
    # 审批
    # ------------------------------------------------------------------
    def create_approval(
        self,
        *,
        action: str,
        summary: str,
        risk: str,
        payload: dict,
        session_id: str | None,
        requested_by: str,
    ) -> dict:
        with self._lock:
            for existing in self.approvals.values():
                if (
                    existing.get("status") == "pending"
                    and existing.get("session_id") == session_id
                    and existing.get("action") == action
                    and existing.get("payload") == payload
                    and existing.get("requested_by") == requested_by
                ):
                    return dict(existing)
            approval = {
                "id": _short_id("ap_"),
                "action": action,
                "summary": summary,
                "risk": risk,
                "status": "pending",
                "payload": dict(payload),
                "requested_by": requested_by,
                "created_at": self.stamp(),
                "session_id": session_id,
            }
            self.approvals[approval["id"]] = approval
            if session_id and session_id in self.sessions:
                self.sessions[session_id].approval_id = approval["id"]
            self._persist()
            return dict(approval)

    def get_approval(self, approval_id: str) -> dict | None:
        with self._lock:
            approval = self.approvals.get(approval_id)
            return dict(approval) if approval else None

    def pending_approval_for_session(self, session_id: str) -> dict | None:
        with self._lock:
            for approval in self.approvals.values():
                if (
                    approval.get("session_id") == session_id
                    and approval.get("status") == "pending"
                ):
                    return dict(approval)
            return None

    def decide_approval(
        self, approval_id: str, decision: str, approver: str, comment: str | None
    ) -> dict | None:
        """把 pending 改成 approved/rejected。已处理的单据不会被再次修改。"""
        with self._lock:
            approval = self.approvals.get(approval_id)
            if approval is None:
                return None
            if approval["status"] != "pending":
                return dict(approval)
            approval["status"] = "approved" if decision == "approve" else "rejected"
            approval["decided_by"] = approver
            approval["decided_at"] = self.stamp()
            approval["comment"] = comment
            session = self.sessions.get(approval.get("session_id") or "")
            if session and session.approval_id == approval_id:
                session.approval_id = None
            self._persist()
            return dict(approval)

    def set_approval_status(self, approval_id: str, status: str, result: str) -> dict | None:
        with self._lock:
            approval = self.approvals.get(approval_id)
            if approval is None:
                return None
            approval["status"] = status
            approval["result"] = result
            self._persist()
            return dict(approval)

    def clear_persisted_state(self) -> None:
        """删除可选的 JSON 落盘文件，确保“重置演示数据”后不会被旧状态覆盖。"""
        with self._lock:
            if self._state_path is not None and self._state_path.is_file():
                try:
                    self._state_path.unlink()
                except OSError as exc:
                    print(f"[store] 清理状态文件失败：{exc}")

    # ------------------------------------------------------------------
    # 审计链
    # ------------------------------------------------------------------
    def record_audit(self, actor: str, action: str, target: str, result: str) -> dict:
        with self._lock:
            payload = {
                "seq": len(self.audits) + 1,
                "actor": actor,
                "action": action,
                "target": target,
                "result": result,
                "at": self.stamp(),
            }
            prev_hash = self.audits[-1]["hash"] if self.audits else GENESIS_HASH
            digest = self._digest(prev_hash, payload)
            record = {
                "id": f"au_{digest[:8]}",
                **payload,
                "prev_hash": prev_hash,
                "hash": digest,
            }
            self.audits.append(record)
            self._persist()
            return dict(record)

    def verify_audit_chain(self) -> bool:
        with self._lock:
            prev_hash = GENESIS_HASH
            for record in self.audits:
                if record.get("prev_hash") != prev_hash:
                    return False
                payload = {
                    key: record.get(key)
                    for key in ("seq", "actor", "action", "target", "result", "at")
                }
                if record.get("hash") != self._digest(prev_hash, payload):
                    return False
                prev_hash = record["hash"]
            return True

    def audit_events(self) -> list[dict]:
        with self._lock:
            return [dict(record) for record in self.audits]

    # ------------------------------------------------------------------
    # 幂等
    # ------------------------------------------------------------------
    def recall_idempotent(self, key: str) -> str | None:
        with self._lock:
            return self.idempotency.get(key)

    def remember_idempotent(self, key: str, value: str) -> None:
        with self._lock:
            self.idempotency[key] = value
            self._persist()

    # ------------------------------------------------------------------
    # 请假
    # ------------------------------------------------------------------
    def create_leave_request(
        self,
        *,
        employee_id: str,
        start_date: str,
        end_date: str,
        days: float,
        leave_type: str,
        idempotency_key: str,
        actor: str,
    ) -> tuple[dict, bool]:
        with self._lock:
            existing_id = self.idempotency.get(idempotency_key)
            if existing_id and existing_id in self.leave_requests:
                return dict(self.leave_requests[existing_id]), True
            self._leave_seq += 1
            request_id = f"LV{self.now():%Y%m%d}{self._leave_seq:03d}"
            request = {
                "id": request_id,
                "employee_id": employee_id,
                "start_date": start_date,
                "end_date": end_date,
                "days": days,
                "leave_type": leave_type,
                "status": "submitted",
                "created_at": self.stamp(),
                "requested_by": actor,
            }
            self.leave_requests[request_id] = request
            self.idempotency[idempotency_key] = request_id
            self._persist()
            return dict(request), False

    def overlapping_leave(
        self, employee_id: str, start_date: str, end_date: str
    ) -> list[dict]:
        with self._lock:
            return [
                dict(request)
                for request in self.leave_requests.values()
                if request["employee_id"] == employee_id
                and request.get("status") in {"submitted", "approved"}
                and not (request["end_date"] < start_date or request["start_date"] > end_date)
            ]

    # ------------------------------------------------------------------
    # 转人工 / 面试 / 入职
    # ------------------------------------------------------------------
    def create_escalation(
        self, *, actor: str, reason: str, category: str = "其他"
    ) -> dict:
        with self._lock:
            safe_reason = mask_pii(reason)
            key = f"escalate:{actor}:{safe_reason}"
            existing_id = self.idempotency.get(key)
            if existing_id and existing_id in self.escalations:
                return dict(self.escalations[existing_id])
            self._escalation_seq += 1
            ticket_id = f"T{self.now():%Y}{self._escalation_seq:03d}"
            ticket = {
                "id": ticket_id,
                "employee_id": actor,
                "category": category,
                "title": "Agent 转人工",
                "description": safe_reason,
                "status": "open",
                "priority": "P2",
                "created_at": self.stamp(),
                "assignee": None,
                "sla_hours": 24,
            }
            self.escalations[ticket_id] = ticket
            self.idempotency[key] = ticket_id
            self.record_audit(actor, "escalate", ticket_id, safe_reason)
            self._persist()
            return dict(ticket)

    def create_interview(
        self,
        *,
        candidate_id: str,
        candidate_name: str,
        scheduled_at: str,
        interviewer: str,
        mode: str,
        approved_by: str,
    ) -> dict:
        with self._lock:
            interview = {
                "id": _short_id("it_"),
                "candidate_id": candidate_id,
                "candidate_name": candidate_name,
                "scheduled_at": scheduled_at,
                "interviewer": interviewer,
                "mode": mode,
                "status": "scheduled",
                "approved_by": approved_by,
                "created_at": self.stamp(),
            }
            self.interviews[interview["id"]] = interview
            self._persist()
            return dict(interview)

    def create_onboarding(
        self,
        *,
        candidate_id: str,
        candidate_name: str,
        start_date: str,
        actor: str,
        steps: list[dict],
    ) -> dict:
        with self._lock:
            self._onboarding_seq += 1
            record_id = f"OB{self.now():%Y%m%d}{self._onboarding_seq:03d}"
            record = {
                "id": record_id,
                "candidate_id": candidate_id,
                "candidate_name": candidate_name,
                "start_date": start_date,
                "status": "in_progress",
                "stage": steps[0]["name"] if steps else "待启动",
                "steps": steps,
                "created_by": actor,
                "created_at": self.stamp(),
            }
            self.onboardings[record_id] = record
            self._persist()
            return dict(record)

    # ------------------------------------------------------------------
    # 薪资（审批通过后才会调用）
    # ------------------------------------------------------------------
    def get_salary_band(self, employee_id: str) -> str | None:
        with self._lock:
            if employee_id in self.salary_overrides:
                return self.salary_overrides[employee_id]
            person = find_employee(employee_id)
            return person["salary_band"] if person else None

    def set_salary_band(self, employee_id: str, band: str) -> None:
        with self._lock:
            self.salary_overrides[employee_id] = band
            self._persist()

    # ------------------------------------------------------------------
    # 可选 JSON 落盘
    # ------------------------------------------------------------------
    def _state_snapshot(self) -> dict:
        return {
            "sessions": {
                sid: {
                    "id": session.id,
                    "employee_id": session.employee_id,
                    "messages": session.messages,
                    "facts": session.facts,
                    "approval_id": session.approval_id,
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                }
                for sid, session in self.sessions.items()
            },
            "approvals": self.approvals,
            "audits": self.audits,
            "idempotency": self.idempotency,
            "leave_requests": self.leave_requests,
            "interviews": self.interviews,
            "onboardings": self.onboardings,
            "escalations": self.escalations,
            "salary_overrides": self.salary_overrides,
            "counters": {
                "leave": self._leave_seq,
                "onboarding": self._onboarding_seq,
                "escalation": self._escalation_seq,
            },
        }

    def _persist(self) -> None:
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
            tmp_path.write_text(
                json.dumps(self._state_snapshot(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(self._state_path)
        except OSError as exc:  # 落盘失败不应影响在线请求
            print(f"[store] 状态落盘失败：{exc}")

    def _load(self) -> None:
        if self._state_path is None or not self._state_path.is_file():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[store] 状态加载失败，使用空状态：{exc}")
            return
        for sid, raw in (data.get("sessions") or {}).items():
            self.sessions[sid] = Session(
                id=raw.get("id", sid),
                employee_id=raw.get("employee_id", ""),
                messages=list(raw.get("messages") or []),
                facts=list(raw.get("facts") or []),
                approval_id=raw.get("approval_id"),
                created_at=raw.get("created_at", ""),
                updated_at=raw.get("updated_at", ""),
            )
        self.approvals = dict(data.get("approvals") or {})
        self.audits = list(data.get("audits") or [])
        self.idempotency = dict(data.get("idempotency") or {})
        self.leave_requests = dict(data.get("leave_requests") or {})
        self.interviews = dict(data.get("interviews") or {})
        self.onboardings = dict(data.get("onboardings") or {})
        self.escalations = dict(data.get("escalations") or {})
        self.salary_overrides = dict(data.get("salary_overrides") or {})
        counters = data.get("counters") or {}
        self._leave_seq = int(counters.get("leave", 0))
        self._onboarding_seq = int(counters.get("onboarding", 0))
        self._escalation_seq = int(counters.get("escalation", 900))
