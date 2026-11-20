"""第 10 章：RAG 进阶层 —— 混合检索、Rerank、版本治理、引用质量。

跑法：python ch10_rag_advanced/main.py

LangChain 原语：
  · BM25Retriever（全文检索，负责"精确词命中"：工号、条款号、制度名）
  · InMemoryVectorStore.as_retriever()（向量检索，负责"同义表达"）
  · EnsembleRetriever（两路加权合并）
  · filter 谓词（按生效日期/部门/版本做元数据过滤）
"""

import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_classic.retrievers import EnsembleRetriever   # ★ 1.x 里搬到了 langchain-classic
from langchain_core.vectorstores import InMemoryVectorStore
from pydantic import BaseModel, Field

from common import ai_text, ai_tool, get_model, practice, section, star, title
from common.embed import LocalHashEmbedding

# 三份制度，同一主题的两个版本（2023 旧版 / 2026 新版）+ 一条个人数据
DOCS = [
    Document(page_content="年假未休完的部分，当年清零，不折现，不可结转。",
             metadata={"title": "年假结转规则", "as_of": "2023-01-01", "dept": "all"}),
    Document(page_content="年假未休完可结转至次年 3 月 31 日，逾期作废；因公司安排无法休假的，经 HRD 审批可折现。",
             metadata={"title": "年假结转规则", "as_of": "2026-01-01", "dept": "all"}),
    Document(page_content="员工 E1001 张伟，2026 年年假余额 7.0 天（含上年结转 3 天）。",
             metadata={"title": "E1001 年假余额", "as_of": "2026-10-31", "dept": "技术中心"}),
    Document(page_content="年假单次超过 5 天需 HRBP 复核，超过 10 天需 HRD 审批；最小请假单位 0.5 天。",
             metadata={"title": "请假审批链", "as_of": "2026-01-01", "dept": "all"}),
    Document(page_content="技术中心员工可在季度末集中调休，需提前 3 个工作日在 OA 提交班次调整。",
             metadata={"title": "技术中心调休补充规定", "as_of": "2025-06-01", "dept": "技术中心"}),
]

title("案例 1：同一句查询，两路检索各有所长")

vec = InMemoryVectorStore(LocalHashEmbedding())
vec.add_documents(DOCS)
vec_r = vec.as_retriever(search_kwargs={"k": 3})
bm25_r = BM25Retriever.from_documents(DOCS, k=3)

q = "E1001 的年假还剩几天"
print(f"  问：{q}")
print("  向量检索：", [d.metadata["title"] for d in vec_r.invoke(q)])
print("  BM25 检索：", [d.metadata["title"] for d in bm25_r.invoke(q)])
star("问'工号/条款号/专有名词'时 BM25 更准；问'口语同义'时向量更强。所以要混，不要二选一")

# ============================================================
# 2) 混合检索 + 版本过滤
# ============================================================
section("案例 2：混合检索 + as_of 版本过滤 —— 同一问题，两个时点两个答案")

def retrieval(as_of: str, dept: str = "技术中心"):
    """★ 元数据过滤和检索必须一起做。先过滤再算相似度，才不会被旧版本占掉名额。"""
    pred = lambda d: d.metadata["as_of"] <= as_of and d.metadata["dept"] in ("all", dept)  # noqa: E731
    bm = BM25Retriever.from_documents([d for d in DOCS if pred(d)], k=2)
    vr = vec.as_retriever(search_kwargs={"k": 2, "filter": pred})
    return EnsembleRetriever(retrievers=[bm, vr], weights=[0.5, 0.5])


def latest_per_title(hits, as_of: str):
    """★ 光过滤不够：旧版本 as_of 更早，一样能通过 as_of<=T 的条件。

    真正的版本口径是"每个标题只取 as_of 最新的那个"——这一步不做，旧制度永远混进来。
    """
    best: dict[str, Document] = {}
    for d in hits:
        if d.metadata["as_of"] > as_of:
            continue
        cur = best.get(d.metadata["title"])
        if cur is None or d.metadata["as_of"] > cur.metadata["as_of"]:
            best[d.metadata["title"]] = d
    return sorted(best.values(), key=lambda d: d.metadata["as_of"], reverse=True)


