"""第 03 章：Agent Loop —— 先看 create_agent 跑，再亲手搭出它的内核。

跑法：python ch03_agent_loop/main.py

LangChain 1.x 的 agent 就是一个 LangGraph：
    model ⇄ tools 两节点循环，直到模型不再发起 tool_call。
本章先用它，再拆开自己搭一遍，最后给这个循环装刹车。
"""

import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from common import ai_text, ai_tool, get_model, practice, section, star, title

# ============================================================
# 工具：真实的数据全是虚构的
# ============================================================
POSITIONS = {
    "P1001": {"title": "高级前端工程师", "city": "苏州", "status": "招聘中", "owner": "王强"},
    "P1002": {"title": "数据分析师", "city": "苏州", "status": "暂停", "owner": "李娜"},
}
APPLICATIONS = [("C1001", "P1001", "待初筛"), ("C1024", "P1001", "已约面"), ("C1002", "P1002", "已淘汰")]


@tool
def get_position(position_id: str) -> str:
    """按岗位编号查岗位详情。编号形如 P1001。"""
    p = POSITIONS.get(position_id)
    return f"{position_id}: {p['title']} / {p['city']} / {p['status']} / 负责人 {p['owner']}" if p else f"没有 {position_id} 这个岗位"


@tool
def count_applications(position_id: str, status: str = "") -> str:
    """统计某岗位的投递数。status 可传'待初筛'/'已约面'/'已淘汰'，不传则统计全部。"""
    rows = [a for a in APPLICATIONS if a[1] == position_id and (not status or a[2] == status)]
    return f"{position_id} 共 {len(rows)} 份投递" + (f"（状态={status}）" if status else "")


TOOLS = [get_position, count_applications]

# ============================================================
# 案例 1：create_agent —— 三跳剧本，看它自己转
# ============================================================
title("案例 1：create_agent 的三步循环（查岗位 → 数投递 → 回答）")

SCRIPT = [
    ai_tool("get_position", {"position_id": "P1001"}, "call_1"),
    ai_tool("count_applications", {"position_id": "P1001", "status": "待初筛"}, "call_2"),
    ai_text("P1001 高级前端工程师在苏州招聘中，目前有 1 份投递停在'待初筛'。"),
]

agent = create_agent(
    get_model(SCRIPT),
    tools=TOOLS,
    system_prompt="你是招聘运营助手。先查事实再回答，不许猜数字。",
)

result = agent.invoke({"messages": [HumanMessage(content="P1001 现在什么情况？有多少待初筛？")]})

print()
for i, m in enumerate(result["messages"], 1):
    if isinstance(m, AIMessage):
        if m.tool_calls:
            calls = ", ".join(f"{c['name']}({c['args']})" for c in m.tool_calls)
            print(f"  [{i}] AIMessage → 我要调工具：{calls}")
        else:
            print(f"  [{i}] AIMessage → 最终回答：{m.content}")
    elif isinstance(m, ToolMessage):
        print(f"  [{i}] ToolMessage ← {m.name} 返回：{m.content}")
    else:
        print(f"  [{i}] {type(m).__name__}：{m.content}")
star("循环的本质：模型每次只做一件事 —— 要么调工具，要么给答案；循环负责把工具结果塞回去")

# ============================================================
# 案例 2：拆开 create_agent —— 两个节点 + 一条条件边
# ============================================================
section("案例 2：手搭同一个循环（model 节点 + ToolNode + tools_condition）")

model = get_model([
    ai_tool("get_position", {"position_id": "P1002"}, "call_1"),
    ai_text("P1002 数据分析师目前在苏州处于'暂停'状态，负责人李娜。"),
])


def model_node(state: MessagesState):
    """① 思考：把当前全部消息给模型，它决定调工具还是收尾。"""
    return {"messages": [model.invoke(state["messages"])]}


builder = StateGraph(MessagesState)
builder.add_node("model", model_node)          # 思考
builder.add_node("tools", ToolNode(TOOLS))     # 行动（LangChain 自带的工具执行节点）
builder.add_edge(START, "model")
builder.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
builder.add_edge("tools", "model")             # ★ 这条回边，就是"循环"
graph = builder.compile()

out = graph.invoke({"messages": [HumanMessage(content="P1002 状态？")]})
print(f"\n  步数：{len(out['messages'])} 条消息")
print(f"  最后回答：{out['messages'][-1].content}")
star("tools_condition 只做一件事：看最后一条 AIMessage 有没有 tool_calls")
star("create_agent 帮你在 model 外面加了三样：system prompt、工具绑定、以及这个循环")

# ============================================================
# 案例 3：刹车 —— 循环必须有人管
# ============================================================
section("案例 3：三种刹车（步数上限 / 重复动作 / 空转）")

print("\n  ① 步数上限（recursion_limit）：")
loop_model = get_model([ai_tool("get_position", {"position_id": "P1001"}, f"c{i}") for i in range(10)])


def loop_node(state):
    return {"messages": [loop_model.invoke(state["messages"])]}


b2 = StateGraph(MessagesState)
b2.add_node("model", loop_node)
b2.add_node("tools", ToolNode(TOOLS))
b2.add_edge(START, "model")
b2.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
b2.add_edge("tools", "model")
g2 = b2.compile()
try:
    g2.invoke({"messages": [HumanMessage(content="查 P1001")]}, config={"recursion_limit": 4})
except Exception as e:
    print(f"      触发上限：{type(e).__name__} → {str(e).splitlines()[0][:90]}")

print("\n  ② 重复动作检测（同一个工具 + 同样参数调太多次）：")
seen: dict[str, int] = {}


def guard(state):
    """在工具执行前拦一刀：同样的调用超过 2 次就中断。

    注意：guard 排在 tools 之后时，状态里最后一条是 ToolMessage，
    所以要往回找最近的一条带 tool_calls 的 AIMessage。
    """
    last_ai = next((m for m in reversed(state["messages"]) if getattr(m, "tool_calls", None)), None)
    if last_ai is None:
        return {}
    for c in last_ai.tool_calls:
        key = f"{c['name']}:{c['args']}"
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 2:
            raise RuntimeError(f"【中止】重复动作 {key} 超过 2 次，模型在空转")
    return {}


b3 = StateGraph(MessagesState)
b3.add_node("guard", guard)
b3.add_node("model", loop_node)
b3.add_node("tools", ToolNode(TOOLS))
b3.add_edge(START, "guard")
b3.add_edge("guard", "model")
b3.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
b3.add_edge("tools", "guard")
try:
    b3.compile().invoke({"messages": [HumanMessage(content="查 P1001")]}, config={"recursion_limit": 20})
except RuntimeError as e:
    print(f"      {e}")
star("四道刹车：步数、token、时长、重复动作。create_agent 只内置了第一个")

practice([
    "把 tools_condition 换成自己的函数（比如 token 超 2000 就强制 END），体会条件边的自由度",
    "给 count_applications 加一个 page 参数，让模型必须分页取数，观察循环次数变化",
    "用 agent.astream() 打印每一步，找出'哪一步最慢'（第 17 章的 Trace 就从这里长出来）",
])
