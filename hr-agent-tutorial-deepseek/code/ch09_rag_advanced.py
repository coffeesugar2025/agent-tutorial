"""第 09 章：混合检索、版本治理与引用质检（LangChain 版）。

08 章的 RAG 只有「向量 Top-K」，遇到三件事会翻车：换个说法就召不回、同义改写召不回、
归档版和讨论稿混进证据。本章用 LangChain 的
`BM25Retriever` + `InMemoryVectorStore.as_retriever()` + `EnsembleRetriever`（内部是 RRF）
做混合检索；元数据过滤在检索前完成；增量索引、引用质检、拒答与 15 条问题评测保留。
离线运行，不联网。
"""
from __future__ import annotations

import hashlib
import math
import re
import sys
from datetime import date
from pathlib import Path

from langchain_classic.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.vectorstores import InMemoryVectorStore

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.data import all_policy_documents
from common.lc import MockChatModel
from common.text import chunk_markdown

TODAY = date(2026, 11, 1)  # 写死“今天”，保证每次结果一致；生产里用 date.today()
DIM = 256

# 真实 embedding 从语料学出来；离线版用一张手写同义词表模拟“近义召回”，只在查询侧扩展。
SYNONYMS: dict[str, list[str]] = {
    "用不": ["未休", "结转"], "带到": ["结转", "顺延"], "下一": ["次年", "明年"],
    "居家": ["远程", "在家办公"], "在家": ["远程", "居家"], "同意": ["授权", "许可"],
    "酒店": ["住宿"], "考勤": ["打卡", "出勤"], "调休": ["加班", "补休"],
}
STOPWORDS = {"公司", "员工", "可以", "什么", "哪些", "怎么", "是否", "需要", "多久", "几天",
             "多少", "流程", "规定", "制度", "请问", "一下", "我们", "有关"}

