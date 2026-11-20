"""第 05 章：Planning —— 用 LangGraph 搭 Plan-and-Execute。

跑法：python ch05_planning/main.py

四个关键点：
  1. 计划是一份**数据**（Step 列表），不是一段自然语言
  2. 执行要按 depends_on 拓扑序，不能按模型的心情
  3. 环 / 死锁要在执行前就查出来
  4. 一步失败 → 重规划（replan），而不是整条重来
"""

import sys, pathlib
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from common import ai_tool, get_model, practice, section, star, title

# ============================================================
# 计划的数据结构
# ============================================================
class Step(BaseModel):
    """计划里的一步。"""
    id: str = Field(description="步骤编号，如 s1")
    action: str = Field(description="要做什么")
    depends_on: list[str] = Field(default_factory=list, description="依赖的前置步骤")
    acceptance: str = Field(description="这一步怎么算完成（可验证的判据）")


class Plan(BaseModel):
    """一份完整计划。"""
    goal: str
    steps: list[Step]


# ============================================================
# 各步的执行器（真实项目里这里是工具调用）
# ============================================================
def run_step(step: Step, ctx: dict) -> tuple[bool, str]:
    if step.id == "s1":
        return True, "JD 已解析：高级前端工程师 / 苏州 / Vue3+TS / 3-5 年"
    if step.id == "s2":
        # ★ 故意让这一步失败，用来演示"失败之后怎么办"
        return False, "简历库连接超时（模拟下游故障）"
    if step.id == "s3":
        return True, "已按评分卡打分：C1001 82 分 / C1024 76 分"
    return True, "完成"


# ============================================================
# 图的状态
# ============================================================
class PlanState(TypedDict):
    messages: list
    plan: Plan | None
    cursor: list[str]
    results: dict
    replans: int
    report: str
    _plan_args: dict
    _last_ok: bool
    _failed: str | None


MAX_REPLANS = 2


def planner_node(state: PlanState):
    """① 规划：模型输出一份 Plan（结构化，不是散文）。"""
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是招聘流程规划器。把目标拆成 2-4 步，每步给出可验证的 acceptance。"),
        ("human", "{goal}"),
    ])
    model = get_model([ai_tool("Plan", state["_plan_args"], "call_plan")])
    plan: Plan = (prompt | model.with_structured_output(Plan)).invoke({"goal": state["messages"][-1]["content"]})
    order = topo_order(plan)
    print(f"\n  计划：{plan.goal}")
    for s in plan.steps:
        print(f"    {s.id} {s.action}  depends_on={s.depends_on}  验收：{s.acceptance}")
    print(f"  拓扑序：{order}")
    return {"plan": plan, "cursor": order}


def topo_order(plan: Plan) -> list[str]:
    """拓扑排序 + 环检测。★ 计划不能直接按模型给的顺序跑。"""
    ids = {s.id for s in plan.steps}
    deps = {s.id: [d for d in s.depends_on if d in ids] for s in plan.steps}
    for s in plan.steps:
        for d in s.depends_on:
            if d not in ids:
                raise ValueError(f"步骤 {s.id} 依赖了不存在的 {d}")
    order, done = [], set()
    while len(order) < len(ids):
        ready = [i for i in ids if i not in done and all(d in done for d in deps[i])]
        if not ready:
            raise ValueError(f"计划里有环或死锁：剩余 {sorted(ids - done)}")
        order.append(sorted(ready)[0])
        done.add(order[-1])
    return order


def executor_node(state: PlanState):
    """② 执行当前这一步。"""
    sid = state["cursor"][0]
    step = next(s for s in state["plan"].steps if s.id == sid)
    ok, msg = run_step(step, state["results"])
    print(f"    执行 {sid}：{'✓' if ok else '✗'} {msg}")
    results = {**state["results"], sid: {"ok": ok, "msg": msg}}
    return {"results": results, "cursor": state["cursor"][1:], "_last_ok": ok, "_failed": None if ok else sid}


