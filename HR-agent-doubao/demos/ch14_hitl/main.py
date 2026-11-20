"""第 14 章：Human-in-the-loop —— 该停的地方必须停下来等人。

跑法：python ch14_hitl/main.py

LangGraph 的 HITL 三件套：
  · interrupt(payload)      —— 在节点里"挂起"，把问题抛给外面的人
  · Command(resume=value)   —— 人给了答案，图从这里继续跑（状态由 checkpointer 保住）
  · checkpointer            —— 挂起期间进程可以退出，第二天照样接着跑

HR 场景的红线：发 offer、调薪、批量导出个人信息、开除人 —— 一律 HITL，不许自动执行。
"""

import sys, pathlib, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from common import practice, section, star, title

title("案例 1：一个必须停下来的动作（发 offer）")

class State(TypedDict, total=False):
    emp_id: str
    applicant: str
    content: str
    approval: dict
    sent: bool
    trace: list[str]


def draft_node(state: State):
    body = f"【offer】{state['emp_id']}：月薪 28,000，试用期 3 个月，报到日 2026-12-01。"
    return {"content": body, "trace": state.get("trace", []) + ["已生成 offer 草稿"]}


def gate_node(state: State):
    """★ 高危动作前挂起：把'要批什么'结构化地交给人，而不是丢一句话。"""
    decision = interrupt({
        "action": "send_offer",
        "risk": "high",
        "reason": "月薪 28,000 超出带宽 22-25K，需薪酬特批 + HRD 签批",
        "content": state["content"],
        "options": ["approve", "reject", "edit"],
        "sla_hours": 24,
        "created_at": time.time(),
    })
    # ↓ 人能返回 approve / reject / edit，甚至改内容
    return {"approval": decision}


def send_node(state: State):
    ap = state["approval"]
    if ap["decision"] != "approve":
        return {"sent": False, "trace": state["trace"] + [f"未发送：{ap['decision']}"]}
    content = ap.get("content") or state["content"]
    return {"sent": True, "content": content,
            "trace": state["trace"] + [f"已发送（审批人 {ap['approver']}）"]}


def route(state: State):
    return "send" if state["approval"]["decision"] == "approve" else END


g = StateGraph(State)
g.add_node("draft", draft_node)
g.add_node("gate", gate_node)
g.add_node("send", send_node)
g.add_edge(START, "draft")
g.add_edge("draft", "gate")
g.add_conditional_edges("gate", route, {"send": "send", END: END})
g.add_edge("send", END)
app = g.compile(checkpointer=InMemorySaver())

cfg = {"configurable": {"thread_id": "offer-K1001"}}
init: State = {"emp_id": "K1001", "applicant": "HRBP-李娜", "trace": []}

print()
app.invoke(init, cfg)
snap = app.get_state(cfg)
print(f"  图已挂起：next={snap.next}")
print(f"  等人批准的内容：{snap.tasks[0].interrupts[0].value['reason']}")
star("interrupt() 之后进程可以做别的事；状态在 checkpointer 里，人可以过两小时再批")

# ============================================================
# 2) 审批人来了：三种回答
# ============================================================
section("案例 2：approve / edit / reject —— 三种续跑方式")

def resume(thread: str, payload: dict, note: str):
    cfg2 = {"configurable": {"thread_id": thread}}
    out = app.invoke(Command(resume=payload), cfg2)
    print(f"\n  {note}")
    print(f"    结果：sent={out.get('sent')}，内容：{out['content'][:46]}")
    print(f"    轨迹：{out['trace']}")
    return out


# ① 直接批准
resume("offer-K1001", {"decision": "approve", "approver": "薪酬负责人-王强"}, "① 直接批准")

# ② 改了内容再批准（人改了金额，流程不重跑）
cfg3 = {"configurable": {"thread_id": "offer-K1002"}}
app.invoke({"emp_id": "K1002", "applicant": "HRBP-李娜", "trace": []}, cfg3)
resume("offer-K1002", {"decision": "approve", "approver": "HRD-陈静",
                       "content": "【offer】K1002：月薪 25,000（已压回带宽内），试用期 3 个月。"},
       "② 编辑后批准")

# ③ 拒绝
cfg4 = {"configurable": {"thread_id": "offer-K1003"}}
app.invoke({"emp_id": "K1003", "applicant": "HRBP-李娜", "trace": []}, cfg4)
resume("offer-K1003", {"decision": "reject", "approver": "HRD-陈静", "note": "带宽外，且无特批材料"},
       "③ 拒绝")

# ============================================================
# 3) HITL 的四个必备校验
# ============================================================
section("案例 3：光有'停下来'不够，还得有这四道校验")

def validate(state: State, ap: dict) -> str | None:
    """审批越权/过期/超时，都要在这里拦。"""
    if ap.get("approver") == state.get("applicant"):
        return "审批人不能是申请人本人"
    waited = time.time() - ap.get("asked_at", time.time())
    if waited > 24 * 3600:
        return f"审批超时 {waited/3600:.0f}h > 24h，自动失效"
    if ap["decision"] == "approve" and "月薪" in state["content"] and ap.get("approver", "").find("HRD") < 0:
        return "超带宽 offer 必须 HRD 签批"
    return None


cases = [
    ("申请人自批", {"decision": "approve", "approver": "HRBP-李娜"}),
    ("超时未批", {"decision": "approve", "approver": "HRD-陈静", "asked_at": time.time() - 30 * 3600}),
    ("越权批准", {"decision": "approve", "approver": "HRBP-张伟"}),
    ("合规批准", {"decision": "approve", "approver": "HRD-陈静"}),
]
st: State = {"emp_id": "K1001", "applicant": "HRBP-李娜", "content": "【offer】月薪 28,000"}
for name, ap in cases:
    err = validate(st, ap)
    print(f"    {name:<8} → {'✅ 通过' if err is None else '⛔ ' + err}")

for line in [
    "① 身份校验：审批人 ≠ 申请人；越权（金额/职级）要更高一层",
    "② 时效校验：挂起不是无限等，超时自动失效并通知发起人",
    "③ 幂等校验：同一个审批点不能批两次（用 interrupt id / 版本号）",
    "④ 审计：谁批的、什么时候、批的哪一版内容，全落库",
]:
    print(f"    {line}")
star("HITL 的本质不是'加个确认弹窗'，是'把不可逆的动作拆成 生成 → 人审 → 执行'三步")

practice([
    "给 gate 加第二个 interrupt（财务复核），跑通'两级审批'",
    "把 InMemorySaver 换成 SqliteSaver，杀掉进程后再 Command(resume) 续跑",
    "给审批加'超时自动转上级'分支，观察 next 的变化",
])
