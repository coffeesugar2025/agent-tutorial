"""第 00 章：LangChain 版最小 Agent —— 用 create_agent 跑通“查余额 → 查制度 → 回答”。

运行：python code/ch00_hello_agent.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain.agents import create_agent
from langchain_core.tools import tool

from common.data import all_policy_documents, employee
from common.lc import TracerCallbackHandler, final_text, get_chat_model, tool_names

QUESTION = "我的工号E1001，我下个月想休 3 天年假，够不够？需要提前几天申请？"


@tool
def get_leave_balance(employee_id: str) -> str:
    """查询员工的年假与病假余额（只读）。employee_id 是工号，如 E1001。"""
    person = employee(employee_id)
    if person is None:
        raise ValueError(f"工号 {employee_id} 不存在")
    leave = person["leave"]
    print("============== get_leave_balance start ==========")
    return json.dumps(
        {
            "employee_id": employee_id,
            "name": person["name"],
            "annual_remaining": leave["annual_total"] - leave["annual_used"],
            "sick_remaining": leave["sick_total"] - leave["sick_used"],
        },
        ensure_ascii=False,
    )


@tool
def search_policy(keyword: str) -> str:
    """检索生效中的 HR 制度原文（只读）。keyword 是关键词，如 申请；返回文档编号与版本。"""

    hits = []
    print("============== search_policy start ==========")
    for doc in all_policy_documents():
        if doc["status"] != "active":
            continue  # 旧版本制度不参与回答，避免口径冲突
        for line in doc["content"].splitlines():
            if keyword in line and len(line.strip()) > 4:
                hits.append({"doc_id": doc["doc_id"], "version": doc["version"], "text": line.strip()})
    return json.dumps(hits[:2], ensure_ascii=False)


SCRIPT = [
    {"tool_calls": [{"name": "get_leave_balance", "args": {"employee_id": "E1001"}}]},
    {"tool_calls": [{"name": "search_policy", "args": {"keyword": "申请"}}]},
    {"content": "张伟，你今年还剩 13 天年假，休 3 天够用。按 HR-LEAVE-2025（2025.1）第 2.3 条，"
                "需提前 3 个工作日提交申请；连续休假不超过 3 天由直属主管审批。"},
]


def hello_agent() -> None:
    print("=== 1. 员工提问 ===\n" + QUESTION)
    model = get_chat_model(script=SCRIPT)  # 无 Key 时自动退回 MockChatModel
    agent = create_agent(
        model=model,
        tools=[get_leave_balance, search_policy],
        system_prompt="你是 HR 服务台助手：回答前必须先用工具核实余额与制度，禁止凭记忆作答；拿不到证据就说不知道。",
    )
    tracer = TracerCallbackHandler()
    state = agent.invoke(
        {"messages": [("user", QUESTION)]},
        config={"recursion_limit": 10, "callbacks": [tracer]},
    )

    print("\n=== 2. 消息序列（循环就藏在这里） ===")
    for index, message in enumerate(state["messages"], 1):
        calls = [call["name"] for call in getattr(message, "tool_calls", []) or []]
        print(f"[{index}] {type(message).__name__:<12} tool_calls={calls} content={str(message.content)[:56]}")

    print("\n=== 3. 最终回答 ===\n" + final_text(state))
    print("\n=== 4. 回调指标 ===")
    print(tracer.summary())

    # assert "13 天" in final_text(state) and "3 个工作日" in final_text(state), "回答必须用上两次工具结果"
    # assert tool_names(state) == ["get_leave_balance", "search_policy"], "模型应先查余额、再查制度"
    # assert tracer.summary()["llm_calls"] == 3 and tracer.summary()["tool_calls"] == 2, "3 次模型调用、2 次工具"
    # print("\n全部断言通过：create_agent 自己转完了“模型 → 工具 → 模型”。")
