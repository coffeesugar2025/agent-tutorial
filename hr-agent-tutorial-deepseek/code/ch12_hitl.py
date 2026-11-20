"""第 12 章：Human-in-the-loop 与权限控制（LangGraph 版）。
用 StateGraph 把流程画出来：authorize → plan → approval → execute/rejected。
approval 节点里的 interrupt() 会暂停图，InMemorySaver 保存状态；
人审批后用 Command(resume=...) 恢复，只有 execute 节点才会产生副作用。
RBAC、职责分离、PII 脱敏、审计哈希链仍然自定义。
运行：python code/ch12_hitl.py
"""
from __future__ import annotations
import copy
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict
sys.path.insert(0, str(Path(__file__).resolve().parent))
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from common.data import employee, employees
from common.lc import MockChatModel
from common.text import mask_pii
GENESIS_HASH = "0" * 64
SALARY_DB: dict[str, str] = {item["id"]: item["salary_band"] for item in employees()}
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "employee": {"profile:read_self"},
    "hrbp": {"profile:read", "salary:read", "salary:propose"},
    "hrd": {"profile:read", "salary:read", "salary:propose", "salary:approve", "salary:execute", "audit:read"},
    "auditor": {"audit:read"},
}

class PermissionDenied(Exception):
    """请求人没有权限，或违反了职责分离。"""

