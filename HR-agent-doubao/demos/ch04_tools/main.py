"""第 04 章：Tool / Function Calling —— 工具写不好，Agent 就不可能靠谱。

跑法：python ch04_tools/main.py

LangChain 侧的重点：
  1. @tool 装饰器：docstring 就是工具描述，Pydantic 模型就是参数 schema
  2. 描述质量决定调用准确率（同一个功能，两种描述，两种结果）
  3. 工具报错怎么回填（handle_tool_error），以及哪些错误不该重试
  4. 写操作默认不注入（allow_write 门禁）
"""

import sys, pathlib
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool, ToolException
from pydantic import BaseModel, Field

from common import ai_text, ai_tool, get_model, practice, section, star, title

# ============================================================
# 数据（虚构）
# ============================================================
EMPLOYEES = {
    "E10086": {"name": "张伟", "dept": "技术中心", "city": "苏州", "level": "P6", "status": "active"},
    "E10087": {"name": "李娜", "dept": "人力资源部", "city": "苏州", "level": "P5", "status": "probation"},
}
LEAVE = {("E10086", 2026): {"年假": 7, "调休": 3}, ("E10087", 2026): {"年假": 0, "调休": 1}}
POLICY = {
    "年假": "第十四条 员工累计工作满 1 年不满 5 年的，年假 7 天；满 5 年不满 10 年 10 天；满 10 年以上 15 天。",
    "病假": "第十五条 病假须提交二级以上医院诊断证明，全年累计不超过 30 天。",
    "调休": "第十六条 加班可申请调休，有效期 6 个月，过期作废。",
}


# ============================================================
# 工具 1：参数用 Pydantic 约束（比裸类型安全得多）
# ============================================================
class LeaveInput(BaseModel):
    """查询员工某年度剩余假期的入参。"""
    emp_id: str = Field(pattern=r"^E\d{5}$", description="工号，形如 E10086")
    year: int = Field(ge=2020, le=2030, description="年度，如 2026")
    leave_type: Literal["年假", "调休", "病假"] = Field(description="假期类型")


@tool("get_leave_balance", args_schema=LeaveInput)
def get_leave_balance(emp_id: str, year: int, leave_type: str) -> str:
    """查询员工某年度剩余假期天数。用户问"我还有几天年假/调休"时用。

    年假与调休分开计算，不可互换；病假不走这个工具（需医院证明，走审批流程）。
    """
    if leave_type == "病假":
        raise ToolException("病假余额需走审批系统查询，本工具不支持")
    bal = LEAVE.get((emp_id, year), {}).get(leave_type)
    if bal is None:
        raise ToolException(f"没有 {emp_id} 在 {year} 年的假期记录，请确认工号与年度")
    return f"{emp_id} {year} 年{leave_type}剩余 {bal} 天"


# ============================================================
# 工具 2：描述写得含糊，模型就会调错（反面教材）
# ============================================================
@tool
def q_emp(e: str) -> str:
    """查信息"""
    return str(EMPLOYEES.get(e, "无"))


@tool("get_employee")
def get_employee_good(emp_id: str) -> str:
    """按工号查询在职员工的基本信息（姓名、部门、城市、职级、状态）。

    只接受以 E 开头的 5 位数字工号，如 E10086。查不到时返回明确提示，不要重试。
    """
    e = EMPLOYEES.get(emp_id)
    return f"{e['name']} / {e['dept']} / {e['city']} / {e['level']} / {e['status']}" if e else f"没有工号 {emp_id}"


# ============================================================
# 工具 3：检索制度条款
# ============================================================
@tool
def search_policy(keyword: str) -> str:
    """在公司制度中检索条款原文。用户问假期天数、审批流程、制度规定时使用。

    返回带条款号的原文；查不到就返回"未规定"，不要自行推断。
    """
    hit = [v for k, v in POLICY.items() if keyword in k or keyword in v]
    return "\n".join(hit) if hit else "制度中未规定该事项"


# ============================================================
# 工具 4：写操作
# ============================================================
INTERVIEWS: list[dict] = []


@tool
def create_interview(candidate_id: str, time: str, interviewer: str) -> str:
    """创建面试（写操作）。仅在用户明确确认时间与面试官后调用。

    candidate_id 形如 C1001，time 形如 2026-11-19 14:00。
    """
    INTERVIEWS.append({"candidate_id": candidate_id, "time": time, "interviewer": interviewer})
    return f"已创建面试：{candidate_id} @ {time}，面试官 {interviewer}（共 {len(INTERVIEWS)} 场）"


READ_TOOLS = [get_leave_balance, get_employee_good, search_policy]
ALL_TOOLS = READ_TOOLS + [create_interview]


