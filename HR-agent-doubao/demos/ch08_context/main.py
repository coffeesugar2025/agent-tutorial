"""第 08 章：Context Engineering —— Token 预算、裁剪、压缩。

跑法：python ch08_context/main.py

LangChain 侧的关键原语：
  · trim_messages —— 按 token 上限裁历史，还能保住 system 与最近几条
  · count_tokens —— 官方工具函数，传自己的 token_counter
  · 摘要压缩 —— 用一条普通 LCEL 链，把旧对话压成一段"事实清单"

三件事决定 Agent 会不会在第 30 轮突然崩：
  ① 预算：谁先被裁（顺序），② 压缩：压成什么（不是压成废话），③ 外部化：状态放哪（不放在 prompt 里）。
"""

import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage, trim_messages
from langchain_core.prompts import ChatPromptTemplate

from common import ai_text, get_model, practice, section, star, title

# ============================================================
# 0) 本地 token 估算（无 Key 也能算预算）
# ============================================================
def count_tokens(messages) -> int:
    """粗估：中文约 1 字 ≈ 1 token，英文约 4 字符 ≈ 1 token。真实项目用 tiktoken 或模型自带 tokenizer。"""
    if isinstance(messages, str):
        messages = [HumanMessage(messages)]
    total = 0
    for m in messages:
        total += 4                                    # 每条消息的固定开销
        text = m.content if isinstance(m.content, str) else str(m.content)
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        total += cjk + (len(text) - cjk) // 4
    return total


title("案例 1：一轮长对话，为什么必须裁剪")

system = SystemMessage("你是招聘助手。回答简洁，只用中文。不许编造员工信息。")
history = [
    HumanMessage("帮我看下 P1001 这个岗位的候选人"),
    AIMessage("这个岗位目前有 12 位候选人在流程中，最近更新的是 C1001。"),
    ToolMessage("C1001 | 张伟 | 技术中心 | 苏州 | P6 | 一面通过", tool_call_id="t1"),
    HumanMessage("C1001 期望薪资多少？"),
    AIMessage("C1001 期望 28K，岗位带宽 22-25K，超出 3K。"),
    ToolMessage("P1001 | 高级前端 | 技术中心 | 22-25K | 苏州", tool_call_id="t2"),
    HumanMessage("那能特批吗？走什么流程？"),
    AIMessage("超带宽需要走薪酬特批：HRBP 发起 → 薪酬负责人审批 → HRD 确认。"),
]
long_tail = [HumanMessage(f"再帮我看看第 {i} 个候选人的情况，越详细越好") for i in range(1, 12)]

msgs = [system, *history, *long_tail]
print(f"  原始上下文：{len(msgs)} 条，约 {count_tokens(msgs)} tokens")
print(f"  单条最长的消息：{max(count_tokens([m]) for m in msgs)} tokens")

# ============================================================
# 1) 预算 + 裁剪顺序
# ============================================================
section("案例 2：trim_messages —— 保谁、裁谁，有明确规则")

BUDGET = 220
trimmed = trim_messages(
    msgs,
    max_tokens=BUDGET,
    strategy="last",             # 从最新往前留（对话场景的默认）
    token_counter=count_tokens,
    include_system=True,         # ★ system 永远保
    start_on="human",            # 裁剪后不能以 AI/工具消息开头（很多模型会报错）
    allow_partial=False,
)
print(f"  预算 {BUDGET} → 剩余 {len(trimmed)} 条，约 {count_tokens(trimmed)} tokens")
for m in trimmed:
    role = type(m).__name__.replace("Message", "")
    print(f"    [{role}] {str(m.content)[:42]}")
star("裁剪不是'砍一半'：include_system + start_on 这两个开关，决定了裁完还能不能正常调用")

# ============================================================
# 2) 摘要压缩：把旧对话压成"事实清单"
# ============================================================
section("案例 3：摘要压缩 —— 压的是事实，不是标点")