class PermissionChecker:
    @staticmethod
    def can(role: str, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(role, set())
    @staticmethod
    def require(actor: str, role: str, permission: str) -> None:
        if not PermissionChecker.can(role, permission):
            raise PermissionDenied(f"{actor}（{role}）缺少权限 {permission}")
@dataclass

class ApprovalTicket:
    ticket_id: str
    employee_id: str
    employee_name: str
    from_band: str
    to_band: str
    requested_by: str
    requested_role: str
    contact: str
    required_role: str = "hrd"
    status: str = "pending"
    reason: str = ""
    def render(self) -> str:
        """给审批人看的摘要：联系方式必须脱敏。"""
        return mask_pii(
            f"{self.ticket_id} | {self.employee_name}({self.employee_id}) {self.from_band} → {self.to_band}"
            f" | 申请人 {self.requested_by}（{self.requested_role}） | 联系方式 {self.contact}"
            f" | 待 {self.required_role} 审批"
        )

def _hash_event(event: dict[str, Any]) -> str:
    body = {key: value for key, value in event.items() if key != "hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

def verify_chain(events: list[dict[str, Any]]) -> tuple[bool, int | None]:
    prev = GENESIS_HASH
    for index, event in enumerate(events):
        if event.get("prev_hash") != prev or event.get("hash") != _hash_event(event):
            return False, index
        prev = event["hash"]
    return True, None

class AuditChain:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.head = GENESIS_HASH
    def append(self, action: str, actor: str, detail: dict[str, Any]) -> None:
        event = {"seq": len(self.events), "action": action, "actor": actor, "detail": detail, "prev_hash": self.head}
        event["hash"] = _hash_event(event)
        self.events.append(event)
        self.head = event["hash"]
    def verify(self) -> tuple[bool, int | None]:
        return verify_chain(self.events)

class ApprovalGate:
    """审批单存储 + 审计。真实系统里票据要落库，这里放内存配合演示。"""
    def __init__(self, audit: AuditChain) -> None:
        self.audit = audit
        self.tickets: dict[str, ApprovalTicket] = {}
    def create_ticket(self, actor: str, role: str, employee_id: str, new_band: str) -> ApprovalTicket:
        target = employee(employee_id)
        if target is None:
            raise ValueError(f"员工不存在：{employee_id}")
        ticket = ApprovalTicket(
            ticket_id=f"AP-{len(self.tickets) + 1:04d}", employee_id=target["id"], employee_name=target["name"],
            from_band=SALARY_DB[target["id"]], to_band=new_band, requested_by=actor, requested_role=role,
            contact=f"{target['phone']} {target['email']}",
        )
        self.tickets[ticket.ticket_id] = ticket
        self.audit.append("approval_requested", actor, {"ticket": ticket.ticket_id, "to": new_band})
        return ticket

class ApprovalState(TypedDict, total=False):
    actor: str; role: str; instruction: str
    employee_id: str; new_band: str; ticket_id: str
    approved: bool; approver: str; approver_role: str
    reason: str; status: str; message: str

def authorize(state: ApprovalState) -> dict:
    try:
        PermissionChecker.require(state["actor"], state["role"], "salary:propose")
        return {"status": "authorized"}
    except PermissionDenied as exc:
        AUDIT.append("permission_denied", state["actor"], {"permission": "salary:propose"})
        return {"status": "denied", "message": f"已拒绝：{exc}"}

def plan(state: ApprovalState, model: MockChatModel) -> dict:
    response = model.invoke([
        SystemMessage("你是 HR 薪酬助理。调薪必须走审批，只能提出动作。"),
        HumanMessage(state["instruction"]),
    ])
    calls = getattr(response, "tool_calls", [])
    if not calls or calls[0]["name"] != "adjust_salary":
        return {"status": "error", "message": "模型没有给出 adjust_salary 工具调用"}
    args = calls[0]["args"]
    ticket = GATE.create_ticket(state["actor"], state["role"], args["employee_id"], args["new_band"])
    return {"status": "awaiting_approval", "employee_id": args["employee_id"], "new_band": args["new_band"],
            "ticket_id": ticket.ticket_id}

def approval(state: ApprovalState) -> dict:
    """interrupt 之前的代码在恢复时可能重跑，所以这里只读，不写库、不发通知。"""
    ticket = GATE.tickets[state["ticket_id"]]
    decision = interrupt({"ticket": ticket.render(), "to_band": ticket.to_band,
                          "requested_by": ticket.requested_by, "required_role": ticket.required_role})
    if not isinstance(decision, dict):
        decision = {"approved": bool(decision)}
    return {"approved": bool(decision.get("approved")), "approver": decision.get("approver", ""),
            "approver_role": decision.get("approver_role", ""), "reason": decision.get("reason", "")}

def execute(state: ApprovalState) -> dict:
    ticket = GATE.tickets[state["ticket_id"]]
    if state["approver"] == ticket.requested_by:
        AUDIT.append("separation_violation", state["approver"], {"ticket": ticket.ticket_id})
        return {"status": "separation_violation", "message": "职责分离：申请人不能审批自己提交的单据"}
    try:
        PermissionChecker.require(state["approver"], state["approver_role"], "salary:approve")
        PermissionChecker.require(state["approver"], state["approver_role"], "salary:execute")
    except PermissionDenied as exc:
        AUDIT.append("permission_denied", state["approver"], {"ticket": ticket.ticket_id})
        return {"status": "permission_denied", "message": f"已拒绝：{exc}"}
    ticket.status, ticket.reason = "approved", state.get("reason", "")
    before = SALARY_DB[ticket.employee_id]
    SALARY_DB[ticket.employee_id] = ticket.to_band
    AUDIT.append("salary_executed", state["approver"], {"ticket": ticket.ticket_id, "from": before, "to": ticket.to_band})
    return {"status": "done", "message": f"已按 {ticket.ticket_id} 将 {ticket.employee_name} 从 {before} 调整为 {ticket.to_band}。"}

def rejected(state: ApprovalState) -> dict:
    ticket = GATE.tickets[state["ticket_id"]]
    ticket.status, ticket.reason = "rejected", state.get("reason", "")
    AUDIT.append("approval_rejected", state["approver"], {"ticket": ticket.ticket_id, "reason": ticket.reason})
    return {"status": "rejected", "message": f"审批被拒绝（{ticket.reason}），未修改薪资。"}

def build_app(model: MockChatModel):
    graph = StateGraph(ApprovalState)
    nodes = {"authorize": authorize, "plan": lambda s: plan(s, model), "approval": approval,
             "execute": execute, "rejected": rejected}
    for name, node in nodes.items():
        graph.add_node(name, node)
    graph.add_edge(START, "authorize")
    graph.add_conditional_edges("authorize", lambda s: "plan" if s["status"] == "authorized" else "denied",
                                {"plan": "plan", "denied": END})
    graph.add_conditional_edges("plan", lambda s: "approval" if s["status"] == "awaiting_approval" else "error",
                                {"approval": "approval", "error": END})
    graph.add_conditional_edges("approval", lambda s: "execute" if s["approved"] else "rejected",
                                {"execute": "execute", "rejected": "rejected"})
    graph.add_edge("execute", END)
    graph.add_edge("rejected", END)
    return graph.compile(checkpointer=InMemorySaver())

AUDIT = AuditChain()
GATE = ApprovalGate(AUDIT)

def main() -> None:
    model = lambda eid, band: MockChatModel(script=[{"tool_calls": [{"name": "adjust_salary", "args": {"employee_id": eid, "new_band": band}}]}])
    print("=== 1. 角色与权限矩阵 ===")
    roles = ["employee", "hrbp", "hrd", "auditor"]
    print("权限点".ljust(16), " ".join(role.center(8) for role in roles))
    for permission in ["salary:propose", "salary:approve", "salary:execute", "audit:read"]:
        print(permission.ljust(16), " ".join(("Y" if PermissionChecker.can(r, permission) else "-").center(8) for r in roles))
    print("\n=== 2. 越权拒绝：员工给自己调薪 ===")
    denied = build_app(MockChatModel(script=[])).invoke(
        {"actor": "张伟", "role": "employee", "instruction": "把我自己的薪资档调到 P6-1"}, {"configurable": {"thread_id": "denied"}})
    print(f"{denied['status']}：{denied['message']}")
    assert denied["status"] == "denied" and SALARY_DB["E1001"] == "P5-2"
    print("\n=== 3. 审批通过：interrupt 暂停，Command(resume) 后执行 ===")
    app, cfg = build_app(model("E1001", "P6-1")), {"configurable": {"thread_id": "approve"}}
    first = app.invoke({"actor": "赵敏", "role": "hrbp",
                        "instruction": "张伟晋升 P6，把薪资档从 P5-2 调整到 P6-1。"}, cfg)
    payload = first["__interrupt__"][0].value
    print(f"interrupt 负载：{json.dumps(payload, ensure_ascii=False)}")
    print(f"审批前张伟仍为 {SALARY_DB['E1001']}；图停在 {app.get_state(cfg).next}")
    assert SALARY_DB["E1001"] == "P5-2" and "13800001001" not in payload["ticket"]
    print(f"checkpoint 状态可序列化：{len(json.dumps(dict(app.get_state(cfg).values), ensure_ascii=False))} 字节")
    done = app.invoke(Command(resume={"approved": True, "approver": "林芳", "approver_role": "hrd",
                                      "reason": "晋升调薪，预算已确认"}), cfg)
    print(f"{done['status']}：{done['message']}")
    assert done["status"] == "done" and SALARY_DB["E1001"] == "P6-1"
    print("\n=== 4. 职责分离：申请人不能审批自己的单 ===")
    app, cfg = build_app(model("E1002", "P6-2")), {"configurable": {"thread_id": "separation"}}
    first = app.invoke({"actor": "赵敏", "role": "hrbp", "instruction": "李娜绩效连续两季 A，申请调薪。"}, cfg)
    print(f"收到审批单：{first['__interrupt__'][0].value['ticket']}")
    separated = app.invoke(Command(resume={"approved": True, "approver": "赵敏", "approver_role": "hrbp"}), cfg)
    print(f"{separated['status']}：{separated['message']}")
    assert separated["status"] == "separation_violation" and SALARY_DB["E1002"] == "P6-1"
    print("\n=== 5. 审批拒绝：不修改任何数据 ===")
    app, cfg = build_app(model("E1002", "P6-2")), {"configurable": {"thread_id": "reject"}}
    app.invoke({"actor": "赵敏", "role": "hrbp", "instruction": "再次申请李娜调薪。"}, cfg)
    rejected_state = app.invoke(Command(resume={"approved": False, "approver": "林芳", "approver_role": "hrd",
                                                "reason": "季度调薪预算未批"}), cfg)
    print(f"{rejected_state['status']}：李娜仍为 {SALARY_DB['E1002']}")
    assert rejected_state["status"] == "rejected" and SALARY_DB["E1002"] == "P6-1"
    print("\n=== 6. 审计哈希链 ===")
    for event in AUDIT.events:
        print(f"  #{event['seq']} {event['action']:<20} {event['actor']:<4} prev={event['prev_hash'][:8]} hash={event['hash'][:8]}")
    ok, bad = AUDIT.verify()
    print(f"链校验：有效={ok}，坏点={bad}，共 {len(AUDIT.events)} 条")
    tampered = copy.deepcopy(AUDIT.events)
    index = next(i for i, event in enumerate(tampered) if event["action"] == "salary_executed")
    tampered[index]["detail"]["to"] = "P7-1"
    tampered_ok, tampered_bad = verify_chain(tampered)
    print(f"篡改第 {index} 条：有效={tampered_ok}，坏点={tampered_bad}")
    assert ok and bad is None and tampered_ok is False and tampered_bad == index
    assert PermissionChecker.can("hrd", "salary:execute") and not PermissionChecker.can("hrbp", "salary:execute") and len(AUDIT.events) >= 6
if __name__ == "__main__":
    main()
