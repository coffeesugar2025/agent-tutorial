"""第 13 章：Multi-Agent——校招小组如何协作（LangGraph 版）。

StateGraph 的 supervisor 节点按 CaseState.stage 分派，各 Agent 节点用
Command(goto="supervisor") 交回控制权；共享 state 里保存 cases/log/rounds/tokens，
合规一票否决，轮次与 token 预算到点即停。
运行：python code/ch13_multi_agent.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from common.data import candidates
from common.lc import MockChatModel
from common.text import mask_pii

MAX_ROUNDS = 12
SCREEN_PASS = 80
SALARY_CAP_K = 40
TOKEN_BUDGET = 6000
SINGLE_PROMPT_TOKENS = 150
SINGLE_COMPLETION_TOKENS = 25
MESSAGE_OVERHEAD_TOKENS = 40

PROMPTS = {
    "recruiter": "你是校招招聘专员，只负责简历初筛，不做合规判断。",
    "compliance": "你是招聘合规专员。薪酬带宽、在职竞业、隐私授权是一票否决项。",
    "interviewer": "你是面试官，负责排期并给出面试结论。",
}
MODELS = {
    "recruiter": MockChatModel(script=lambda messages, tools: {"content": "简历与岗位匹配，建议进入合规检查。"}),
    "compliance": MockChatModel(script=lambda messages, tools: {"content": "已核对薪酬带宽、在职状态与隐私字段，结论见规则判定。"}),
    "interviewer": MockChatModel(script=lambda messages, tools: {"content": "沟通与项目深度达标，建议进入 Offer 池。"}),
}
ROUTE = {"new": "recruiter", "screening_done": "compliance", "compliance_ok": "interviewer"}


class TeamState(TypedDict, total=False):
    cases: list[dict]
    log: list[dict]
    rounds: int
    current: str
    tokens: dict[str, int]
    finished: bool
    stop_reason: str


def think(agent: str, prompt: str) -> tuple[str, int]:
    response = MODELS[agent].invoke([SystemMessage(PROMPTS[agent]), HumanMessage(prompt)])
    usage = getattr(response, "usage_metadata", None) or {}
    return (response.content or "").strip(), usage.get("total_tokens", 0)


def current_case(state: TeamState) -> dict:
    return copy.deepcopy(next(case for case in state["cases"] if case["id"] == state["current"]))


def emit(state: TeamState, agent: str, topic: str, case: dict, text: str, **payload) -> dict:
    message = {"round": state["rounds"], "sender": agent, "topic": topic, "case_id": case["id"], "text": text, "payload": payload}
    print(f"[轮 {message['round']:02d}] {agent:>10} → supervisor | {case['id']} | {topic:<10} | {text}")
    return message


def finish_round(state: TeamState, case: dict, message: dict, agent: str, used: int) -> Command:
    others = [item for item in state["cases"] if item["id"] != case["id"]]
    tokens = {**state["tokens"], agent: state["tokens"].get(agent, 0) + used}
    return Command(goto="supervisor", update={"cases": others + [case], "log": state["log"] + [message], "tokens": tokens})


def recruiter_node(state: TeamState) -> Command:
    case = current_case(state)
    candidate = case["candidate"]
    passed = candidate["score"] >= SCREEN_PASS
    text, used = think("recruiter", f"候选人 {candidate['name']}，{candidate['years']} 年经验，技能 {candidate['skills']}，评分 {candidate['score']}。用一句话给出筛选结论。")
    case["checks"].append("screening")
    case["stage"] = "screening_done" if passed else "rejected"
    case["done"] = not passed
    conclusion = text if passed else "评分低于 80 分线"
    message = emit(state, "recruiter", "screening", case, f"{candidate['name']} {candidate['score']} 分 → {'通过初筛' if passed else '淘汰'}；{conclusion}", passed=passed)
    return finish_round(state, case, message, "recruiter", used)


def compliance_node(state: TeamState) -> Command:
    case = current_case(state)
    candidate = case["candidate"]
    veto = candidate["expected_salary_k"] > SALARY_CAP_K
    review = "；在职满 6 年，需补离职证明与竞业核查" if candidate["current_status"] == "在职" and candidate["years"] >= 6 else ""
    masked = mask_pii(f"{candidate['phone']} {candidate['email']}")
    # 合规结论由规则给出，LLM 只把结论写成说明，不能改判。
    text, used = think("compliance", f"候选人 {candidate['name']}，期望 {candidate['expected_salary_k']}k，当前{candidate['current_status']}，联系 {masked}。用一句话说明合规结论。")
    case["checks"].append("compliance")
    if veto:
        case.update(done=True, blocked=True, stage="blocked",
                    block_reason=f"期望薪资 {candidate['expected_salary_k']}k 超出校招薪酬带宽 18-35k{review}")
        message = emit(state, "compliance", "compliance", case, f"{candidate['name']} 一票否决：{case['block_reason']}", veto=True)
    else:
        case["stage"] = "compliance_ok"
        message = emit(state, "compliance", "compliance", case, f"{candidate['name']} 合规通过（展示层 {masked}）{review}；{text}", veto=False)
    return finish_round(state, case, message, "compliance", used)


def interviewer_node(state: TeamState) -> Command:
    case = current_case(state)
    candidate = case["candidate"]
    text, used = think("interviewer", f"候选人 {candidate['name']} 通过初筛与合规，可到岗 {candidate['available_date']}。用一句话给出面试安排与结论。")
    case["checks"].append("interview")
    case.update(stage="interview_done", done=True)
    message = emit(state, "interviewer", "interview", case, f"{candidate['name']} 一面安排 {candidate['available_date']} 10:00；{text}")
    return finish_round(state, case, message, "interviewer", used)


NODES = {"recruiter": recruiter_node, "compliance": compliance_node, "interviewer": interviewer_node}


def supervisor_node(state: TeamState) -> Command:
    if state.get("finished"):
        return Command(goto=END)
    if state["rounds"] >= MAX_ROUNDS:
        return Command(goto=END, update={"finished": True, "stop_reason": f"达到轮次上限 {MAX_ROUNDS}"})
    if sum(state["tokens"].values()) >= TOKEN_BUDGET:
        return Command(goto=END, update={"finished": True, "stop_reason": f"达到 token 预算 {TOKEN_BUDGET}"})
    pending = [case for case in state["cases"] if not case["done"] and not case["blocked"]]
    if not pending:
        return Command(goto=END, update={"finished": True, "stop_reason": "队列为空（全部完成/淘汰/否决）"})
    case = pending[0]
    return Command(goto=ROUTE[case["stage"]], update={"rounds": state["rounds"] + 1, "current": case["id"]})


def build_app():
    graph = StateGraph(TeamState)
    graph.add_node("supervisor", supervisor_node)
    for name, node in NODES.items():
        graph.add_node(name, node)
    graph.add_edge(START, "supervisor")
    return graph.compile()


def new_case(candidate: dict) -> dict:
    return {"id": candidate["id"], "candidate": candidate, "stage": "new", "done": False,
            "blocked": False, "block_reason": "", "checks": []}


def main() -> None:
    print("=== 1. 场景：6 名候选人，3 个角色，最多 12 轮 ===")
    picked = candidates()[:6]
    cases = [new_case(candidate) for candidate in picked]
    print(f"候选人：{'、'.join(candidate['name'] for candidate in picked)}")
    app = build_app()
    result = app.invoke(
        {"cases": cases, "log": [], "rounds": 0, "tokens": {}, "finished": False, "stop_reason": ""},
        {"recursion_limit": 100},
    )

    print("\n=== 2. 终止条件与结果 ===")
    print(f"停止原因：{result['stop_reason']}；已用 {result['rounds']}/{MAX_ROUNDS} 轮；消息 {len(result['log'])} 条")
    print("终止条件：① 队列为空 ② 轮次上限 12 ③ token 预算 6000 ④ 合规一票否决")
    for case in result["cases"]:
        status = "否决" if case["blocked"] else ("完成" if case["done"] else "未完成")
        print(f"  {case['id']} {case['candidate']['name']:<3} {status:<4} checks={','.join(case['checks']):<30} {case['block_reason']}")

    print("\n=== 3. 单 Agent 与多 Agent 对比 ===")
    possible = len(cases) * 3
    multi_checks = sum(len(set(case["checks"])) for case in result["cases"])
    multi_tokens = sum(result["tokens"].values()) + len(result["log"]) * MESSAGE_OVERHEAD_TOKENS
    single_tokens = len(cases) * (SINGLE_PROMPT_TOKENS + SINGLE_COMPLETION_TOKENS)
    print(f"{'指标':<10}{'单 Agent':<16}{'多 Agent'}")
    print(f"{'覆盖检查':<10}{f'{len(cases)}/{possible}':<16}{multi_checks}/{possible}")
    print(f"{'token':<10}{single_tokens:<16}{multi_tokens}（含消息开销）")
    for name, used in result["tokens"].items():
        print(f"  {name:<12} calls={sum(1 for m in result['log'] if m['sender'] == name):<3} tokens={used}")

    blocked = next(case for case in result["cases"] if case["id"] == "C003")
    unfinished = [case for case in result["cases"] if not case["done"] and not case["blocked"]]
    print(f"\n=== 4. 结论：覆盖率 {multi_checks}/{possible}，转人工 {len(unfinished)} 人 ===")
    assert blocked["blocked"] and "薪酬" in blocked["block_reason"]
    assert result["rounds"] == MAX_ROUNDS and len(result["log"]) == result["rounds"]
    assert multi_checks > len(cases) and sum(result["tokens"].values()) > 0


if __name__ == "__main__":
    main()
