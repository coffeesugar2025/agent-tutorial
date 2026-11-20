"""第 08 章：RAG 基础 —— 用 LangChain 走通「切片 → 向量 → 检索 → 引用」。

`RecursiveCharacterTextSplitter` 按标题切块并保留 heading 元数据；自定义 `HashingEmbeddings`
配合 `InMemoryVectorStore` 做 Top-K；`ChatPromptTemplate | MockChatModel` 生成带引用回答；
最后用 10 条问题算 Recall@3，并保留 2024/2025 两版同时被召回的版本冲突。
"""

from __future__ import annotations

import hashlib
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

from common.data import all_policy_documents, policy_manifest
from common.lc import MockChatModel
from common.text import mask_pii

CITE = re.compile(r"【([a-z0-9-]+) §([^】]+)】")
QUESTIONS: list[tuple[str, str, str]] = [
    ("年假没休完能转到明年吗？", "leave-2025", "结转"), ("病假需要提供什么材料？", "leave-2025", "病假"),
    ("入职第一天要完成哪些事？", "onboarding-2025", "入职"), ("出差住宿标准是多少？", "expense-2025", "住宿"),
    ("绩效评级为 C 会有什么影响？", "performance-2025", "PIP"), ("候选人面试记录保留多久？", "privacy-2025", "保留"),
    ("远程办公讨论稿打算把每周远程天数改成几天？", "remote-2027-draft", "3 天"),
    ("试用期可以远程办公吗？", "leave-2025", "试用期"), ("招聘面试一般有几轮？", "recruitment-2025", "面试"),
    ("加班调休怎么规定的？", "handbook-2025", "加班"),
]


class HashingEmbeddings(Embeddings):
    """256 维哈希向量：中文 2 字滑窗 + 英文词，hashlib 决定落点，零训练、可解释。"""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    @staticmethod
    def tokens(text: str) -> list[str]:
        text = text.lower()
        words = re.findall(r"[a-z0-9]+", text)
        grams = [run[i : i + 2] for run in re.findall(r"[\u4e00-\u9fff]+", text) for i in range(len(run) - 1)]
        return words + grams

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in self.tokens(text):
            bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16) % self.dim
            vector[bucket] += 1  # 词频累加；先保证信号不被碰撞抵消
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def markdown_sections(text: str) -> list[tuple[str, str]]:
    """按 ## / ### 标题切段，preamble 丢弃；heading 作为元数据保留。"""
    heading, buffer, sections = "", [], []
    for line in text.splitlines():
        if line.startswith("#"):
            if heading and any(item.strip() for item in buffer):
                sections.append((heading, "\n".join(buffer).strip()))
            heading = line.lstrip("# ").strip() if not line.startswith("# ") else ""
            buffer = []
        else:
            buffer.append(line)
    if heading and any(item.strip() for item in buffer):
        sections.append((heading, "\n".join(buffer).strip()))
    return sections


SPLITTER = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=60,
                                          separators=["\n\n", "\n", "。", "；", "，", " "])


def build_documents() -> list[Document]:
    documents: list[Document] = []
    for doc in all_policy_documents():
        for heading, body in markdown_sections(doc["content"]):
            for piece in SPLITTER.split_text(body):
                documents.append(Document(page_content=f"## {heading}\n{piece}", metadata={
                    "doc_id": doc["doc_id"], "title": doc["title"], "version": doc["version"],
                    "status": doc["status"], "heading": heading}))
    return documents


STORE = InMemoryVectorStore(embedding=HashingEmbeddings(256))


def format_context(hits: list[tuple[Document, float]]) -> str:
    return "\n\n".join(
        f"【片段{index}】{doc.metadata['doc_id']}《{doc.metadata['title']}》v{doc.metadata['version']}"
        f"（状态：{doc.metadata['status']}）｜{doc.metadata['heading']}\n{doc.page_content.split(chr(10), 1)[-1]}"
        for index, (doc, _) in enumerate(hits, 1))


PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是 HR 共享服务中心的助手。只能依据给定片段回答；"
               "每个结论后用【doc_id §条款标题】标注出处；片段里没有答案就拒答。"),
    ("human", "片段：\n{context}\n\n问题：{question}"),
])


def mock_answer(messages: list, tools: list | None = None) -> dict:
    """确定性假模型：从片段 1 里挑与问题最相关的一句，并原样带上出处。"""
    prompt = str(messages[-1].content)
    question = prompt.rsplit("问题：", 1)[-1].strip()
    first = re.search(r"【片段1】([^\n]+)\n(.+?)(?=\n\n【片段|\Z)", prompt, re.S)
    if not first:
        return {"content": "片段中没有找到依据，无法回答。"}
    header, body = first.group(1), first.group(2).strip()
    doc_id, heading = header.split("《")[0].strip(), header.split("｜", 1)[-1].strip()
    query_grams = set(HashingEmbeddings.tokens(question))
    sentences = [s.strip("- *") for s in re.split(r"[。；\n]", body) if s.strip()]
    best = max(sentences, key=lambda s: len(query_grams & set(HashingEmbeddings.tokens(s))))
    return {"content": f"根据《{header.split('《')[1].split('》')[0]}》：{mask_pii(best)}。【{doc_id} §{heading}】"}


