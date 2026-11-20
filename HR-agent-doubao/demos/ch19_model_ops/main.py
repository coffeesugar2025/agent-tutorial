"""第 19 章：模型工程 —— 路由、参数、成本、本地部署、要不要自训。

跑法：python ch19_model_ops/main.py

这一章不训练模型（要 GPU），只解决工程问题：
  ① 一个系统里到底要几个模型？（答案：按任务分档，不是全用最贵的）
  ② init_chat_model 怎么一行切换厂商
  ③ 成本/延迟怎么算，路由错了亏在哪
  ④ 什么时候该上 LoRA，什么时候纯属浪费钱
"""

import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain_core.prompts import ChatPromptTemplate

from common import ai_text, get_model, has_real_model, practice, section, star, title

title("案例 1：一个 HR Agent 里，其实有三档模型")

TIERS = [
    ("T1 轻量", "qwen-turbo / gpt-4o-mini", "意图分类、字段抽取、改写查询", 0.0008, "P50 < 1s"),
    ("T2 主力", "deepseek-chat / qwen-plus", "答案生成、多步推理、工具编排", 0.0040, "P50 2-4s"),
    ("T3 兜底", "gpt-4o / qwen-max", "复杂冲突仲裁、长文档核对", 0.0300, "P50 6-10s"),
]
print(f"  {'档位':<8}{'典型模型':<28}{'用在什么任务':<34}{'每千次成本(元)':<12}延迟")
for name, models, use, price, lat in TIERS:
    print(f"  {name:<8}{models:<28}{use:<34}{price * 1000:<12.1f}{lat}")
star("全用 T3 是最常见也最贵的错误：80% 的请求都是分类和抽取，用轻量档就够了")

# ============================================================
# 2) init_chat_model：一行切厂商
# ============================================================
section("案例 2：init_chat_model —— 换厂商只改一个字符串")
print("""
    from langchain.chat_models import init_chat_model

    llm = init_chat_model("openai:gpt-4o-mini", temperature=0)      # OpenAI
    llm = init_chat_model("deepseek:deepseek-chat")                  # DeepSeek（需 langchain-deepseek）
    llm = init_chat_model("ollama:qwen2.5:7b", base_url="http://localhost:11434")   # 本地
    llm = init_chat_model("openai:qwen-plus", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    #  ↑ 任何 OpenAI 兼容服务（vLLM / Xinference / SGLang / 通义 / 智谱）都走这一条
""")
print(f"  当前环境有没有真 Key：{has_real_model()}（没有就继续用 ScriptedChatModel，逻辑完全一致）")

# ============================================================
# 3) 路由：按任务难度 + 预算决定用哪个档
# ============================================================
section("案例 3：路由表 —— 规则路由 vs 学习路由")

ROUTE_RULES = {
    "intent": ("T1", "分类任务，答案空间只有几个标签"),
    "extract": ("T1", "抽取任务，输出受 schema 约束"),
    "qa_policy": ("T2", "制度问答，需要读 2-3 段资料并组织语言"),
    "multi_step": ("T2", "多步工具编排，需要稳定遵循格式"),
    "arbitrate": ("T3", "薪酬/合规冲突仲裁，错了要赔钱"),
}


def route(task: str, budget_left: float) -> tuple[str, str]:
    """★ 先按任务分档，再看预算：预算紧就降档，但'仲裁'类不许降。"""
    tier, why = ROUTE_RULES.get(task, ("T2", "未分类任务默认主力档"))
    if budget_left < 0.05 and tier != "T3":
        return "T1", why + "；预算不足，降档"
    return tier, why


for task in ["intent", "qa_policy", "arbitrate"]:
    t, why = route(task, budget_left=1.0)
    print(f"    {task:<12} → {t}   （{why}）")
print(f"    预算只剩 0.02 时 qa_policy → {route('qa_policy', 0.02)[0]}（降档，但会提示'回答可能粗糙'）")
print(f"    预算只剩 0.02 时 arbitrate → {route('arbitrate', 0.02)[0]}（红线条目不降档）")

# ============================================================
# 4) 成本测算
# ============================================================
section("案例 4：成本 = 输入 tokens × 单价 + 输出 tokens × 单价（输出通常贵 2-4 倍）")


def cost(in_tok: int, out_tok: int, in_price: float, out_price: float) -> float:
    return in_tok / 1000 * in_price + out_tok / 1000 * out_price


