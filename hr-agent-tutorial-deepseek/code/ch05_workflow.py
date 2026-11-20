"""第 05 章：Workflow 与状态机 —— 用 LangGraph 把入职流程画成图。

运行：python code/ch05_workflow.py
StateGraph + InMemorySaver + thread_id：守卫、崩溃恢复、终止补偿都看得见。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from common.data import candidate

State = StrEnum("State", {name: name for name in [
    "CREATED", "DOCS_VERIFIED", "CONTRACT_SIGNED", "ACCOUNTS_READY",
    "EQUIPMENT_READY", "DAY1_READY", "PROBATION", "TERMINATED"]})
Event = StrEnum("Event", {name: name for name in [
    "VERIFY_DOCS", "SIGN_CONTRACT", "PROVISION_ACCOUNTS", "ASSIGN_EQUIPMENT",
    "DAY1_CHECK", "START_PROBATION", "FAIL_BACKGROUND_CHECK"]})

class WorkflowError(Exception): pass
class IllegalTransition(WorkflowError): pass
class GuardFailed(WorkflowError): pass
class SimulatedCrash(WorkflowError): pass

@dataclass(frozen=True)
class Transition:
    target: State
    node: str

@dataclass
class AccountService:
    """模拟外部账号系统：它有自己的存储，不依赖 LangGraph checkpoint。"""

    accounts: dict[tuple[str, str], str] = field(default_factory=dict)

    def ensure(self, employee_id: str, systems: list[str]) -> dict:
        created, existing = [], []
        for system in systems:
            if (employee_id, system) in self.accounts:
                existing.append(system)
            else:
                self.accounts[(employee_id, system)] = f"{employee_id}-{system}"
                created.append(system)
        return {"created": created, "existing": existing}

    def revoke(self, employee_id: str) -> list[str]:
        systems = [system for employee, system in self.accounts if employee == employee_id]
        for system in systems:
            del self.accounts[(employee_id, system)]
        return systems

ACCOUNTS = AccountService()
SYSTEMS = ["域账号", "企业邮箱", "IM", "VPN"]
def docs_complete(state: "OnboardingState") -> tuple[bool, str]:
    missing = [name for name in ("id_card", "education") if not state.get("docs", {}).get(name)]
    return (not missing, f"缺少材料 {missing}")
def has_resignation(state: "OnboardingState") -> tuple[bool, str]:
    return (state.get("docs", {}).get("resignation", False), "缺少离职证明，不能签署劳动合同")
def day1_ready(state: "OnboardingState") -> tuple[bool, str]:
    effects = state.get("effects", {})
    checks = {"accounts": Event.PROVISION_ACCOUNTS.value in effects,
              "equipment": Event.ASSIGN_EQUIPMENT.value in effects,
              "mentor": bool(state.get("mentor"))}
    failed = [name for name, ok in checks.items() if not ok]
    return (not failed, f"未完成 {failed}")

def advance(state: "OnboardingState", event: Event, target: State, result: dict) -> dict:
    history = state.get("history", []) + [
        {"from": state["state"], "event": event.value, "to": target.value, "result": result}
    ]
    return {"state": target.value, "history": history, "effects": {**state.get("effects", {}), event.value: result}}
def verify_docs(state: "OnboardingState") -> dict:
    ok, reason = docs_complete(state)
    if not ok:
        raise GuardFailed(f"docs_complete 未通过：{reason}")
    result = {"verified": [name for name, ok in state["docs"].items() if ok]}
    return advance(state, Event.VERIFY_DOCS, State.DOCS_VERIFIED, result)
def sign_contract(state: "OnboardingState") -> dict:
    ok, reason = has_resignation(state)
    if not ok:
        raise GuardFailed(f"has_resignation 未通过：{reason}")
    result = {"contract_id": f"CT-{state['employee_id']}", "type": "劳动合同 + 保密协议"}
    return advance(state, Event.SIGN_CONTRACT, State.CONTRACT_SIGNED, result)
def provision_accounts(state: "OnboardingState") -> dict:
    result = ACCOUNTS.ensure(state["employee_id"], SYSTEMS)
    if state.get("crash_on") == Event.PROVISION_ACCOUNTS.value:
        raise SimulatedCrash("PROVISION_ACCOUNTS 动作已完成，checkpoint 尚未落盘")
    return advance(state, Event.PROVISION_ACCOUNTS, State.ACCOUNTS_READY, result)
def assign_equipment(state: "OnboardingState") -> dict:
    result = {"laptop": f"NB-{state['employee_id']}", "badge": f"B-{state['employee_id']}", "mentor": state["mentor"]}
    return advance(state, Event.ASSIGN_EQUIPMENT, State.EQUIPMENT_READY, result)
def day1_check(state: "OnboardingState") -> dict:
    ok, reason = day1_ready(state)
    if not ok:
        raise GuardFailed(f"day1_ready 未通过：{reason}")
    return advance(state, Event.DAY1_CHECK, State.DAY1_READY, {"checked": ["账号", "设备", "工位", "导师"]})
def start_probation(state: "OnboardingState") -> dict:
    result = {"probation_end": "2027-03-01", "goal": "90 天内独立交付一个算法服务"}
    return advance(state, Event.START_PROBATION, State.PROBATION, result)
def terminate(state: "OnboardingState") -> dict:
    result = {"reason": "背景调查未通过", "revoked": ACCOUNTS.revoke(state["employee_id"]),
              "offboarding_ticket": f"OFF-{state['employee_id']}"}
    return advance(state, Event.FAIL_BACKGROUND_CHECK, State.TERMINATED, result)

TRANSITIONS: dict[tuple[State, Event], Transition] = {
    (State.CREATED, Event.VERIFY_DOCS): Transition(State.DOCS_VERIFIED, "verify_docs"),
    (State.DOCS_VERIFIED, Event.SIGN_CONTRACT): Transition(State.CONTRACT_SIGNED, "sign_contract"),
    (State.CONTRACT_SIGNED, Event.PROVISION_ACCOUNTS): Transition(State.ACCOUNTS_READY, "provision_accounts"),
    (State.ACCOUNTS_READY, Event.ASSIGN_EQUIPMENT): Transition(State.EQUIPMENT_READY, "assign_equipment"),
    (State.EQUIPMENT_READY, Event.DAY1_CHECK): Transition(State.DAY1_READY, "day1_check"),
    (State.DAY1_READY, Event.START_PROBATION): Transition(State.PROBATION, "start_probation"),
}
for state in (State.DOCS_VERIFIED, State.CONTRACT_SIGNED, State.ACCOUNTS_READY, State.EQUIPMENT_READY, State.DAY1_READY):
    TRANSITIONS[(state, Event.FAIL_BACKGROUND_CHECK)] = Transition(State.TERMINATED, "terminate")

NODES = {"verify_docs": verify_docs, "sign_contract": sign_contract, "provision_accounts": provision_accounts,
         "assign_equipment": assign_equipment, "day1_check": day1_check, "start_probation": start_probation,
         "terminate": terminate}

class OnboardingState(TypedDict, total=False):
    employee_id: str
    state: str
    docs: dict[str, bool]
    mentor: str
    history: list[dict]
    effects: dict[str, Any]
    event: str
    next: str
    crash_on: str
def dispatch(state: OnboardingState) -> dict:
    current, event = state["state"], state["event"]
    transition = TRANSITIONS.get((current, event))
    if transition is None:
        allowed = [item.value for (source, item) in TRANSITIONS if source == current]
        raise IllegalTransition(f"{current} 不允许 {event}；可执行 {allowed or '无（终态）'}")
    return {"next": transition.node}

def build_graph():
    graph = StateGraph(OnboardingState)
    graph.add_node("dispatch", dispatch)
    for name, node in NODES.items():
        graph.add_node(name, node)
        graph.add_edge(name, END)
    graph.add_edge(START, "dispatch")
    graph.add_conditional_edges("dispatch", lambda state: state["next"], {name: name for name in NODES})
    return graph.compile(checkpointer=InMemorySaver())

def initial_state(cid: str, docs: dict[str, bool]) -> dict:
    person = candidate(cid)
    return {"employee_id": person["id"], "state": State.CREATED.value, "docs": docs, "mentor": "E1007 孙悦",
            "history": [], "effects": {}, "event": "", "crash_on": ""}

def main() -> None:
    graph = build_graph()
    config = {"configurable": {"thread_id": "onboarding-C001"}}
    print("=== 1. StateGraph 状态机 ===")
    for (state, event), transition in TRANSITIONS.items():
        print(f"  {state} --{event}--> {transition.target} ({transition.node})")

    print("\n=== 2. 守卫：缺离职证明，签约被拒 ===")
    graph.invoke({**initial_state("C001", {"id_card": True, "education": True}), "event": Event.VERIFY_DOCS.value}, config)
    try:
        graph.invoke({"event": Event.SIGN_CONTRACT.value}, config)
    except GuardFailed as exc:
        print(f"  拒绝：{exc}")
    snapshot = graph.get_state(config)
    graph.update_state(config, {"docs": {**snapshot.values["docs"], "resignation": True}})
    graph.invoke({"event": Event.SIGN_CONTRACT.value}, config)
    print(f"  补交离职证明后：{graph.get_state(config).values['state']}")
    print("\n=== 3. 崩溃：动作已执行，checkpoint 还没写 ===")
    graph.update_state(config, {"crash_on": Event.PROVISION_ACCOUNTS.value})
    try:
        graph.invoke({"event": Event.PROVISION_ACCOUNTS.value}, config)
    except SimulatedCrash as exc:
        print(f"  崩溃：{exc}")
    snapshot = graph.get_state(config)
    print(f"  checkpoint 状态={snapshot.values['state']}，外部账号={len(ACCOUNTS.accounts)} 个")
    print("\n=== 4. 恢复：从同一 saver 重新 invoke，账号不重复开通 ===")
    graph.update_state(config, {"crash_on": ""})
    graph.invoke({"event": Event.PROVISION_ACCOUNTS.value}, config)
    effects = graph.get_state(config).values["effects"]["PROVISION_ACCOUNTS"]
    print(f"  新建={effects['created']} 已存在={effects['existing']}")
    for event in (Event.ASSIGN_EQUIPMENT, Event.DAY1_CHECK, Event.START_PROBATION):
        graph.invoke({"event": event.value}, config)
        print(f"  {event} -> {graph.get_state(config).values['state']}")
    print("\n=== 5. 非法转移：终态与跳步都必须拒绝 ===")
    illegal = 0
    for thread, payload in (("onboarding-C001", {"event": Event.SIGN_CONTRACT.value}),
                            ("onboarding-C008", {**initial_state("C008", {}), "event": Event.PROVISION_ACCOUNTS.value})):
        target = {"configurable": {"thread_id": thread}}
        try:
            graph.invoke(payload, target)
        except IllegalTransition as exc:
            illegal += 1
            print(f"  拒绝：{exc}")
    print("\n=== 6. 背调未通过：终止并回收账号 ===")
    wang_config = {"configurable": {"thread_id": "onboarding-C003"}}
    graph.invoke({**initial_state("C003", {"id_card": True, "education": True, "resignation": True}),
                  "event": Event.VERIFY_DOCS.value}, wang_config)
    for event in (Event.SIGN_CONTRACT, Event.PROVISION_ACCOUNTS, Event.FAIL_BACKGROUND_CHECK):
        graph.invoke({"event": event.value}, wang_config)
    wang = graph.get_state(wang_config).values
    print(f"  状态={wang['state']} 回收={wang['effects']['FAIL_BACKGROUND_CHECK']['revoked']}")
    print("\n=== 7. 断言 ===")
    assert graph.get_state(config).values["state"] == State.PROBATION.value
    assert effects["created"] == [] and len(effects["existing"]) == 4
    assert wang["state"] == State.TERMINATED.value and not any(emp == "C003" for emp, _ in ACCOUNTS.accounts)
    assert illegal == 2
    print("全部通过：守卫、崩溃恢复、幂等开通、非法转移、终止补偿都符合预期。")
if __name__ == "__main__":
    main()
