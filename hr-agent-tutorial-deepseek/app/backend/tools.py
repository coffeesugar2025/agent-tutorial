"""10 个 HR 工具：只读 / 写 / 敏感写。

约定：
- 工具只做业务动作，不负责“怎么措辞”；回复模板在 ``agent.py``。
- 敏感工具（``schedule_interview`` / ``adjust_salary``）不会在这里执行，
  而是抛出 ``SensitiveAction``，由 Agent 创建审批单并中断。
- 所有写工具都带幂等键，重复调用返回同一业务单号。
- 候选人手机号、邮箱统一用 ``common.text.mask_pii`` 脱敏后再返回。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path

try:  # 作为包导入
    from . import config
except ImportError:  # python app/backend/main.py
    import config  # type: ignore[no-redef]

from common.data import (
    candidate as find_candidate,
    candidates,
    employee as find_employee,
    employees,
    tickets,
    POLICY_DIR,
)
from common.text import mask_pii

SENSITIVE_TOOLS = ("schedule_interview", "adjust_salary")

TOOL_SPECS: list[dict] = [
    {"name": "get_leave_balance", "type": "read", "description": "查询年假 / 病假余额"},
    {"name": "search_policy", "type": "read", "description": "制度混合检索，返回可引用片段"},
    {"name": "check_leave_eligibility", "type": "read", "description": "校验余额、提前天数与日期冲突"},
    {"name": "submit_leave_request", "type": "write", "description": "幂等提交请假申请"},
    {"name": "search_candidates", "type": "read", "description": "按技能 / 年限 / 岗位筛候选人"},
    {"name": "get_candidate", "type": "read", "description": "候选人详情（联系方式脱敏）"},
    {"name": "schedule_interview", "type": "sensitive", "description": "创建面试日程，必须审批"},
    {"name": "adjust_salary", "type": "sensitive", "description": "调整薪资带宽，必须审批"},
    {"name": "start_onboarding", "type": "write", "description": "启动入职状态机"},
    {"name": "get_ticket", "type": "read", "description": "查询工单详情"},
]

TICKET_STATUS_LABELS = {
    "open": "待处理",
    "in_progress": "处理中",
    "resolved": "已解决",
    "closed": "已关闭",
}

_ONBOARDING_STEPS = [
    "确认 offer 与入职日期",
    "收集入职材料",
    "创建员工档案与工号",
    "申请账号与邮箱",
    "准备工位、电脑、工牌",
    "指定入职导师",
    "Day 1 签约与设备发放",
    "30 / 60 / 90 天转正评估",
]

BAND_RE = re.compile(r"^[PM]\d-\d$")


class ToolError(Exception):
    """可预期的业务错误，Agent 会把它变成一句人话，而不是 500。"""


class PermissionDenied(ToolError):
    """当前演示身份没有权限。"""


class SensitiveAction(ToolError):
    """敏感操作被拦截，需要人工审批。"""

    def __init__(self, action: str, summary: str, risk: str, payload: dict) -> None:
        super().__init__(summary)
        self.action = action
        self.summary = summary
        self.risk = risk
        self.payload = payload


def _parse_date(value: str, field_label: str = "日期") -> date:
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError) as exc:
        raise ToolError(f"{field_label}格式应为 YYYY-MM-DD，收到：{value!r}") from exc


def _parse_datetime(value: str) -> datetime:
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ToolError(f"时间格式不合法：{value!r}，请使用 ISO 8601，如 2026-12-05T14:00:00+08:00") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=config.TZ)
    return moment


def _workdays_between(start: date, end: date) -> int:
    """统计 (start, end) 之间的工作日数量。"""
    count = 0
    cursor = start + timedelta(days=1)
    while cursor < end:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


def masked_candidate(person: dict) -> dict:
    return {
        "id": person["id"],
        "name": person["name"],
        "position": person["position"],
        "city": person["city"],
        "years": person["years"],
        "education": person["education"],
        "current_status": person["current_status"],
        "expected_salary_k": person["expected_salary_k"],
        "skills": list(person["skills"]),
        "stage": person["stage"],
        "score": person["score"],
        "available_date": person["available_date"],
        "phone": mask_pii(person.get("phone", "")),
        "email": mask_pii(person.get("email", "")),
    }


def _mask_note(text: str) -> str:
    """面试记录里可能夹带联系方式；只遮真手机号 / 带域名邮箱，避免误伤 Recall@5。"""
    text = re.sub(r"(1[3-9]\d)\d{4}(\d{4})", r"\1****\2", text)
    text = re.sub(r"([\w.+-]{1,3})[\w.+-]*(@[\w-]+\.[A-Za-z]{2,})", r"\1***\2", text)
    return text


def _interview_note(candidate_id: str) -> str | None:
    notes_dir = config.DATA_DIR / "interview-notes"
    if not notes_dir.is_dir():
        return None
    for path in sorted(notes_dir.glob(f"{candidate_id}-*.md")):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not text:
            continue
        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        return _mask_note(" / ".join(lines[:3])[:220])
    return None


class Toolbox:
    def __init__(self, store, rag) -> None:
        self.store = store
        self.rag = rag

    # ------------------------------------------------------------------
    # 基础校验
    # ------------------------------------------------------------------
    @staticmethod
    def _require_employee(identifier: str | None) -> dict:
        key = (identifier or "").strip()
        person = find_employee(key) or next(
            (item for item in employees() if item["name"] == key), None
        )
        if not person:
            raise ToolError(f"员工不存在：{key or '（空）'}")
        return person

    @staticmethod
    def _require_candidate(identifier: str | None) -> dict:
        key = (identifier or "").strip()
        person = find_candidate(key) or next(
            (item for item in candidates() if item["name"] == key), None
        )
        if not person:
            raise ToolError(f"候选人不存在：{key or '（空）'}")
        return person

    def _require_hr(self, actor: str, reason: str = "该操作仅限 HR 角色") -> None:
        if actor not in config.HR_ROLES:
            raise PermissionDenied(f"你的演示身份没有权限：{reason}")

    # ------------------------------------------------------------------
    # 1. 余额
    # ------------------------------------------------------------------
    def get_leave_balance(self, employee_id: str, actor: str) -> dict:
        target = employee_id or actor
        if actor != target and actor not in config.HR_ROLES:
            raise PermissionDenied("只能查询自己的假期余额")
        person = self._require_employee(target)
        leave = person["leave"]
        annual_remaining = leave["annual_total"] - leave["annual_used"]
        sick_remaining = leave["sick_total"] - leave["sick_used"]
        return {
            "employee_id": person["id"],
            "name": person["name"],
            "year": self.store.now().year,
            "annual_total": leave["annual_total"],
            "annual_used": leave["annual_used"],
            "annual_remaining": annual_remaining,
            "sick_total": leave["sick_total"],
            "sick_used": leave["sick_used"],
            "sick_remaining": sick_remaining,
        }

    # ------------------------------------------------------------------
    # 2. 制度检索
    # ------------------------------------------------------------------
    def search_policy(
        self,
        query: str,
        *,
        top_k: int = 4,
        include_archived: bool = False,
        include_drafts: bool = False,
    ) -> list[dict]:
        hits = self.rag.search(
            query,
            top_k=top_k,
            include_archived=include_archived,
            include_drafts=include_drafts,
            today=self.store.now().date(),
        )
        return [{key: value for key, value in hit.items() if not key.startswith("_")} for hit in hits]

    # ------------------------------------------------------------------
    # 3. 请假资格
    # ------------------------------------------------------------------
    def check_leave_eligibility(
        self,
        employee_id: str,
        start_date: str,
        end_date: str,
        days: float,
        leave_type: str,
        actor: str,
        ignore_request_id: str | None = None,
    ) -> dict:
        person = self._require_employee(employee_id)
        if actor != person["id"] and actor not in config.HR_ROLES:
            raise PermissionDenied("只能为自己提交请假申请")
        start = _parse_date(start_date, "开始日期")
        end = _parse_date(end_date, "结束日期")
        today = self.store.now().date()
        reasons: list[str] = []
        leave = person["leave"]
        type_key = leave_type if leave_type in {"annual", "sick"} else "annual"
        remaining = (
            leave["annual_total"] - leave["annual_used"]
            if type_key == "annual"
            else leave["sick_total"] - leave["sick_used"]
        )
        if end < start:
            reasons.append("结束日期早于开始日期")
        if days <= 0:
            reasons.append("请假天数必须大于 0")
        if abs(days * 2 - round(days * 2)) > 1e-9:
            reasons.append("年假最小请假单位为 0.5 天")
        if days > remaining:
            reasons.append(f"余额不足：当前剩余 {remaining} 天，申请 {days:g} 天")
        if start < today:
            reasons.append(f"开始日期 {start_date} 早于今天 {today.isoformat()}")
        advance = _workdays_between(today, start) if start >= today else 0
        if advance < 3:
            reasons.append(f"需至少提前 3 个工作日申请，当前仅提前 {advance} 个工作日")
        conflicts = [
            item
            for item in self.store.overlapping_leave(person["id"], start_date, end_date)
            if item["id"] != ignore_request_id
        ]
        if conflicts:
            reasons.append("与已有请假申请日期重叠：" + "、".join(item["id"] for item in conflicts))
        return {
            "ok": not reasons,
            "reasons": reasons,
            "employee_id": person["id"],
            "leave_type": type_key,
            "days": days,
            "remaining": remaining,
            "advance_workdays": advance,
            "required_advance_workdays": 3,
            "conflicts": conflicts,
        }

    # ------------------------------------------------------------------
    # 4. 提交请假（写，幂等）
    # ------------------------------------------------------------------
    def submit_leave_request(
        self,
        employee_id: str,
        start_date: str,
        end_date: str,
        days: float,
        leave_type: str,
        actor: str,
        idempotency_key: str | None = None,
    ) -> dict:
        person = self._require_employee(employee_id)
        if actor != person["id"] and actor not in config.HR_ROLES:
            raise PermissionDenied("只能为自己提交请假申请")
        key = idempotency_key or (
            f"leave:{person['id']}:{start_date}:{end_date}:{days:g}:{leave_type}"
        )
        request, replay = self.store.create_leave_request(
            employee_id=person["id"],
            start_date=start_date,
            end_date=end_date,
            days=days,
            leave_type=leave_type,
            idempotency_key=key,
            actor=actor,
        )
        if not replay:
            self.store.record_audit(
                actor,
                "submit_leave_request",
                request["id"],
                f"{start_date} 至 {end_date}，{days:g} 天{leave_type}",
            )
        leave = person["leave"]
        projected = leave["annual_total"] - leave["annual_used"] - (
            days if leave_type == "annual" else 0
        )
        return {
            "request": request,
            "replay": replay,
            "projected_annual_remaining": projected,
            "idempotency_key": key,
        }

    # ------------------------------------------------------------------
    # 5. 候选人搜索
    # ------------------------------------------------------------------
    def search_candidates(
        self,
        *,
        actor: str,
        skills: list[str] | None = None,
        position: str | None = None,
        min_years: int = 0,
        city: str | None = None,
        keyword: str | None = None,
        top_k: int = 5,
    ) -> dict:
        self._require_hr(actor, "候选人数据仅招聘相关角色可访问")
        wanted_skills = [skill.casefold() for skill in (skills or []) if skill]
        matched: list[dict] = []
        for person in candidates():
            hits = [
                skill
                for skill in person["skills"]
                if any(
                    wanted in skill.casefold() or skill.casefold() in wanted
                    for wanted in wanted_skills
                )
            ]
            if wanted_skills and not hits:
                continue
            if position and position not in person["position"]:
                continue
            if person["years"] < min_years:
                continue
            if city and city not in person["city"]:
                continue
            if keyword:
                haystack = " ".join(
                    [person["name"], person["position"], person["note"], *person["skills"]]
                ).casefold()
                if keyword.casefold() not in haystack:
                    continue
            score = person["score"] + len(hits) * 6 + min(person["years"], 10)
            matched.append({**person, "_match_score": score, "_matched_skills": hits})
        matched.sort(key=lambda item: (-item["_match_score"], item["id"]))
        top = matched[: max(1, top_k)]
        return {
            "count": len(matched),
            "criteria": {
                "skills": skills or [],
                "position": position,
                "min_years": min_years,
                "city": city,
                "keyword": keyword,
            },
            "candidate_ids": [item["id"] for item in top],
            "candidates": [
                {
                    **masked_candidate(item),
                    "matched_skills": item["_matched_skills"],
                }
                for item in top
            ],
        }

    # ------------------------------------------------------------------
    # 6. 候选人详情
    # ------------------------------------------------------------------
    def get_candidate(self, identifier: str, actor: str) -> dict:
        self._require_hr(actor, "候选人数据仅招聘相关角色可访问")
        person = self._require_candidate(identifier)
        note = _interview_note(person["id"])
        return {
            **masked_candidate(person),
            "note": person["note"],
            "interview_note": note,
        }

    # ------------------------------------------------------------------
    # 7. 安排面试（敏感写，只创建审批单）
    # ------------------------------------------------------------------
    def schedule_interview(
        self,
        *,
        actor: str,
        candidate: str,
        scheduled_at: str,
        interviewer: str | None = None,
        mode: str = "视频",
    ) -> dict:
        self._require_hr(actor, "面试安排仅招聘相关角色可发起")
        person = self._require_candidate(candidate)
        moment = _parse_datetime(scheduled_at)
        if moment <= self.store.now():
            raise ToolError("面试时间必须在未来")
        interviewer_id = (interviewer or "E2001").strip()
        interviewer_person = find_employee(interviewer_id)
        if not interviewer_person:
            raise ToolError(f"面试官不存在：{interviewer_id}")
        display = moment.strftime("%Y-%m-%d %H:%M")
        summary = (
            f"为{person['name']}（{person['id']}）安排 {display} 的面试"
            f"（面试官 {interviewer_id} {interviewer_person['name']}）"
        )
        raise SensitiveAction(
            "schedule_interview",
            summary,
            "high",
            {
                "candidate_id": person["id"],
                "candidate_name": person["name"],
                "scheduled_at": moment.isoformat(timespec="seconds"),
                "interviewer": interviewer_id,
                "mode": mode,
            },
        )

    # ------------------------------------------------------------------
    # 8. 调薪（敏感写，只创建审批单）
    # ------------------------------------------------------------------
    def adjust_salary(
        self,
        *,
        actor: str,
        employee: str,
        new_band: str,
        reason: str | None = None,
    ) -> dict:
        if actor not in config.SALARY_APPROVERS:
            raise PermissionDenied("调薪仅 HRBP 或 HR 总监可以发起")
        person = self._require_employee(employee)
        band = (new_band or "").strip().upper()
        if not BAND_RE.match(band):
            raise ToolError(f"薪资带宽格式应为 P5-2 / M1-2 这种形式，收到：{new_band!r}")
        old_band = self.store.get_salary_band(person["id"]) or person["salary_band"]
        if old_band == band:
            raise ToolError(f"{person['name']}的薪资带宽已经是 {band}，无需调整")
        summary = (
            f"将{person['name']}（{person['id']}）薪资带宽从 {old_band} 调整为 {band}"
        )
        raise SensitiveAction(
            "adjust_salary",
            summary,
            "high",
            {
                "employee_id": person["id"],
                "employee_name": person["name"],
                "old_band": old_band,
                "new_band": band,
                "reason": reason or "未填写",
            },
        )

    # ------------------------------------------------------------------
    # 9. 入职状态机
    # ------------------------------------------------------------------
    def start_onboarding(
        self, *, actor: str, candidate: str, start_date: str
    ) -> dict:
        self._require_hr(actor, "入职流程仅 HR 角色可启动")
        person = self._require_candidate(candidate)
        start = _parse_date(start_date, "入职日期")
        if start < self.store.now().date():
            raise ToolError("入职日期不能早于今天")
        key = f"onboarding:{person['id']}:{start.isoformat()}"
        existing_id = self.store.recall_idempotent(key)
        if existing_id and existing_id in self.store.onboardings:
            record = self.store.onboardings[existing_id]
            return {
                "onboarding": dict(record),
                "candidate": masked_candidate(person),
                "step_count": len(record["steps"]),
                "replay": True,
            }
        steps = [
            {"name": name, "status": "pending" if index else "doing"}
            for index, name in enumerate(_ONBOARDING_STEPS)
        ]
        record = self.store.create_onboarding(
            candidate_id=person["id"],
            candidate_name=person["name"],
            start_date=start.isoformat(),
            actor=actor,
            steps=steps,
        )
        self.store.remember_idempotent(key, record["id"])
        self.store.record_audit(
            actor,
            "start_onboarding",
            record["id"],
            f"{person['name']}（{person['id']}）入职日期 {start.isoformat()}",
        )
        return {
            "onboarding": record,
            "candidate": masked_candidate(person),
            "step_count": len(steps),
            "replay": False,
        }

    # ------------------------------------------------------------------
    # 10. 工单
    # ------------------------------------------------------------------
    def get_ticket(self, ticket_id: str, actor: str) -> dict:
        key = (ticket_id or "").strip().upper()
        record = next((item for item in tickets() if item["id"].upper() == key), None)
        if record is None:
            record = self.store.escalations.get(key)
        if record is None:
            raise ToolError(f"工单不存在：{ticket_id}")
        if record["employee_id"] != actor and actor not in config.HR_ROLES:
            raise PermissionDenied("只能查看自己的工单；跨人查询需要 HR 角色")
        assignee = find_employee(record.get("assignee") or "")
        return {
            **record,
            "status_label": TICKET_STATUS_LABELS.get(record["status"], record["status"]),
            "assignee_name": assignee["name"] if assignee else None,
        }

    # ------------------------------------------------------------------
    # 审批通过后的真正执行
    # ------------------------------------------------------------------
    def execute_schedule_interview(self, payload: dict, approver: str) -> tuple[str, dict]:
        """LangChain 敏感工具在 HITL 恢复后调用的执行入口。"""
        return self._execute_schedule_interview(payload, approver)

    def execute_adjust_salary(self, payload: dict, approver: str) -> tuple[str, dict]:
        """LangChain 敏感工具在 HITL 恢复后调用的执行入口。"""
        return self._execute_adjust_salary(payload, approver)

    def execute_approval(self, approval: dict, approver: str) -> tuple[str, dict]:
        action = approval["action"]
        payload = approval.get("payload") or {}
        if action == "adjust_salary":
            return self._execute_adjust_salary(payload, approver)
        if action == "schedule_interview":
            return self._execute_schedule_interview(payload, approver)
        raise ToolError(f"未知审批动作：{action}")

    def _execute_adjust_salary(self, payload: dict, approver: str) -> tuple[str, dict]:
        person = self._require_employee(payload.get("employee_id", ""))
        old_band = self.store.get_salary_band(person["id"]) or payload.get("old_band")
        new_band = payload["new_band"]
        self.store.set_salary_band(person["id"], new_band)
        result = (
            f"已按 {new_band} 更新{person['name']}（{person['id']}）的薪资带宽"
            f"（原 {old_band}），并写入审计日志。"
        )
        audit = self.store.record_audit(
            approver, "adjust_salary", person["id"], f"{old_band} → {new_band}"
        )
        return result, audit

    def _execute_schedule_interview(self, payload: dict, approver: str) -> tuple[str, dict]:
        person = self._require_candidate(payload.get("candidate_id", ""))
        interview = self.store.create_interview(
            candidate_id=person["id"],
            candidate_name=person["name"],
            scheduled_at=payload["scheduled_at"],
            interviewer=payload.get("interviewer", "E2001"),
            mode=payload.get("mode", "视频"),
            approved_by=approver,
        )
        display = payload["scheduled_at"].replace("T", " ")[:16]
        result = (
            f"已为{person['name']}（{person['id']}）安排 {display} 的面试"
            f"（面试官 {payload.get('interviewer', 'E2001')}），并写入审计日志。"
        )
        audit = self.store.record_audit(
            approver,
            "schedule_interview",
            f"{person['id']}:{interview['id']}",
            result,
        )
        return result, audit


def policy_file(doc_id: str) -> Path | None:
    """调试辅助：按 doc_id 找制度原文件。"""
    for path in sorted(POLICY_DIR.glob("*.md")):
        if doc_id in path.stem:
            return path
    return None
