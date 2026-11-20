"""第 06 章：Workflow 与状态机 —— 该定死的地方别让模型自由发挥。

跑法：python ch06_workflow/main.py

LangChain 侧用 LangGraph 的 StateGraph：
  · 每个节点 = 状态里的一个动作（action）
  · 条件边 = 转移（transition），守卫（guard）写在条件函数里
  · checkpointer = 状态落库，进程崩了能续
  · 模型只负责两件事：意图分类、状态内的话术生成。不负责决定"能不能跳步"。
"""

import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from common import ai_text, get_model, practice, section, star, title

# ============================================================
# 1) 状态机定义（纯数据，可审查）
# ============================================================
STATES = ["草稿", "业务审批", "HRBP审批", "薪酬审批", "待发出", "已发出"]
TRANSITIONS = {
    ("草稿", "业务审批"): {"guard": lambda p: bool(p.get("candidate_id")), "why": "缺候选人号"},
    ("业务审批", "HRBP审批"): {"guard": lambda p: p.get("biz_ok") is True, "why": "业务未通过"},
    ("HRBP审批", "薪酬审批"): {"guard": lambda p: p.get("hb_ok") is True, "why": "HRBP 未通过"},
    ("薪酬审批", "待发出"): {"guard": lambda p: p.get("salary_ok") is True, "why": "薪酬超带宽未特批"},
    ("待发出", "已发出"): {"guard": lambda p: p.get("mail_sent") is True, "why": "邮件未发出"},
}
TERMINAL = {"已发出"}
# ★ 注意：这里没有任何一条边允许"草稿 → 薪酬审批"。SOP 的顺序由代码保证，不是由 prompt 保证。


class OfferState(TypedDict, total=False):
    offer_id: str
    state: str
    payload: dict
    log: list[str]
    version: int
    stalled: bool


# ============================================================
# 2) 带乐观锁的存储（真实项目里换成数据库 + version 字段）
# ============================================================
class Store:
    def __init__(self):
        self.rows: dict[str, OfferState] = {}

    def cas(self, offer_id: str, expect_version: int, new_state: str, patch: dict | None = None):
        """★ CAS：只有版本号对得上才允许写。两个审批人同时点'通过'时，只有一个能成功。

        同时守住"只有 TRANSITIONS 里存在的边才能走" —— 跳步在数据层就不可能发生。
        """
        row = self.rows.get(offer_id)
        if row is None:
            raise KeyError(offer_id)
        if new_state != row["state"] and (row["state"], new_state) not in TRANSITIONS:
            raise RuntimeError(f"非法转移：{row['state']} → {new_state}（SOP 里没有这条边）")
        if row["version"] != expect_version:
            raise RuntimeError(f"版本冲突：期望 v{expect_version}，实际 v{row['version']}（有人先改了）")
        row["state"] = new_state
        row["payload"] = {**row["payload"], **(patch or {})}
        row["version"] += 1
        row["log"].append(f"{new_state}@v{row['version']}")
        return row

    def patch(self, offer_id: str, patch: dict):
        """外部系统写入（审批人点通过、上传附件等）：只改数据，不推进状态。"""
        row = self.rows[offer_id]
        row["payload"] = {**row["payload"], **patch}
        row["version"] += 1
        return row


store = Store()
store.rows["K1001"] = {"offer_id": "K1001", "state": "草稿", "version": 1, "log": ["草稿@v1"],
                       "payload": {"candidate_id": "C1024", "level": "P6", "salary": 28000, "band_max": 25000}}


# ============================================================
# 3) 图：一个节点负责"推进一格"，守卫决定能不能推
# ============================================================
def transition_node(state: OfferState):
    """尝试把 offer 往前推一格；推不动就把原因记下来。"""
    cur = state["state"]
    for (frm, to), rule in TRANSITIONS.items():
        if frm != cur:
            continue
        if not rule["guard"](state["payload"]):
            return {"log": state["log"] + [f"⛔ 停在 {cur}：{rule['why']}"], "stalled": True}
        try:
            row = store.cas(state["offer_id"], state["version"], to)
        except RuntimeError as e:
            return {"log": state["log"] + [f"⛔ {e}"], "stalled": True}
        return {"state": row["state"], "version": row["version"], "log": row["log"], "stalled": False}
    return {"log": state["log"] + [f"（{cur} 没有可用转移，流程结束）"], "stalled": True}


def route(state: OfferState):
    """★ 终止条件：到终态，或者这一格推不动了（守卫拦住 / 版本冲突）。

    没有这个条件，图会在同一个状态上无限自旋 —— 这就是"工作流也需要终止条件"。
    """
    return END if (state["state"] in TERMINAL or state.get("stalled")) else "transition"


builder = StateGraph(OfferState)
builder.add_node("transition", transition_node)
builder.add_edge(START, "transition")
builder.add_conditional_edges("transition", route, {"transition": "transition", END: END})
# ★ checkpointer：每一步状态都落库，进程挂了/要人工介入时可以原地恢复
graph = builder.compile(checkpointer=InMemorySaver())

