"""第 13 章：Multi-Agent —— 分工、交接、仲裁。

跑法：python ch13_multi_agent/main.py

LangGraph 里做多智能体有两条路：
  · Supervisor（一个调度者，串行派活）—— 好调试，绝大多数场景够用
  · Send / 并行 fan-out 再 join —— 快，但冲突要自己收口

本章两个都跑：先串行 supervisor，再并行评审 + 仲裁。
"""

import operator, sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from typing import Annotated
from typing_extensions import TypedDict

from common import ai_text, ai_tool, get_model, practice, section, star, title

# ============================================================
# 0) 三个"专家"（每个都有自己的职责、工具、边界）
# ============================================================
WORKERS = {
    "recruiter": {"role": "招聘专员", "scope": "候选人匹配、面试安排", "may_not": "定薪、改带宽"},
    "comp": {"role": "薪酬专员", "scope": "带宽核对、特批测算", "may_not": "承诺候选人薪资"},
    "legal": {"role": "合规审核", "scope": "合同条款、用工风险、数据合规", "may_not": "做业务决策"},
}

title("案例 1：为什么不能只用一个'全能 Agent'")

for k, v in WORKERS.items():
    print(f"    {k:<10} {v['role']:<6} 负责：{v['scope']:<22} 禁止：{v['may_not']}")
star("多智能体的真正理由不是'模型不够聪明'，是'权限与责任要分开'——定薪的人和合规的人不能是同一个")

# ============================================================
# 1) Supervisor：串行派活 + 交接限制
# ============================================================
section("案例 2：Supervisor 模式（含手数上限与交接记录）")

class TeamState(TypedDict, total=False):
    task: str
    next: str
    findings: dict
    handoffs: list[str]
    turns: int
    verdict: str


MAX_HANDOFFS = 4

ROUTE_PROMPT = "根据任务与已有结论，决定下一位专家：recruiter / comp / legal / FINISH。"


def supervisor(state: TeamState):
    """★ 调度者只做一件事：决定'谁下一个'。它不干活，也不许无限派活。"""
    if state.get("turns", 0) >= MAX_HANDOFFS:
        return {"next": "FINISH", "handoffs": state.get("handoffs", []) + ["达到交接上限，强制收口"]}
    done = state.get("findings", {})
    script = []
    if "recruiter" not in done:
        script.append(ai_text("recruiter"))
    elif "comp" not in done:
        script.append(ai_text("comp"))
    elif "legal" not in done:
        script.append(ai_text("legal"))
    else:
        script.append(ai_text("FINISH"))
    model = get_model(script)
    nxt = model.invoke(ROUTE_PROMPT).content.strip()
    if state.get("turns", 0) >= MAX_HANDOFFS:
        nxt = "FINISH"
    print(f"    supervisor → {nxt}")
    return {"next": nxt, "turns": state.get("turns", 0) + 1}


def make_worker(name: str):
    def _run(state: TeamState):
        # 每个 worker 只拿到"自己该看的那部分上下文"，不是全量（这是成本与安全的双重要求）
        if name == "recruiter":
            finding = "C1024 与 P1001 匹配度 82%，可约二面"
        elif name == "comp":
            finding = "C1024 期望 28K，带宽 22-25K，超 3K，需薪酬特批"
        else:
            finding = "合规提示：offer 需写明试用期与竞业条款；28K 超出带宽须留特批书面记录"
        print(f"    {name} 输出：{finding}")
        findings = {**state.get("findings", {}), name: finding}
        return {"findings": findings, "handoffs": state.get("handoffs", []) + [f"→{name}"]}

    return _run


def judge(state: TeamState):
    """★ 仲裁：合规有一票否决；薪酬与招聘冲突时以'制度'为准，不以'谁先说'为准。"""
    f = state.get("findings", {})
    legal_veto = "须留特批书面记录" not in f.get("legal", "")
    if legal_veto:
        verdict = "退回：合规未通过"
    elif "特批" in f.get("comp", ""):
        verdict = "有条件通过：走薪酬特批后再发 offer"
    else:
        verdict = "通过"
    print(f"    仲裁结果：{verdict}")
    return {"verdict": verdict}


