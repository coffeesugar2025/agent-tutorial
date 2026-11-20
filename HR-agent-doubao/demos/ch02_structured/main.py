"""第 02 章：Prompt 与结构化输出（LangChain 版）。

跑法：python ch02_structured/main.py

四件事：
  1. 五部位 prompt 用 ChatPromptTemplate 写出来
  2. with_structured_output：让 pydantic 契约成为"模型的返回类型"
  3. 校验失败 → 把错误喂回去 → 重试（修复循环），并给 max_fix 上限
  4. evidence 字段：让幻觉自己暴露
"""

import sys, pathlib
from typing import Literal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, ValidationError

from common import ai_text, ai_tool, get_model, practice, section, star, title

# ============================================================
# 契约：模型必须按这个形状说话
# ============================================================
class JobProfile(BaseModel):
    """岗位画像。字段全部必填，缺一个就校验失败。"""
    title: str = Field(description="岗位名称，如 高级前端工程师")
    city: str = Field(description="工作城市")
    years: str = Field(description="经验要求，如 3-5年")
    must_have: list[str] = Field(description="硬性门槛，逐条列出")
    skills: list[str] = Field(description="核心技能，最多 6 项")
    risk: str = Field(description="这条 JD 的风险点；没看出风险就写'无'")


class EvidenceField(BaseModel):
    """每个字段都挂一个原文依据，没有依据就必须给 null。"""
    value: str | None = Field(description="抽取到的值；原文没有就填 null")
    evidence: str | None = Field(description="支撑该值的原文片段；没有就填 null")


class CandidateFacts(BaseModel):
    姓名: EvidenceField
    最高学历: EvidenceField
    工作年限: EvidenceField


# ============================================================
# 案例 1：五部位 prompt
# ============================================================
title("案例 1：把 prompt 拆成五个部位（用 ChatPromptTemplate 落成模板）")

PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     # ① 角色 ② 任务 ③ 约束 ④ 输出格式 ⑤ 兜底（不知道怎么办）
     "你是招聘 HR 的结构化抽取器。\n"
     "任务：把 JD 文本解析成岗位画像。\n"
     "约束：只依据 JD 原文，不得引入外部知识；JD 里没写的字段填空字符串。\n"
     "输出：必须符合给定的 JSON Schema，不要输出任何解释。\n"
     "兜底：无法判断的字段，value 填 null 并在 evidence 里说明'原文未提及'。"),
    ("human", "<jd>\n{jd}\n</jd>"),
])

JD = """高级前端工程师 / 苏州 / 3-5 年 / 统招本科
负责集团 HR 中台前端，Vue3 + TypeScript，要求有工程化与性能优化经验。
有大厂或中大型项目经验优先。"""

# 让剧本模拟"第一次缺字段、第二次学乖"——这就是真实修复循环的样子
model = get_model([
    ai_tool("JobProfile", {                     # ① 第一次：少给了 risk 和 must_have
        "title": "高级前端工程师", "city": "苏州", "years": "3-5年",
        "skills": ["Vue3", "TypeScript", "工程化", "性能优化"],
    }, call_id="call_1"),
    ai_tool("JobProfile", {                     # ② 第二次：补齐
        "title": "高级前端工程师", "city": "苏州", "years": "3-5年",
        "must_have": ["统招本科", "有大厂或中大型项目经验"],
        "skills": ["Vue3", "TypeScript", "工程化", "性能优化"],
        "risk": "经验区间与薪资带宽可能不匹配",
    }, call_id="call_2"),
])

structured = model.with_structured_output(JobProfile)     # ★ 契约变成"返回类型"
chain = PROMPT | structured

print("\n  ① 第一次调用（剧本故意少给字段）：")
try:
    print("    ", chain.invoke({"jd": JD}))
except ValidationError as e:
    print(f"     校验失败：{e.error_count()} 处 —— {str(e).splitlines()[1].strip()}")

print("\n  ② 把校验错误喂回模型，再试一次：")
fixed = chain.invoke({"jd": JD})
print("     title    =", fixed.title)
print("     must_have=", fixed.must_have)
print("     risk     =", fixed.risk)
star("with_structured_output 内部就是 tool-calling + Pydantic 解析；校验不过它自己会抛错")
star("'校验失败'不是异常事故，是设计的一部分：契约越严，模型越难蒙混")