def build_tools(allow_write: bool = False):
    """★ 权限门禁：写操作默认不给模型看见，而不是靠 prompt 求它别调。"""
    return ALL_TOOLS if allow_write else READ_TOOLS


# ============================================================
# 案例 1：描述质量对比
# ============================================================
title("案例 1：两种工具描述，模型的选择完全不同")

print(f"\n  含糊版 q_emp 的 schema：")
print(f"    name        = {q_emp.name}")
print(f"    description = {q_emp.description!r}")
print(f"    args        = {list(q_emp.args.keys())}")
print(f"\n  合格版 get_employee 的 schema：")
print(f"    name        = {get_employee_good.name}")
print(f"    description = {get_employee_good.description.splitlines()[0]!r} …")
print(f"    args        = {get_employee_good.args}")
star("模型选工具只看两样：name + description。描述含糊 = 100% 调错或干脆不调")

agent = create_agent(get_model([
    ai_tool("get_employee", {"emp_id": "E10086"}, "c1"),
    ai_text("张伟在技术中心，苏州，P6，在职。"),
]), tools=[get_employee_good], system_prompt="你是 HR 助手")
print("\n  调用过程：")
for m in agent.invoke({"messages": [HumanMessage(content="张伟是哪个部门的？")]})["messages"]:
    if getattr(m, "tool_calls", None):
        print(f"    调 {m.tool_calls[0]['name']}({m.tool_calls[0]['args']})")
    elif type(m).__name__ == "ToolMessage":
        print(f"    返回：{m.content}")
    elif type(m).__name__ == "AIMessage" and m.content:
        print(f"    回答：{m.content}")

# ============================================================
# 案例 2：参数错 → ToolException → 模型自我修正
# ============================================================
section("案例 2：工具报错要回填给模型，让它自己改参数")

bad_then_good = create_agent(
    get_model([
        ai_tool("get_leave_balance", {"emp_id": "E1008", "year": 2026, "leave_type": "年假"}, "c1"),
        ai_tool("get_leave_balance", {"emp_id": "E10086", "year": 2026, "leave_type": "年假"}, "c2"),
        ai_text("张伟 2026 年还剩 7 天年假。"),
    ]),
    tools=[get_leave_balance],
    system_prompt="你是 HR 助手。工具报参数错误时，按提示修正后重试一次。",
)

print()
for m in bad_then_good.invoke({"messages": [HumanMessage(content="张伟还有几天年假？")]})["messages"]:
    if getattr(m, "tool_calls", None):
        print(f"    调 {m.tool_calls[0]['args']}")
    elif type(m).__name__ == "ToolMessage":
        print(f"    返回（status={m.status}）：{m.content.splitlines()[0]}")
    elif m.type == "ai" and m.content:
        print(f"    回答：{m.content}")
star("ToolMessage 带 status='error' —— 模型看得见这次失败，才有机会改")

# ============================================================
# 案例 3：写操作门禁
# ============================================================
section("案例 3：同一个请求，写权限关闭 vs 打开")

question = "帮张伟约一场技术一面，周四 14:00，面试官王强"

print(f"\n  提问：{question}")
print(f"  ① allow_write=False → 模型能看到 {len(build_tools(False))} 个工具，其中没有 create_interview")

ro = create_agent(get_model([ai_text("我目前只能查询，不能创建面试。请先在系统里走面试申请流程。")]),
                  tools=build_tools(False), system_prompt="你是 HR 助手")
print(f"     回答：{ro.invoke({'messages': [HumanMessage(content=question)]})['messages'][-1].content}")

print(f"\n  ② allow_write=True → 模型能看到 {len(build_tools(True))} 个工具")
rw = create_agent(get_model([
    ai_tool("create_interview", {"candidate_id": "C1001", "time": "2026-11-19 14:00", "interviewer": "王强"}, "c1"),
    ai_text("已创建面试，稍后给候选人和面试官发出通知。"),
]), tools=build_tools(True), system_prompt="你是 HR 助手")
print(f"     回答：{rw.invoke({'messages': [HumanMessage(content=question)]})['messages'][-1].content}")
print(f"     实际创建：{INTERVIEWS}")
star("最小权限原则：写工具不该出现在'能查但没审批'的会话里")
star("进阶做法是第 14 章：让写操作触发 interrupt，人在环上确认后才真正落库")

practice([
    "把 q_emp 的描述改成和 get_employee 一样详细，观察模型是否还会调它",
    "给 create_interview 加一个幂等键参数，重复调用返回同一张票（第 15 章会用到）",
    "把 5 个工具一起给模型，看它会不会拿 search_policy 去查员工信息（工具越多越容易挑错）",
])