plans = [
    ("全用 T3", 1.0, 3000, 400, 0.03, 0.06),
    ("全用 T1", 1.0, 3000, 400, 0.0008, 0.0016),
    ("分档（80/15/5）", 0.8 * 0.0008 + 0.15 * 0.004 + 0.05 * 0.03, 3000, 400, 0.008, 0.016),
]
print(f"  {'方案':<16}{'每千次请求成本(元)':<18}{'年化(日均 1 万次)'}")
for name, price_in, it, ot, pin, pout in plans:
    per = cost(it, ot, pin, pout) * 1000
    print(f"  {name:<16}{per:<18.1f}{per * 3650:,.0f} 元")
star("成本优化的顺序：① 减输入（上下文裁剪/检索按需）② 分档 ③ 缓存 ④ 才轮到换更便宜的模型")

# ============================================================
# 5) 参数调优：三个真正影响结果的旋钮
# ============================================================
section("案例 5：参数不是随便填的")
params = [
    ("temperature", "0：抽取/分类/工具调用必用；0.7：文案/邮件草稿", "越高越发散，结构化任务直接崩"),
    ("max_tokens", "按任务定：分类 5，抽取 300，生成 1200", "不设上限 = 不设预算"),
    ("stop", "工具调用场景加 stop=['\\n\\nObservation']", "让模型别自己编造工具返回"),
    ("response_format / JSON Mode", "能和 with_structured_output 一起用时优先用它", "比 prompt 里写'请返回 JSON'可靠一个量级"),
]
for a, b, c in params:
    print(f"    {a:<26}{b:<40}{c}")

# ============================================================
# 6) 本地部署与自训的判据
# ============================================================
section("案例 6：什么时候该自部署、什么时候该上 LoRA")

for line in [
    "自部署（vLLM / SGLang / Ollama / Xinference）的合理理由：",
    "① 数据不能出内网（HR 数据是典型）  ② 调用量大到 API 成本高于 GPU 成本  ③ 需要固定延迟",
    "   Ollama：一条命令、适合开发机与 7B 以下；vLLM/SGLang：吞吐高、要 Linux + CUDA",
    "",
    "上 LoRA 的判据（满足 2 条以上才值得）：",
    "① 任务是'风格/格式'问题，不是知识问题（如固定格式的面试评价）",
    "② 有 500+ 条高质量标注样本（少于此，prompt + few-shot 通常更好）",
    "③ 每次调用都要塞 2000 字 few-shot，成本已经压不下来",
    "④ 通用模型在这类任务上反复失败，且失败模式稳定（说明是能力缺口，不是提示问题）",
    "",
    "不该上 LoRA 的：知识问答（LoRA 记不住新制度）、要经常改口径的业务（改 prompt 比重训便宜）、",
    "样本少于 200 条、连评测集都没有（训完无法判断好坏）。",
]:
    print(f"    {line}")

# ============================================================
# 7) 同一道题，不同档位的实际差别（用剧本演示质量差异）
# ============================================================
section("案例 7：路由错了会怎样（同一问题的三个档位输出）")
q = "候选人 C1024 期望 28K，岗位带宽 22-25K，能否直接发 offer？"
outs = {
    "T1": "可以直接发，28K 不算高。",
    "T2": "超带宽 3K，不能直接发，需走薪酬特批流程。",
    "T3": "不能直接发。带宽上限 25K，28K 超 3K（12%），需 HRBP 发起薪酬特批 → 薪酬负责人审批 → HRD 确认；"
          "同时需在 offer 中标注特批单号，并留存审批记录以备审计。",
}
prompt = ChatPromptTemplate.from_messages([("system", "回答 HR 政策问题。"), ("human", "{q}")])
for tier, text in outs.items():
    ans = (prompt | get_model([ai_text(text)])).invoke({"q": q}).content
    print(f"    {tier}：{ans}")
star("同一问题三档输出：T1 会闯祸、T2 够用、T3 才敢上审计。所以'该用哪档'由**风险**决定，不由价格决定")

practice([
    "给 route() 加一个'失败重试升档'：T2 输出校验不过 → 自动升 T3 重跑一次",
    "用 tiktoken 算真实输入 tokens，把成本表换成你自己的业务数据",
    "写一个 5 条用例的小评测，对比 T1/T2/T3 的准确率与成本，算出'每正确一次多少钱'",
])