SUMMARIZE = ChatPromptTemplate.from_messages([
    ("system", "把下面的对话压成不超过 80 字的事实清单。只保留：已确认的数据、已做的决定、待办。"
               "丢掉寒暄、重复、模型的解释过程。"),
    ("human", "{history}"),
])
summarizer = SUMMARIZE | get_model([ai_text(
    "已确认：P1001 高级前端，带宽 22-25K；C1001 张伟，技术中心，一面通过，期望 28K 超带宽 3K。"
    "待办：走薪酬特批（HRBP 发起→薪酬审批→HRD 确认）。"
)])

flat = "\n".join(f"[{type(m).__name__}] {m.content}" for m in history)
summary = summarizer.invoke({"history": flat}).content
print(f"  压缩前 {count_tokens(history)} tokens → 压缩后 {count_tokens([HumanMessage(summary)])} tokens")
print(f"  摘要：{summary}")

rebuild = [system, HumanMessage(f"【历史摘要】{summary}"), *trimmed[-2:]]
print(f"  重建后的上下文：{len(rebuild)} 条 / {count_tokens(rebuild)} tokens")
star("摘要必须保留'数字、决定、待办'三类；只保留'聊过什么'的摘要，等于把上下文压成了噪声")

# ============================================================
# 3) 六种压缩手段与适用场景
# ============================================================
section("案例 4：六种压缩，按'信息损失'从低到高排")
rows = [
    ("工具结果瘦身", "把 ToolMessage 的 JSON 只留用到的 3 个字段", "损失最小，优先做"),
    ("检索按需", "不把整篇 SOP 塞进去，只塞命中的 2 段", "RAG 场景必做"),
    ("去重合并", "同一事实重复出现 5 次 → 留 1 次", "长会话高频"),
    ("结构化抽取", "50 条消息 → 一张 {字段: 值} 表", "任务型对话最划算"),
    ("摘要压缩", "旧对话 → 一段事实清单", "超过 10 轮时启动"),
    ("截断", "只留最近 N 条", "兜底，会丢早期约束，慎用"),
]
for name, how, when in rows:
    print(f"    {name:<10} {how:<34} {when}")

# 工具结果瘦身：只留需要的字段
fat = ToolMessage('{"emp_id":"E1001","name":"张伟","dept":"技术中心","city":"苏州","level":"P6",'
                  '"id_card":"3205********1234","salary":28000,"bank":"6222****8888"}', tool_call_id="t3")
slim = ToolMessage('{"emp_id":"E1001","name":"张伟","dept":"技术中心","level":"P6"}', tool_call_id="t3")
print(f"\n    工具结果：{count_tokens([fat])} → {count_tokens([slim])} tokens（同时把敏感字段挡在模型之外）")

# ============================================================
# 4) 水位线：什么时候该压
# ============================================================
section("案例 5：水位线 —— 别等爆了再压")

def water_level(used: int, limit: int) -> str:
    r = used / limit
    if r < 0.6:
        return "🟢 正常：全量保留"
    if r < 0.85:
        return "🟡 预警：启动结构化抽取 / 检索按需"
    return "🔴 危险：强制摘要压缩 + 外置状态，并给用户提示'我需要重新确认一下'"


for used in (400, 1200, 1900):
    print(f"    已用 {used}/2000 tokens → {water_level(used, 2000)}")

print("\n  外置状态（不放进 prompt 的那部分）：")
for line in [
    "· 计划、待办、已执行步骤 → 放 LangGraph state / 数据库，按需取摘要",
    "· 大文档 → 放向量库，按需检索两段",
    "· 长工具输出 → 放文件/对象存储，只把'结果 + 关键字段'回填",
]:
    print(f"    {line}")
star("上下文工程的核心不是'压缩技巧'，是'决定什么不放进上下文'")

practice([
    "把 count_tokens 换成 tiktoken 的 cl100k_base，对比估算误差",
    "给 trim_messages 加 max_tokens=120 试一次，看早期约束（不许编造）是否被裁掉",
    "写一个'每 5 轮自动摘要一次'的循环，观察摘要里最先丢的是哪类信息",
])