_WORD = re.compile(r"[a-z0-9]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    """中文按相邻两字切 bigram，英文数字按单词切；同时提供给 BM25 的 preprocess_func。"""
    text = text.lower()
    chars = _CJK.findall(text)
    return _WORD.findall(text) + ["".join(p) for p in zip(chars, chars[1:])] + chars


class HashingEmbeddings(Embeddings):
    """256 维字符 n-gram 哈希向量。真实项目换 OpenAIEmbeddings / HuggingFaceEmbeddings。"""

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text, expand=False) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text, expand=True)

    def _embed(self, text: str, expand: bool) -> list[float]:
        tokens = tokenize(text)
        if expand:
            tokens += [piece for t in tokens for syn in SYNONYMS.get(t, []) for piece in tokenize(syn)]
        vector = [0.0] * self.dim
        for token in tokens:
            bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16) % self.dim
            vector[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def build_documents() -> list[Document]:
    """把制度切成 LangChain Document，元数据带到检索结果里，后续过滤与引用都靠它。"""
    documents: list[Document] = []
    for doc in all_policy_documents():
        for piece in chunk_markdown(doc["content"], max_chars=260):
            if not piece["heading"]:  # 文首的文档编号块没有正文价值，不进索引
                continue
            documents.append(Document(
                id=f'{doc["doc_id"]}#{piece["index"]}',
                page_content=f'{piece["heading"]}\n{piece["text"]}',
                metadata={
                    "doc_id": doc["doc_id"], "title": doc["title"], "version": doc["version"],
                    "status": doc["status"], "effective_from": doc["effective_from"],
                    "effective_to": doc["effective_to"], "heading": piece["heading"],
                },
            ))
    return documents


def in_force(metadata: dict, today: date = TODAY) -> bool:
    """状态 active、已到生效日、且没有过期，才允许作为办理依据。"""
    if metadata["status"] != "active" or date.fromisoformat(metadata["effective_from"]) > today:
        return False
    return not (metadata["effective_to"] and date.fromisoformat(metadata["effective_to"]) < today)


def dedupe(documents: list[Document]) -> list[Document]:
    """同一份制度的多个切片只保留排名最高的一个，Top3 才有文档多样性。"""
    seen: set[str] = set()
    unique: list[Document] = []
    for document in documents:
        doc_id = document.metadata["doc_id"]
        if doc_id not in seen:
            seen.add(doc_id)
            unique.append(document)
    return unique


class PolicyIndex:
    """两套索引：全量（用于演示版本冲突）和仅现行有效（主链路真正用的那套）。"""

    def __init__(self, documents: list[Document], embeddings: Embeddings | None = None):
        self.documents = list(documents)
        self.embeddings = embeddings or HashingEmbeddings()
        self.rebuild()

    def _bundle(self, documents: list[Document]) -> dict[str, object]:
        store = InMemoryVectorStore(embedding=self.embeddings)
        store.add_documents(documents)
        bm25 = BM25Retriever.from_documents(documents, preprocess_func=tokenize)
        bm25.k = 8
        vector = store.as_retriever(search_kwargs={"k": 8})
        # EnsembleRetriever 内部就是加权 RRF：只按名次融合，不需要对齐两路分数量纲。
        ensemble = EnsembleRetriever(retrievers=[bm25, vector], weights=[0.5, 0.5])
        return {"bm25": bm25, "vector": vector, "hybrid": ensemble}

    def rebuild(self) -> None:
        self.full = self._bundle(self.documents)
        self.active_documents = [doc for doc in self.documents if in_force(doc.metadata)]
        self.active = self._bundle(self.active_documents)

    def count(self, active_only: bool = True) -> int:
        return len(self.active_documents) if active_only else len(self.documents)

    def search(self, question: str, k: int = 3, mode: str = "hybrid", active_only: bool = True):
        bundle = self.active if active_only else self.full
        documents = bundle[mode].invoke(question)  # type: ignore[union-attr]
        return dedupe(list(documents))[:k]

    def upsert(self, documents: list[Document]) -> int:
        ids = {doc.id for doc in documents}
        self.documents = [doc for doc in self.documents if doc.id not in ids] + list(documents)
        self.rebuild()
        return len(documents)

    def delete_doc(self, doc_id: str) -> int:
        before = len(self.documents)
        self.documents = [doc for doc in self.documents if doc.metadata["doc_id"] != doc_id]
        self.rebuild()
        return before - len(self.documents)


QUESTIONS = [
    ("5 年以上年假有几天", "leave-2025"), ("年假用不完能不能带到下一年", "leave-2025"),
    ("病假要提前多久跟主管说", "leave-2025"), ("每周最多远程办公几天", "remote-2025"),
    ("试用期员工可以申请居家办公吗", "remote-2025"), ("面试官多久内要提交面试反馈", "recruitment-2025"),
    ("背景调查必须拿到候选人同意吗", "recruitment-2025"), ("北京上海出差住宿每晚最多报多少", "expense-2025"),
    ("报销要在费用发生后几天内提交", "expense-2025"), ("绩效 S 的比例是多少", "performance-2025"),
    ("一年有几次调薪窗口，分别在几月", "performance-2025"), ("入职第一天要办哪些手续", "onboarding-2025"),
    ("试用期离职要提前几天", "handbook-2025"), ("入职要交哪些材料", "onboarding-2025"),
    ("L3 敏感数据访问要走什么流程", "privacy-2025"),
]

PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是 HR 共享服务中心助手。只依据证据回答，用 [n] 标注引用；没有证据就拒答。"),
    ("human", "问题：{question}\n证据：\n{evidence}"),
])


def core_terms(text: str) -> set[str]:
    tokens = tokenize(text)
    tokens += [piece for token in tokens for syn in SYNONYMS.get(token, []) for piece in tokenize(syn)]
    return {token for token in tokens if len(token) == 2 and token not in STOPWORDS}


def mock_reply(messages: list, tools=None) -> dict:
    """模拟“只依据证据说话”：从 Prompt 证据块里挑与问题重合最多的一行，并带引用号。"""
    prompt = messages[-1].content
    question = prompt.split("证据：")[0].replace("问题：", "").strip()
    query = set(tokenize(question))
    blocks = [block for block in prompt.split("\n[") if block.strip()]
    candidates: list[tuple[int, str, str, str]] = []
    for block in blocks:
        number = "[" + block.split("]", 1)[0] + "]"
        title = (re.search(r"《(.+?)》", block) or [None, "制度"])[1]
        for line in block.splitlines()[1:]:
            line = line.strip(" |：")
            if line and not line.startswith("#"):
                candidates.append((len(query & set(tokenize(line))), line, number, title))
    if not candidates:
        return {"content": "现行制度中没有找到依据，我不能回答。"}
    _, line, number, title = max(candidates)
    return {"content": f"根据《{title}》{line}（依据 {number}）"}


def answer_question(index: PolicyIndex, question: str) -> dict:
    core = core_terms(question)
    hits = [doc for doc in index.search(question, 3) if core & set(tokenize(doc.page_content))]
    if not hits:
        return {"answer": "现行制度中没有找到依据，请转 HR 人工确认。", "hits": [], "valid": False}
    evidence = "\n".join(
        f"[{n}] 《{doc.metadata['title']}》{doc.metadata['heading']}：{doc.page_content}"
        for n, doc in enumerate(hits, 1)
    )
    chain = PROMPT | MockChatModel(script=mock_reply) | StrOutputParser()
    answer = chain.invoke({"question": question, "evidence": evidence})
    citations = [int(n) for n in re.findall(r"\[(\d+)\]", answer)]
    valid = bool(citations) and all(1 <= n <= len(hits) for n in citations)
    return {"answer": answer, "hits": hits, "citations": citations, "valid": valid}


def main() -> None:
    def section(title: str) -> None:
        print(f"\n=== {title} ===")

    section("1. 建索引：全量文档 vs 当前有效文档")
    documents = build_documents()
    index = PolicyIndex(documents)
    print(f"文档 {len(all_policy_documents())} 份，切片 {index.count(False)} 个，可作为依据 {index.count()} 个")
    print("归档/草稿：" + "、".join(
        doc["doc_id"] for doc in all_policy_documents() if doc["status"] != "active"))

    section("2. 版本冲突：2024 归档版与 2025 版都在库里")
    raw = index.search("年假有几天", 4, active_only=False)
    print("不过滤 Top4：" + "、".join(doc.metadata["doc_id"] for doc in raw))
    filtered = index.search("年假有几天", 3)
    print("过滤后 Top3：" + "、".join(doc.metadata["doc_id"] for doc in filtered))
    for doc_id in ("leave-2024", "leave-2025"):
        doc = next(item for item in all_policy_documents() if item["doc_id"] == doc_id)
        rows = [line.strip(" |") for line in doc["content"].splitlines() if line.strip().startswith("| 满")]
        print(f"  {doc_id}：" + "；".join(rows))

    section("3. 讨论稿不能召回：2027 版只是草稿，生效日期在未来")
    draft_query = "每周远程天数拟调整为几天"
    print("不过滤 Top4：" + "、".join(
        doc.metadata["doc_id"] for doc in index.search(draft_query, 4, active_only=False)))
    print("过滤后 Top3：" + "、".join(
        f"{doc.metadata['doc_id']}({doc.metadata['heading']})" for doc in index.search(draft_query)))

    section("4. 15 条问题：只向量 / 只 BM25 / 混合 的 Recall@3")
    modes = ["vector", "bm25", "hybrid"]
    hits = {mode: [any(doc.metadata["doc_id"] == gold for doc in index.search(q, 3, mode))
                   for q, gold in QUESTIONS] for mode in modes}
    print(f"{'#':<3}{'问题':<28}{'只向量':<9}{'只BM25':<9}混合")
    for number, (question, _) in enumerate(QUESTIONS, 1):
        cells = "".join(f"{'命中' if hits[mode][number - 1] else '漏召':<9}" for mode in modes)
        print(f"{number:<3}{question:<28}{cells}")
    recall = {mode: sum(hit) / len(hit) for mode, hit in hits.items()}
    print("Recall@3：" + "，".join(f"{mode} {recall[mode]:.0%}" for mode in modes))

    section("5. 回答 + 引用质检：「5 年以上年假几天」")
    result = answer_question(index, "5 年以上年假几天")
    print("回答：" + result["answer"])
    for number, doc in enumerate(result["hits"], 1):
        meta = doc.metadata
        print(f"  [{number}] {meta['doc_id']} v{meta['version']} {meta['heading']}（{meta['status']}）")
    forged = "根据 [9] 应为 20 天"
    forged_ok = all(1 <= int(n) <= len(result["hits"]) for n in re.findall(r"\[(\d+)\]", forged))
    print(f"伪造引用 [9] 通过质检？{forged_ok}；合法引用通过？{result['valid']}")

    section("6. 证据不足就拒答，不编造")
    print("回答：" + answer_question(index, "公司会发股票期权吗")["answer"])

    section("7. 增量更新：upsert 一份新草稿，再 delete 掉")
    draft = Document(
        id="leave-2026-draft#0", page_content="2.1 年假天数\n拟将满 5 年的年假调整为 20 天。",
        metadata={"doc_id": "leave-2026-draft", "title": "年假制度（2026 讨论稿）", "version": "2026.0-draft",
                  "status": "draft", "effective_from": "2026-01-01", "effective_to": None,
                  "heading": "2.1 年假天数"},
    )
    print(f"upsert {index.upsert([draft])} 个切片，总切片 {index.count(False)}，可引用仍 {index.count()}")
    print(f"删除 {index.delete_doc('leave-2026-draft')} 个切片，总切片回到 {index.count(False)}")

    assert "15 天" in result["answer"], "当前有效制度里 5 年以上年假应为 15 天"
    assert all(doc.metadata["doc_id"] != "leave-2024" for doc in filtered)
    assert recall["hybrid"] >= max(recall["vector"], recall["bm25"]), "混合检索不应低于任一路单检索"
    assert forged_ok is False and result["valid"], "引用质检要拒绝越界引用、接受合法引用"
    print("\n全部断言通过：LangChain retriever 混合检索、版本过滤、引用质检、拒答四件事都成立。")


if __name__ == "__main__":
    main()
