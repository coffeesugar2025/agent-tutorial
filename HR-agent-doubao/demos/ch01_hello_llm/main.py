"""第 01 章：第一次调用大模型 —— 用 LangChain 的 Runnable 链路。

跑法：python ch01_hello_llm/main.py

三个递进：
  1. 最短的一条链：Prompt → Model → Parser
  2. 消息对象与水牌（System/Human/AI），以及 LCEL 的 | 到底在做什么
  3. 流式输出：stream() 与 invoke() 的区别
"""

import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import SystemMessage, HumanMessage

from common import ai_text, get_model, practice, section, star, title

# ============================================================
# 案例 1：最短的链
# ============================================================
title("案例 1：Prompt | Model | Parser —— LangChain 的最小骨架")

prompt = ChatPromptTemplate.from_messages([
    ("system", "你是苏州智造集团的 HR 助手。回答不超过 40 字，不编造制度条款。"),
    ("human", "候选人 {name} 应聘 {position}，帮我写一句面试邀约开场白。"),
])

model = get_model([ai_text("张伟您好，感谢投递高级前端工程师岗位。想约您周四 14:00 聊 45 分钟。")])
parser = StrOutputParser()

chain = prompt | model | parser          # ★ 这个 | 就是 LCEL：把 Runnable 串成一条链

print(f"\n  链的类型：{type(chain).__name__}")
print(f"  输入：{{'name': '张伟', 'position': '高级前端工程师'}}")
print(f"  输出：{chain.invoke({'name': '张伟', 'position': '高级前端工程师'})}")
star("prompt / model / parser 都是 Runnable，所以能拼；换掉其中任何一段，链的形状不变")

# ============================================================
# 案例 2：消息对象 —— 你真正在调的是"一组消息"
# ============================================================
section("案例 2：三种消息角色")

messages = [
    SystemMessage(content="你是 HR 助手，只回答制度问题，其余转 HRBP。"),
    HumanMessage(content="入职满一年有几天年假？"),
]
model2 = get_model([ai_text("按《员工手册》第十四条，满 1 年不满 5 年享年假 7 天。")])
reply = model2.invoke(messages)

print(f"\n  发出去的消息：{[type(m).__name__ for m in messages]}")
print(f"  回来的消息：{type(reply).__name__}")
print(f"  内容：{reply.content}")
print(f"  ★ 关键认知：模型是无状态的，'记得上文'是你每次把历史消息重新发一遍的结果")
star("第 07 章（Memory）要解决的，就是'这段历史到底怎么攒、怎么裁'")

# ============================================================
# 案例 3：流式输出
# ============================================================
section("案例 3：invoke 一次性返回 vs stream 逐段返回")

chain3 = ChatPromptTemplate.from_messages([("human", "{q}")]) | get_model([
    ai_text("年假天数按累计工作年限分三档：1-5 年 7 天，5-10 年 10 天，10 年以上 15 天。")
]) | StrOutputParser()

print("\n  stream() 的输出片段：")
for i, chunk in enumerate(chain3.stream({"q": "年假怎么算？"}), 1):
    print(f"    [{i}] {chunk!r}")
star("前端的'打字机效果'就是拿 stream()：每来一段就 append 到界面上，而不是等整段回来")

print()
print("  为什么要流式：")
print("    · 首字延迟（TTFT）从 3s 降到 0.3s，用户体感完全不同")
print("    · 工具调用场景必须流式，否则用户盯着转圈 10 秒不知道在干什么（第 18 章）")

# ============================================================
# 案例 4：把参数抽出来 —— 一条链服务所有岗位
# ============================================================
section("案例 4：同一条链，换输入就换场景")

chain4 = (
    ChatPromptTemplate.from_messages([
        ("system", "你是招聘助手。用一句话总结岗位卖点，不超过 25 字。"),
        ("human", "岗位：{position}；城市：{city}；要求：{requirement}"),
    ])
    | get_model([
        ai_text("苏州园区核心位置，Vue3 主栈，团队有前端基建沉淀。"),
        ai_text("制造业数字化一线，能接触 MES 与产线数据。"),
    ])
    | StrOutputParser()
)

for job in [
    {"position": "高级前端工程师", "city": "苏州", "requirement": "Vue3 + TypeScript，3-5 年"},
    {"position": "数据分析师", "city": "苏州", "requirement": "SQL + Python，懂制造业务"},
]:
    print(f"  {job['position']}：{chain4.invoke(job)}")

practice([
    "把案例 1 的 system prompt 删掉，看输出风格怎么变（这就是 system 的作用）",
    "给案例 3 的链加一个 RunnableLambda（把输出转大写），体会'任何函数都能进链'",
    "把 .env 配上真 Key，重跑案例 3，对比假模型与真模型的流式粒度差异",
])