for as_of in ("2023-06-30", "2026-11-15"):
    hits = latest_per_title(retrieval(as_of).invoke("年假没休完能结转吗"), as_of)
    print(f"\n  查询时点 as_of={as_of}：")
    for d in hits[:2]:
        print(f"    ← [{d.metadata['as_of']}] {d.metadata['title']} | {d.page_content[:36]}…")

star("RAG 里最严重的错误不是'召回不准'，是'用 2023 年的制度回答 2026 年的问题'")

# ============================================================
# 3) Rerank：敢丢，才是重排
# ============================================================
section("案例 3：Rerank —— 召回 5 条，只留真相关的 2 条")

class Score(BaseModel):
    relevant: bool = Field(description="这条资料是否真能回答该问题")
    score: int = Field(ge=0, le=10, description="0=完全无关，10=直接答案")


RERANK_P = ChatPromptTemplate.from_messages([
    ("system", "判断资料能否回答用户问题。只判断相关性，不要答题。"),
    ("human", "问题：{q}\n资料：{doc}"),
])
reranker = RERANK_P | get_model([
    ai_tool("Score", {"relevant": False, "score": 2}, "r1"),
    ai_tool("Score", {"relevant": True, "score": 9}, "r2"),
    ai_tool("Score", {"relevant": False, "score": 4}, "r3"),
]).with_structured_output(Score)

THRESHOLD = 6
AS_OF = "2026-11-15"
cands = retrieval(AS_OF).invoke("年假能留到明年吗")[:3]
kept = []
for d in cands:
    s = reranker.invoke({"q": "年假能留到明年吗", "doc": d.page_content})
    flag = "✓ 进上下文" if s.score >= THRESHOLD else "✗ 丢弃"
    print(f"    {d.metadata['title']:<14} score={s.score} {flag}")
    if s.score >= THRESHOLD:
        kept.append(d)
print(f"  召回 {len(cands)} 条 → 重排后 {len(kept)} 条")
star("Rerank 的价值不是'排序'，是'敢丢'；没有低分下限的重排，只是给噪声排了个名次")

# ============================================================
# 4) 引用质量
# ============================================================
section("案例 4：引用校验 —— 答得对不对，先看引得到不到")

ANSWER_P = ChatPromptTemplate.from_messages([
    ("system", "只根据资料回答。每条结论后标 [来源: 标题]。资料里没有就说不知道。\n资料：\n{ctx}"),
    ("human", "{q}"),
])
ctx = "\n".join(f"[{d.metadata['title']}] {d.page_content}" for d in kept)
gen = ANSWER_P | get_model([ai_text("可以。年假未休完可结转至次年 3 月 31 日，逾期作废。 [来源: 年假结转规则]")]) | StrOutputParser()
ans = gen.invoke({"ctx": ctx, "q": "年假能留到明年吗"})
print(f"\n  答案：{ans}")

cited = [s.split("]")[0] for s in ans.split("[来源: ")[1:]]
available = {d.metadata["title"] for d in kept}
print(f"  解析到的引用：{cited} / 可核对的来源：{sorted(available)}")
ok = all(c in available for c in cited)
print(f"  引用校验：{'✓ 全部可对回原文' if ok else '✗ 有引用对不上 → 判本次回答失败，返回兜底话术'}")

for line in [
    "混合检索治「召不回」，Rerank 治「召回里混噪声」，元数据过滤治「版本串台」，引用校验治「没法追责」",
    "四件事都做，才算能上线的 RAG；只做前两件，是 demo",
]:
    print(f"    · {line}")

practice([
    "把 weights 从 [0.5,0.5] 改成 [0.7,0.3]，比较专有名词查询与口语查询的差别",
    "把 THRESHOLD 调到 8，观察'答不出来'的比例上升，是否反而更可信",
    "给 as_of 加一个'用户当前时间'来源，跑通'历史回溯'场景",
    "把 reranker 换成真 cross-encoder（bge-reranker），对比延迟与准确率",
])