g = StateGraph(TeamState)
g.add_node("supervisor", supervisor)
for n in WORKERS:
    g.add_node(n, make_worker(n))
g.add_node("judge", judge)
g.add_edge(START, "supervisor")
g.add_conditional_edges("supervisor", lambda s: s["next"],
                        {**{n: n for n in WORKERS}, "FINISH": "judge"})
for n in WORKERS:
    g.add_edge(n, "supervisor")
g.add_edge("judge", END)
team = g.compile()

print()
out = team.invoke({"task": "把 C1024 的 offer 走完", "findings": {}, "handoffs": [], "turns": 0})
print(f"  交接链：{' '.join(out['handoffs'])}")
print(f"  结论：{out['verdict']}")

# ============================================================
# 2) 并行 fan-out + join
# ============================================================
section("案例 3：Send 并行评审 —— 三个专家同时看，再统一收口")

class ReviewState(TypedDict, total=False):
    case: str
    reviews: Annotated[list[dict], operator.add]   # ★ 并行分支要往同一个字段写，必须声明 reducer
    merged: str
    conflicts: list[str]


def fan_out(state: ReviewState):
    """★ Send：把同一个 case 复制三份，并行发给三个专家节点。"""
    return [Send(w, {"case": state["case"], "reviews": []}) for w in WORKERS]


def mk_reviewer(name: str):
    def _run(state: ReviewState):
        verdicts = {
            "recruiter": {"ok": True, "note": "C1024 匹配 82%"},
            "comp": {"ok": False, "note": "期望 28K 超带宽 3K"},
            "legal": {"ok": True, "note": "需补竞业条款"},
        }
        print(f"    [{name}] 并行评审完成")
        return {"reviews": [{"who": name, **verdicts[name]}]}
    return _run


def join_reviews(state: ReviewState):
    """★ 收口：把并行结论合并，冲突项必须显式标出来（不能悄悄取平均）。"""
    rs = state["reviews"]
    conflicts = [f"{r['who']}:{r['note']}" for r in rs if not r["ok"]]
    merged = f"共 {len(rs)} 份评审，{'通过' if not conflicts else '有条件通过'}；待处理：{conflicts}"
    print(f"    合并结果：{merged}")
    return {"merged": merged, "conflicts": conflicts}


r = StateGraph(ReviewState)
for n in WORKERS:
    r.add_node(n, mk_reviewer(n))
r.add_node("join", join_reviews)
r.add_conditional_edges(START, fan_out, list(WORKERS))
for n in WORKERS:
    r.add_edge(n, "join")
r.add_edge("join", END)
review = r.compile()

print()
rout = review.invoke({"case": "C1024 的 offer", "reviews": []})
print(f"  并行合并：{rout['merged']}")
star("Send 的价值：墙钟时间 = 最慢那个；代价：结果无序，冲突必须自己收口")

# ============================================================
# 3) 多智能体的四个坑
# ============================================================
section("案例 4：多智能体最容易翻车的四件事")
for line in [
    "① 无限交接：A 给 B、B 给 A，永远收不了口 → 必须有交接上限 + 收敛判据",
    "② 上下文污染：每个 worker 都塞全量历史，token 成本翻三倍，且互相带偏 → 只给切片",
    "③ 责任真空：三个都说'没问题'，没人对最终结果负责 → 必须有一个仲裁节点署名",
    "④ 成本失控：串行 5 个专家，成本 = 5 倍 → 先问'能不能一个 Agent 加 3 个工具就够'",
]:
    print(f"    {line}")
star("能用单 Agent + 工具门禁解决的，别上多智能体；多智能体的门槛是'权限必须分开'")

practice([
    "把 MAX_HANDOFFS 改成 2，观察结论质量与成本的变化",
    "给 legal 加一票否决的结构化输出（veto: bool + reason），替代字符串匹配",
    "把三个 worker 分别指向不同的模型（贵的给敲定、便宜的给检索），统计成本",
])