# ============================================================
# 案例 2：修复循环要有上限
# ============================================================
section("案例 2：修复循环（带 max_fix 上限，跑不通就抛错）")

def structured_call(schema, chain, payload, max_fix=2):
    """把'生成-校验-把错误喂回去'写成一个函数。

    ★ 三个要点：
      1. 错误信息要原样回灌给模型，它才知道错在哪
      2. 必须有上限，否则一条坏 schema 能把账单打爆
      3. 上限到了要抛错给上层，不能返回半个对象
    """
    messages = []
    last_err = None
    for attempt in range(1, max_fix + 2):
        try:
            return chain.invoke({**payload, "fix_hint": last_err or ""})
        except ValidationError as e:
            last_err = f"上一次输出不合法（{e.error_count()} 处）：{str(e).splitlines()[1].strip()}"
            print(f"    第 {attempt} 次失败 → {last_err}")
    raise RuntimeError(f"修复 {max_fix} 次仍失败，交人工处理：{last_err}")


# 造一份"怎么改都不合格"的剧本：所有回答都缺 must_have
bad_model = get_model([ai_tool("JobProfile", {"title": "x", "city": "苏州", "years": "3", "skills": []},
                               call_id=f"call_{i}") for i in range(4)])
bad_chain = PROMPT | bad_model.with_structured_output(JobProfile)
try:
    structured_call(JobProfile, bad_chain, {"jd": JD}, max_fix=2)
except RuntimeError as e:
    print("    ", e)
star("案例 2 的价值：证明'重试能救一切'是错觉。schema 与 prompt 打架时，重试只是多花钱")

# ============================================================
# 案例 3：evidence 字段 —— 让幻觉无处可藏
# ============================================================
section("案例 3：每抽一个字段，都要求它给出原文出处")

RESUME = """张伟 / 男 / 1995
2014-2018 苏州大学 计算机科学与技术 本科
2021-2024 某大厂 前端开发（Vue3）"""

model3 = get_model([ai_tool("CandidateFacts", {
    "姓名": {"value": "张伟", "evidence": "张伟 / 男 / 1995"},
    "最高学历": {"value": "本科", "evidence": "2014-2018 苏州大学 计算机科学与技术 本科"},
    "工作年限": {"value": None, "evidence": None},          # 原文没写年限，就不许编
}, call_id="call_3")])

facts = (ChatPromptTemplate.from_messages([
    ("system", "从简历中抽取字段。每个字段必须给出 evidence 原文片段；原文没有就 value=null。"),
    ("human", "<resume>\n{resume}\n</resume>"),
]) | model3.with_structured_output(CandidateFacts)).invoke({"resume": RESUME})

for k in ("姓名", "最高学历", "工作年限"):
    f = getattr(facts, k)
    mark = "✓" if f.evidence else "（缺失）"
    print(f"    {k}: {f.value!r} {mark}  evidence={f.evidence!r}")


def validate_evidence(facts: CandidateFacts, resume: str) -> list[str]:
    """校验 evidence 是不是真的出现在原文里（防模型编造引用）。"""
    problems = []
    for name in ("姓名", "最高学历", "工作年限"):
        f = getattr(facts, name)
        if f.value is None:
            continue
        if not f.evidence:
            problems.append(f"{name} 有值但没有 evidence")
        elif f.evidence not in resume:
            problems.append(f"{name} 的 evidence 在原文里找不到：{f.evidence!r}")
    return problems


problems = validate_evidence(facts, RESUME)
print(f"\n  evidence 校验：{'通过' if not problems else problems}")
star("一条规则顶一百句'不要编造'：evidence 必须能在原文里 grep 到")

practice([
    "把 JobProfile 的 risk 改成 Literal['有','无']，观察模型被迫做选择时的行为变化",
    "把 max_fix 从 2 改成 10，统计调用次数，体会'终止条件'的成本意义",
    "故意把 evidence 改成原文里没有的句子，看 validate_evidence 能不能抓住",
])