def replanner_node(state: PlanState):
    """③ 重规划：只重排剩下的步骤，已完成的不动。★ 这是 Plan-and-Solve 与一次性规划的差别。"""
    n = state["replans"] + 1
    failed = state.get("_failed")
    print(f"    重规划 #{n}：{failed} 失败，改用降级路径")
    rest = [s for s in state["plan"].steps if s.id not in state["results"]]
    alt_id = f"{failed}_alt"
    # ★ 重规划不只是"加一步"：原来依赖失败步骤的下游步骤，依赖边也要一起改写
    new_steps = [
        s.model_copy(update={"depends_on": [alt_id if d == failed else d for d in s.depends_on]})
        for s in rest
    ] + [Step(id=alt_id, action="用缓存的人才库快照代替实时库", depends_on=[],
              acceptance="能拿到候选人列表")]
    plan = Plan(goal=state["plan"].goal, steps=new_steps)
    return {"plan": plan, "cursor": topo_order(plan), "replans": n, "_failed": None}


def route(state: PlanState):
    if state.get("_failed"):
        return "replan" if state["replans"] < MAX_REPLANS else "give_up"
    return "execute" if state["cursor"] else "summarize"


def summarize_node(state: PlanState):
    done = sum(1 for v in state["results"].values() if v["ok"])
    return {"report": f"完成 {done}/{len(state['results'])} 步；最终结论：建议约面 C1001（82 分）"}


def give_up_node(state: PlanState):
    return {"report": f"放弃：重规划 {state['replans']} 次仍未通过，转人工"}


# ============================================================
# 组装
# ============================================================
builder = StateGraph(PlanState)
builder.add_node("planner", planner_node)
builder.add_node("executor", executor_node)
builder.add_node("replan", replanner_node)
builder.add_node("summarize", summarize_node)
builder.add_node("give_up", give_up_node)
builder.add_edge(START, "planner")
builder.add_conditional_edges("planner", lambda s: "execute" if s["cursor"] else "summarize",
                              {"execute": "executor", "summarize": "summarize"})
builder.add_conditional_edges("executor", route,
                              {"execute": "executor", "replan": "replan", "summarize": "summarize", "give_up": "give_up"})
builder.add_conditional_edges("replan", lambda s: "execute" if s["cursor"] else "summarize",
                              {"execute": "executor", "summarize": "summarize"})
builder.add_edge("summarize", END)
builder.add_edge("give_up", END)
graph = builder.compile()

# ============================================================
# 跑
# ============================================================
title("案例：一次真实的重规划（s2 故障 → 降级 → 收敛）")

PLAN_ARGS = {
    "goal": "把 P1001 的候选人初筛做完并给出建议",
    "steps": [
        {"id": "s1", "action": "解析 JD 得到岗位画像", "depends_on": [], "acceptance": "拿到结构化 JobProfile"},
        {"id": "s2", "action": "拉取该岗位全部简历", "depends_on": ["s1"], "acceptance": "拿到 >=1 份简历"},
        {"id": "s3", "action": "按评分卡打分并排序", "depends_on": ["s2"], "acceptance": "每份简历有分数与依据"},
    ],
}

init: PlanState = {"messages": [{"content": "把 P1001 的候选人初筛做完"}], "plan": None, "cursor": [],
                   "results": {}, "replans": 0, "report": "", "_plan_args": PLAN_ARGS}

out = graph.invoke(init, config={"recursion_limit": 20})
print(f"\n  结果：{out['report']}")

# ============================================================
# 反面：环检测
# ============================================================
section("反面案例：计划里出现环，执行前就该拦住")
bad = Plan(goal="x", steps=[
    Step(id="a", action="A", depends_on=["b"], acceptance="ok"),
    Step(id="b", action="B", depends_on=["a"], acceptance="ok"),
])
try:
    topo_order(bad)
except ValueError as e:
    print(f"    {e}")
star("计划是数据 → 数据就能校验。校验放在执行前，比事后 debug 便宜一百倍")

# ============================================================
# 什么时候不该规划
# ============================================================
section("判据：这三条命中就别用 Planning")
for line in [
    "① 步骤固定、每次一样（如'查余额'）→ 直接用 Workflow（第 06 章）",
    "② 单步就能答完（问一句话）→ 直接 create_agent 或一条链",
    "③ 每步结果不可预估且相互耦合 → 用 ReAct 边走边看，别预先排",
]:
    print(f"    {line}")

practice([
    "把 s2 改成'先试两次再降级'，看 replan 次数怎么变",
    "给 Step 加一个 est_tokens 字段，在 planner 里拒绝总预算超标的计划",
    "把 planning 图换成 create_agent + 一个 write_plan 工具，对比两种做法的可控性",
])
