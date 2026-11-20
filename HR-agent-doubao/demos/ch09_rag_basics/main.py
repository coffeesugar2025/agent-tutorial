"""第 09 章：RAG 基础层 —— 解析、切片、向量化、召回、拼 Prompt。

跑法：python ch09_rag_basics/main.py

LangChain 侧用到的原语（一条 RAG 链就能串起来）：
  TextLoader / RecursiveCharacterTextSplitter / InMemoryVectorStore / Retriever / LCEL
"""

import sys, pathlib, re

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain_core.documents import Document
from common.embed import LocalHashEmbedding
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

from common import ai_text, get_model, practice, section, star, title

ROOT = pathlib.Path(__file__).resolve().parent
RAW = ROOT / "knowledge" / "sop_leave.md"

# ============================================================
# 1) 切片的三个参数怎么定
# ============================================================
title("案例 1：同一份 SOP，三种切片方式的差别")

text = RAW.read_text(encoding="utf-8")
print(f"  原文 {len(text)} 字，{text.count(chr(10)) + 1} 行")

splitters = {
    "固定 80 字（不对）": RecursiveCharacterTextSplitter(chunk_size=80, chunk_overlap=0, separators=[""]),
    "按段落（次优）": RecursiveCharacterTextSplitter(chunk_size=140, chunk_overlap=20, separators=["\n\n", "\n"]),
    "按标题层级（对）": RecursiveCharacterTextSplitter(chunk_size=110, chunk_overlap=0,
                                                separators=["\n## "], keep_separator=True),
}
for name, sp in splitters.items():
    chunks = sp.split_text(text)
    print(f"\n  {name} → {len(chunks)} 块，平均 {sum(len(c) for c in chunks) // len(chunks)} 字")
    for c in chunks[:2]:
        head = c.strip().replace("\n", " / ")[:52]
        print(f"      · {head}…")
star("切片不是越小越好：切断了'条件—结论'，检索出来的就是一句没用的话")

# ★ 关键：给每块挂元数据（来源、章节、版本、生效日期）
chunks = splitters["按标题层级（对）"].split_text(text)
docs = []
for i, c in enumerate(chunks):
    title_line = c.strip().splitlines()[0].lstrip("# ").strip() if c.strip() else f"段{i}"
    docs.append(Document(page_content=c, metadata={"source": RAW.name, "section": title_line,
                                                   "version": "v3", "updated": "2026-09-01"}))

# ============================================================
# 2) 建库 + 检索
# ============================================================
section("案例 2：召回质量取决于'查询写法'，不只是向量库")

store = InMemoryVectorStore(LocalHashEmbedding())
store.add_documents(docs)
retriever = store.as_retriever(search_kwargs={"k": 3})

for q in ["年假怎么请", "试用期员工有年假吗", "年假没休完能折钱吗"]:
    hits = retriever.invoke(q)
    print(f"\n  问：{q}")
    for d in hits:
        print(f"    ← [{d.metadata['section']}] {d.page_content.strip().splitlines()[0][:44]}")

# ============================================================
# 3) 一条完整的 RAG 链（LCEL）
# ============================================================
section("案例 3：RAG 链 = 检索 + 拼 Prompt + 生成 + 输出解析")

PROMPT = ChatPromptTemplate.from_messages([
    ("system", "只根据下面的资料回答，资料里没有就说'制度里没写，建议咨询 HRBP'。"
               "回答末尾用 [来源: 章节] 标注。\n\n资料：\n{context}"),
    ("human", "{question}"),
])

def format_docs(ds):
    return "\n\n".join(f"[{d.metadata['section']}] {d.page_content}" for d in ds)

rag = (
    {"context": (lambda x: x["question"]) | retriever | format_docs, "question": lambda x: x["question"]}
    | PROMPT
    | get_model([ai_text("转正后按司龄计算年假：满 1 年 5 天，满 3 年 7 天。试用期不单独计算，转正后按入职日期折算。 [来源: 年假天数]")])
    | StrOutputParser()
)

ans = rag.invoke({"question": "试用期员工有年假吗？"})
print(f"\n  问：试用期员工有年假吗？\n  答：{ans}")
star("LCEL 的并行字典写法：{context: 检索链, question: 原样透传} —— 一个 dict 就是并行分支")

# ============================================================
# 4) 检索失败长什么样（这才是要防的）
# ============================================================
section("案例 4：三种典型失败")
bad = [
    ("召回到了但没答到", "切片把'条件'和'结论'拆开 → 只召回半句"),
    ("答了但没来源", "prompt 没强制引用 → 用户无法核对，幻觉无从追责"),
    ("该说没有却说有", "没给'资料里没有就说没有'的兜底话术 → 模型自己编"),
]
for name, why in bad:
    print(f"    {name:<12} {why}")

print("\n  三个最低成本的兜底：")
for line in [
    "① prompt 里写死'资料里没有就说没有'，并给出替代动作（找谁）",
    "② 强制 [来源: 章节] 标注，答案里没有来源就当失败",
    "③ 检索分数低于阈值时不要硬答，直接转人工/追问",
]:
    print(f"    {line}")

practice([
    "把 separators 改成 ['\\n## ', '\\n\\n']，看'年假没休完能折钱吗'的召回变化",
    "给 Document.metadata 加 effective_from，检索时过滤掉未生效版本",
    "在 rag 链前面加一个'查询改写'步骤（把口语问题改成制度术语），比较召回",
])