# ============================================================
# 4) 跑：正常流程（需要三次人工审批通过）
# ============================================================
title("案例 1：一条 offer 的正常推进路径")

cfg = {"configurable": {"thread_id": "K1001"}, "recursion_limit": 12}

init: OfferState = {"offer_id": "K1001", "state": "草稿", "version": 1, "log": ["草稿@v1"],
                    "payload": {"candidate_id": "C1024", "level": "P6", "salary": 28000, "band_max": 25000}}

print()
graph.invoke(init, cfg)
print(f"  第 1 次推进后：{store.rows['K1001']['log'][-1]}（停在'业务审批'等人）")


def advance(thread_cfg, note: str):
    """把最新数据同步给图，让它再推一格（真实项目里由审批回调触发）。"""
    row = store.rows["K1001"]
    graph.invoke({"payload": row["payload"], "version": row["version"]}, thread_cfg)
    print(f"  {note} → {store.rows['K1001']['log'][-1]}")


snapshot = graph.get_state(cfg)
print(f"  checkpoint 里的状态：{snapshot.values['state']} v{snapshot.values['version']}")

store.patch("K1001", {"biz_ok": True})
advance(cfg, "业务审批通过")
store.patch("K1001", {"hb_ok": True})
advance(cfg, "HRBP 通过")
store.patch("K1001", {"salary_ok": True, "exception_note": "P6 稀缺技能，已报 HRD 特批"})
advance(cfg, "薪酬特批通过")
store.patch("K1001", {"mail_sent": True})
advance(cfg, "offer 邮件发出")
print(f"  最终：{store.rows['K1001']['state']}，审计流水：{store.rows['K1001']['log']}")
star("状态机最大的价值：'走到哪一步'是数据，不是模型的一句话，可查、可恢复、可审计")

# ============================================================
# 5) 三种异常
# ============================================================
section("案例 2：跳步 / 守卫拦住 / 并发冲突")

print("\n  ① 想直接从'草稿'跳到'薪酬审批'：")
try:
    store.cas("K1001", store.rows["K1001"]["version"], "薪酬审批")
except Exception as e:
    print(f"     ", e)
print("     正确做法：代码里根本没有这条边 → 跳步在编译期就不可能发生")

print("\n  ② 守卫拦住（薪酬超带宽）：")
fresh = Store()
fresh.rows["K2002"] = {"offer_id": "K2002", "state": "薪酬审批", "version": 1, "log": ["薪酬审批@v1"],
                        "payload": {"candidate_id": "C1009", "level": "P7", "salary": 32000, "band_max": 28000,
                                    "salary_ok": False}}
st = fresh.rows["K2002"]
for (frm, to), rule in TRANSITIONS.items():
    if frm == st["state"]:
        print(f"      → {to}: {'放行' if rule['guard'](st['payload']) else '⛔ ' + rule['why']}")

print("\n  ③ 两个审批人同时提交（乐观锁）：")
row = store.rows["K1001"]
v = row["version"]
try:
    store.cas("K1001", v, "已发出", {"mail_sent": True})
    print("      第一人成功")
except Exception as e:
    print(f"      第一人失败：{e}")
try:
    store.cas("K1001", v, "已发出", {"mail_sent": True})
except RuntimeError as e:
    print(f"      第二人失败：{e}")
star("并发不是'可能发生'，是'一定发生'。版本号是成本最低的解决办法")

# ============================================================
# 6) 模型在这套流程里的位置
# ============================================================
section("案例 3：模型只做两件事——意图分类、话术生成")
model = get_model([
    ai_text('{"intent":"approve","confidence":0.92}'),
    ai_text("张伟您好，我们已为您准备好 offer，请在 3 个工作日内确认。"),
])
print("\n  ① 意图分类（模型判断用户说'行，就这样吧'是想通过还是想改）：")
print("     ", model.invoke("行，就这样吧").content)
print("  ② 话术生成（内容由状态机决定，模型只负责把它说得像人话）：")
print("     ", model.invoke("给 C1024 生成 offer 通知邮件正文").content)
for line in [
    "不该交给模型的：能不能跳步、能不能发出、走哪条分支",
    "可以交给模型的：这句用户话是什么意图、这段文案怎么写、这条异常怎么解释给用户",
]:
    print(f"     · {line}")
star("'Agent 只做事件分类与状态内执行器' —— 这是 HR/财务/审批类系统的通用架构")

practice([
    "给 TRANSITIONS 加一条'驳回'边（回到草稿并记录原因），跑一遍看 log 是否可审计",
    "把 InMemorySaver 换成 SqliteSaver，杀掉进程再 get_state 恢复",
    "把意图分类改成 with_structured_output(Intent)，比较两种写法的可靠性",
])