CHAIN = PROMPT | MockChatModel(script=mock_answer)


def validate_citation(answer: str, hits: list[tuple[Document, float]]) -> tuple[bool, list[str]]:
    allowed = {(doc.metadata["doc_id"], doc.metadata["heading"]) for doc, _ in hits}
    cited = CITE.findall(answer)
    problems = [f"{doc} §{heading} 不在召回结果中" for doc, heading in cited if (doc, heading) not in allowed]
    if not cited:
        problems.append("回答没有给出任何引用")
    return (not problems and bool(cited)), problems


def main() -> None:
    print("=== 1. 读清单：LangChain Document + RecursiveCharacterTextSplitter ===")
    documents = build_documents()
    STORE.add_documents(documents)
    print(f"清单 {len(policy_manifest())} 份文档，切成 {len(documents)} 块，"
          f"平均 {sum(len(doc.page_content) for doc in documents) // len(documents)} 字/块")
    print("状态分布：", {s: sum(1 for d in documents if d.metadata["status"] == s) for s in
                       sorted({d.metadata["status"] for d in documents})})

    print("\n=== 2. 切片示例：heading 进入元数据，也进入向量 ===")
    for doc in [d for d in documents if d.metadata["doc_id"] == "leave-2025"][:2]:
        print(f"[{doc.metadata['doc_id']} §{doc.metadata['heading']}] {doc.page_content.splitlines()[1][:52]}…")

    print("\n=== 3. 检索：2024 和 2025 两版会一起回来 ===")
    question = "年假没休完能转到明年吗？"
    hits = STORE.similarity_search_with_score(question, k=3)
    for rank, (doc, score) in enumerate(hits, 1):
        print(f"  Top{rank} {score:.3f}  {doc.metadata['doc_id']} §{doc.metadata['heading']:<18}"
              f" v{doc.metadata['version']} {doc.metadata['status']}")

    print("\n=== 4. ChatPromptTemplate 拼片段 + MockChatModel 生成引用回答 ===")
    context = format_context(hits)
    answer = CHAIN.invoke({"context": context, "question": question}).content
    print("Prompt 片段数：", len(hits), "｜回答：", answer)
    ok, problems = validate_citation(answer, hits)
    print("引用校验：", "通过" if ok else problems)
    forged = "根据制度：年假可以无限结转。【leave-2024 §9.9 不存在的条款】"
    print("伪造引用校验：", validate_citation(forged, hits)[1])

    print("\n=== 5. 10 条问题算 Recall@3（文档级命中）===")
    hit_count, evidence_count = 0, 0
    for text, expected, keyword in QUESTIONS:
        top = STORE.similarity_search(text, k=3)
        docs = [doc.metadata["doc_id"] for doc in top]
        hit = expected in docs
        hit_count += hit
        evidence_count += any(keyword in doc.page_content and doc.metadata["doc_id"] == expected for doc in top)
        print(f"  {'✓' if hit else '✗'} {text:<22} 期望 {expected:<17} Top3 {docs}")
    recall = hit_count / len(QUESTIONS)
    print(f"Recall@3 = {hit_count}/{len(QUESTIONS)} = {recall:.0%}；"
          f"其中「正确文档里真有对应证据」{evidence_count}/{len(QUESTIONS)}")

    print("\n=== 6. 版本冲突：2024 和 2025 一起被召回，本章先不过滤 ===")
    for rank, (doc, score) in enumerate(STORE.similarity_search_with_score("病假需要提供什么材料？", k=2), 1):
        print(f"  Top{rank} {score:.3f} {doc.metadata['doc_id']}（{doc.metadata['status']}）"
              f"v{doc.metadata['version']}：{doc.page_content.splitlines()[1][:34]}…")
    relevant = [doc for doc, _ in hits if doc.metadata["doc_id"] == "leave-2025" and "5 天" in doc.page_content]
    print("「年假没休完」Top3 里，2025 版『结转 5 天』片段存在：", bool(relevant))

    assert abs(sum(a * b for a, b in zip(HashingEmbeddings(256).embed_query("年假"),
                                         HashingEmbeddings(256).embed_query("年假"))) - 1) < 1e-6
    assert relevant, "2025 版『结转 5 天』的片段必须能被召回"
    assert ok and not problems
    assert recall >= 0.8
    print(f"\n断言通过：同文本余弦为 1、2025 版证据在 Top3、引用可校验、Recall@3={recall:.0%}。")


if __name__ == "__main__":
    main()
