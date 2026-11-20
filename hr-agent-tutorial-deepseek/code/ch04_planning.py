"""第 04 章：Planning —— 用 LangGraph 跑 ReAct 与 Plan-and-Solve。

运行：python code/ch04_planning.py
ReAct 走 create_agent；Plan 走 StateGraph：plan → execute → replan → finalize。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from pydantic import BaseModel, Field, ValidationError, model_validator

from common.data import candidates
from common.lc import MockChatModel, TracerCallbackHandler, final_text, tool_names

MAX_REPLANS = 1
def _screen() -> dict:
    ids = [item["id"] for item in candidates() if "算法" in item["position"]]
    return {"ok": True, "data": {"qualified": len(ids), "ids": ids}}

def _mock(name: str, description: str, fn: Callable[[], dict]) -> StructuredTool:
    return StructuredTool.from_function(func=fn, name=name, description=description)

TOOLS = {
    "check_hc": _mock("check_hc", "确认算法组 HC 与 P6 薪资带宽。", lambda: {"ok": True, "data": {"hc": 2, "level": "P6", "budget_k": 45}}),
    "post_job": _mock("post_job", "把 JD 发布到招聘渠道。", lambda: {"ok": True, "data": {"channels": ["官网", "猎聘", "内推"], "jd_id": "JD-ALGO-P6"}}),
    "screen": _mock("screen", "从人才池筛出符合算法岗位的候选人。", _screen),
    "expand_sourcing": _mock("expand_sourcing", "放宽到相邻技能，并启动猎头补位。", lambda: {"ok": True, "data": {"qualified": 2, "ids": ["C003", "C008"]}}),
    "arrange_interviews": _mock("arrange_interviews", "为通过筛选的候选人安排技术面。", lambda: {"ok": True, "data": {"booked": 2, "ids": ["IV01", "IV02"]}}),
    "make_offer": _mock("make_offer", "为通过面试的候选人发起 offer 审批。", lambda: {"ok": True, "data": {"approvals": ["AP-01", "AP-02"], "status": "approved"}}),
}
TOOL_LIST = list(TOOLS.values())
ACCEPT: dict[str, Callable[[dict], bool]] = {
    "check_hc": lambda data: data.get("hc", 0) >= 2,
    "post_job": lambda data: len(data.get("channels", [])) >= 3,
    "screen": lambda data: data.get("qualified", 0) >= 2,
    "expand_sourcing": lambda data: data.get("qualified", 0) >= 2,
    "arrange_interviews": lambda data: data.get("booked", 0) >= 2,
    "make_offer": lambda data: len(data.get("approvals", [])) >= 2,
}

class PlanStep(BaseModel):
    id: str
    goal: str
    tool: str
    depends_on: list[str] = Field(default_factory=list)
    done_when: str

class Plan(BaseModel):
    steps: list[PlanStep]

    @model_validator(mode="after")
    def check_graph(self):
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step id 重复")
        for step in self.steps:
            if step.tool not in TOOLS:
                raise ValueError(f"{step.id} 调用了不存在的工具 {step.tool}")
            missing = [dep for dep in step.depends_on if dep not in ids]
            if missing:
                raise ValueError(f"{step.id} 依赖不存在的步骤 {missing}")
        return self

def topo(plan: Plan) -> list[PlanStep]:
    rest = {step.id: set(step.depends_on) for step in plan.steps}
    order: list[PlanStep] = []
    while rest:
        ready = [step for step in plan.steps if step.id in rest and not rest[step.id]]
        if not ready:  # 没有可执行的步骤，只能是依赖成环
            raise ValueError("依赖成环，计划不可执行")
        for step in ready:
            order.append(step)
            rest.pop(step.id)
        for deps in rest.values():
            deps.difference_update(step.id for step in ready)
    return order

def patch(plan: Plan, failed_id: str, replacements: list[PlanStep]) -> Plan:
    steps = [step for step in plan.steps if step.id != failed_id]
    for step in steps:
        if failed_id in step.depends_on:
            step.depends_on = [dep for dep in step.depends_on if dep != failed_id] + [item.id for item in replacements]
    return Plan(steps=steps + replacements)

class PlanState(TypedDict, total=False):
    task: str
    plan: Plan
    done: dict[str, dict]
    executed: list[str]
    replans: int
    failed_step: str
    failure: dict
    status: str
    answer: str

def ask(model: MockChatModel, messages: list, config: RunnableConfig, label: str) -> str:
    response = model.invoke(messages, config=config)
    print(f"  [{label}] tokens={(response.usage_metadata or {}).get('total_tokens', 0)}")
    return response.content or ""

def build_graph(model: MockChatModel):
    def plan_node(state: PlanState, config: RunnableConfig) -> Command:
        content = ask(model, [SystemMessage("你是招聘规划器。只输出 steps JSON，字段 id/goal/tool/depends_on/done_when。"),
                              HumanMessage(state["task"])], config, "plan")
        try:
            plan = Plan.model_validate_json(content)
        except ValidationError as exc:
            return Command(goto="finalize", update={"status": "invalid_plan", "answer": f"计划校验失败：{exc.errors()[0]['msg']}"})
        for step in topo(plan):
            print(f"    {step.id} <- {step.depends_on or ['ROOT']} | {step.tool} | 验收: {step.done_when}")
        return Command(goto="execute", update={"plan": plan, "done": {}, "executed": [], "replans": 0, "status": "running"})

    def execute_node(state: PlanState, config: RunnableConfig) -> Command:
        plan, done = state["plan"], state.get("done", {})
        pending = [step for step in topo(plan) if step.id not in done]
        if not pending:
            return Command(goto="finalize", update={"status": "success"})
        step = pending[0]
        result = TOOLS[step.tool].invoke({})
        print(f"  [run] {step.id} {step.goal} -> {result['data']}")
        if result["ok"] and ACCEPT[step.tool](result["data"]):
            done[step.id] = result
            return Command(goto="execute", update={"done": done, "executed": state.get("executed", []) + [step.id]})
        if state.get("replans", 0) >= MAX_REPLANS:
            return Command(goto="finalize", update={"status": "failed", "failed_step": step.id})
        return Command(goto="replan", update={"failed_step": step.id, "failure": result["data"]})

    def replan_node(state: PlanState, config: RunnableConfig) -> Command:
        failed = next(step for step in state["plan"].steps if step.id == state["failed_step"])
        prompt = json.dumps({"failed": failed.model_dump(), "observation": state.get("failure", {})}, ensure_ascii=False)
        content = ask(model, [SystemMessage("只输出替代步骤的 JSON。"), HumanMessage(prompt)], config, "replan")
        try:
            replacements = [PlanStep.model_validate(item) for item in json.loads(content)["steps"]]
        except (json.JSONDecodeError, KeyError, ValidationError) as exc:
            return Command(goto="finalize", update={"status": "replan_failed", "answer": f"重规划失败：{exc}"})
        plan = patch(state["plan"], failed.id, replacements)
        print(f"  [replan] {failed.id} -> {[item.id for item in replacements]}")
        return Command(goto="execute", update={"plan": plan, "replans": state.get("replans", 0) + 1})

    def finalize_node(state: PlanState, config: RunnableConfig) -> dict:
        if state.get("status") != "success":
            return {"answer": state.get("answer", "计划未完成，已转人工。")}
        answer = ask(model, [HumanMessage(f"已执行 {state['executed']}，重规划 {state['replans']} 次。用一句话向 HR 汇报。")],
                     config, "summary")
        return {"answer": answer, "status": "success"}

    graph = StateGraph(PlanState)
    for name, node in (("plan", plan_node), ("execute", execute_node), ("replan", replan_node), ("finalize", finalize_node)):
        graph.add_node(name, node)
    graph.add_edge(START, "plan")
    graph.add_edge("finalize", END)
    return graph.compile()

PLAN_JSON = json.dumps({"steps": [
    {"id": "s1", "goal": "确认 HC 与薪资带宽", "tool": "check_hc", "depends_on": [], "done_when": "hc >= 2"},
    {"id": "s2", "goal": "把 JD 发到 3 个渠道", "tool": "post_job", "depends_on": ["s1"], "done_when": "channels >= 3"},
    {"id": "s3", "goal": "筛出至少 2 名 P6 算法候选人", "tool": "screen", "depends_on": ["s2"], "done_when": "qualified >= 2"},
    {"id": "s4", "goal": "安排 2 场技术面", "tool": "arrange_interviews", "depends_on": ["s3"], "done_when": "booked >= 2"},
    {"id": "s5", "goal": "发起 2 个 offer 审批", "tool": "make_offer", "depends_on": ["s4"], "done_when": "approvals >= 2"},
]}, ensure_ascii=False)
REPLAN_JSON = json.dumps({"steps": [
    {"id": "s3b", "goal": "放宽到相邻技能并启动猎头补位", "tool": "expand_sourcing", "depends_on": ["s2"], "done_when": "qualified >= 2"}
]}, ensure_ascii=False)
REACT_SCRIPT = [
    {"content": f"Thought: 执行 {name}", "tool_calls": [{"name": name, "args": {}}]}
    for name in ("check_hc", "post_job", "screen", "expand_sourcing", "arrange_interviews", "make_offer")
] + [{"content": "最终答案：3 周内锁定 2 名 P6 候选人，2 个 offer 审批已提交。"}]

def react_agent(task: str) -> tuple[dict, TracerCallbackHandler]:
    print("\n=== 1. ReAct：create_agent 的模型→工具循环 ===")
    agent = create_agent(model=MockChatModel(script=REACT_SCRIPT), tools=TOOL_LIST,
                         system_prompt="你是招聘 Agent。每轮只做一个动作，观察结果后再决定下一步。")
    tracer = TracerCallbackHandler()
    state = agent.invoke({"messages": [{"role": "user", "content": task}]},
                         config={"callbacks": [tracer], "recursion_limit": 20})
    print(f"工具序列：{tool_names(state)}")
    return state, tracer

def plan_and_solve(task: str) -> tuple[dict, TracerCallbackHandler]:
    print("\n=== 2. Plan-and-Solve：StateGraph 的 plan→execute→replan ===")
    model = MockChatModel(script=[{"content": PLAN_JSON}, {"content": REPLAN_JSON},
                                  {"content": "最终答案：计划执行完毕，2 名 P6 候选人进入 offer 审批，重规划 1 次。"}])
    tracer = TracerCallbackHandler()
    state = build_graph(model).invoke({"task": task}, config={"callbacks": [tracer], "recursion_limit": 30})
    return state, tracer

def main() -> None:
    task = "3 周内为算法组招到 2 名 P6 算法工程师，月薪不超过 45K，11 月 20 日启动。"
    react_state, react_tracer = react_agent(task)
    plan_state, plan_tracer = plan_and_solve(task)
    react_calls, react_tokens, react_tools = (react_tracer.llm_calls, react_tracer.prompt_tokens + react_tracer.completion_tokens, react_tracer.tool_calls)
    plan_calls, plan_tokens, plan_tools = (plan_tracer.llm_calls, plan_tracer.prompt_tokens + plan_tracer.completion_tokens, plan_tracer.tool_calls)

    print("\n=== 3. 两种模式对比 ===")
    print(f"{'模式':<16}{'LLM 调用':>10}{'Token':>10}{'工具调用':>10}  状态")
    print(f"{'ReAct':<16}{react_calls:>10}{react_tokens:>10}{react_tools:>10}  success")
    print(f"{'Plan-and-Solve':<16}{plan_calls:>10}{plan_tokens:>10}{plan_tools:>10}  {plan_state['status']}")
    print(f"\nReAct 答案：{final_text(react_state)}")
    print(f"Plan 答案：{plan_state['answer']}")
    print(f"计划执行：{plan_state['executed']}；重规划 {plan_state['replans']} 次")
    print("\n=== 4. 断言 ===")
    assert "2 名" in final_text(react_state)
    assert plan_state["status"] == "success" and plan_state["replans"] == 1 and "s3b" in plan_state["executed"]
    assert plan_calls < react_calls
    assert plan_tokens < react_tokens
    print("全部通过：ReAct 与 Plan-and-Solve 都完成，Plan 的调用与 token 更少。")
if __name__ == "__main__":
    main()
