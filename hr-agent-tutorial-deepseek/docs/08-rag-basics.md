---
title: "08 | RAG 基础：从员工手册到可引用回答"
slug: "rag-basics"
order: 8
part: "RAG 与知识工程"
minutes: 65
difficulty: "进阶"
prerequisites: ["07"]
summary: "手写切片、哈希向量与余弦检索，跑通带引用校验的 RAG，并用 10 条问题算 Recall@3。"
---
> 🧩 **框架说明**：本章 demo 基于 **LangChain 1.x + LangGraph 1.x**，核心 API：`RecursiveCharacterTextSplitter`、`InMemoryVectorStore`、`Embeddings`。正文中的代码若标注“原理示意”（包括旧版 MockLLM / 手写循环片段），用于解释内部机制，不是最终运行代码；完整可运行代码见 `code/ch08_rag_basic.py`。


## 0. 本章你会得到什么

学完这一章，你应该能：

1. 走通 RAG 全链路：解析 → 切片 → 向量化 → 索引 → 召回 → 拼 Prompt → 生成 → 引用校验。
2. 手写一个 256 维哈希 Embedding 与余弦相似度，说清「向量检索」到底在算什么。
3. 让回答必须带文档编号与条款位置，并写代码校验引用是不是真的来自召回结果。
4. 用 10 条问题算 Recall@3，知道 RAG 也要评测，而且「召回对」不等于「答得对」。
5. 看见版本冲突：2024 版和 2025 版同时被召回时，系统会怎样给出错误口径。

## 1. 场景：同一句「年假没休完」，两个版本两个答案

11 月 18 日，产品部的李娜在员工自助入口问了一句：

> 年假没休完能转到明年吗？

公司制度库里有 10 份文档，其中两份都叫《年假与休假制度》：

- `leave-2024`（2024 版，状态 `archived`）：未休完的年假最多结转 **3 天**，到次年 **1 月 31 日** 作废。
- `leave-2025`（2025 版，状态 `active`）：未休完的年假最多结转 **5 天**，到次年 **3 月 31 日** 作废。

李娜今年有 8 天没休完。如果系统答「3 天」，她按 3 天安排，剩下 5 天会被作废；如果答「5 天」，她可以留到 3 月底。两种答案差的不是一句话，是 5 天假期和一次劳动仲裁的风险。

传统做法是 HR 手工查：打开文档库，搜「年假」，看到两份文件，确认哪份是现行版，再翻到 2.2 条。熟手要 3 分钟，新人要 15 分钟，而且会累、会看错版本。更糟的是，当员工在群里问「到底几天」，三个人可能给出三个答案。

RAG（Retrieval-Augmented Generation，检索增强生成）想解决的就是这件事：让系统先从文档库里找出**该看的那几段**，再让模型**基于这几段**回答，并且**标出出处**。它不是让模型背下整本手册，而是每次答题前先翻书。

但翻书也会翻错。本章故意不做过多的版本治理，就是为了让你看到基础 RAG 的真实样子：2024 和 2025 两版会一起被召回，甚至已归档的 2024 版排在第一。员工问病假材料，系统会答「三级甲等医院证明」——那是 2024 版的要求，2025 版已经改成「二级及以上」。这个悬念留到第 09 章解决。

本章要跑通的链路是：

```text
manifest.json ──▶ 读文档 ──▶ chunk_markdown 切片 ──▶ HashingEmbedder 向量化
                                                          │
员工问题 ──▶ 向量化 ──▶ 余弦相似度 ──▶ Top-K ──▶ 拼 Prompt（片段号/文档号/版本/状态）
                                                          │
                                                    MockLLM 生成
                                                          │
                                          带【doc_id §条款】的回答
                                                          │
                                    引用校验：doc_id 必须在召回结果里
                                                          │
                                        10 条问题 ──▶ Recall@3
```

## 2. 概念：RAG 是把「查资料」写进流程

**RAG** 的直白解释：模型本身不知道你公司的制度，所以每次回答前，先从你的文档库里检索相关片段，把片段和问题一起交给模型，让它「看着材料回答」。它由两部分组成：检索（Retrieval）和生成（Generation）。

为什么不让模型直接记住？三个原因：

- **知识会变**。制度一年一版，模型训练数据不会跟着更新。
- **幻觉**。模型不知道时会编，编得还很像真的。
- **可追溯**。HR 场景要求「你说的依据在哪」，检索片段就是证据。

### 2.1 切片：切多大才合适

文档不能整份塞进去。一份员工手册 2 万字，一次请求放不下，也没必要。所以要**切片（Chunking）**：把长文档切成一段一段，每段单独建索引。

切片粒度是个取舍：

- 切得太碎（比如 100 字）：每段信息不完整，「最多结转 5 天」和「至次年 3 月 31 日」可能被切到两段，检索到一半，答案就残了。
- 切得太大（比如 2000 字）：一段里混了好几个主题，向量被平均掉，检索精度下降，塞进 Prompt 也浪费 token。
- 中文制度类文档的经验值：**300~600 字**，按 Markdown 标题切，标题本身作为元数据保留。

本章用 `common.text.chunk_markdown`，先按 `##` 标题切成语义段，再按长度切。好处是「年假」「病假」「远程办公」天然分开，坏处是短章节会切出很多小段（本章 10 份文档切出 61 块，平均 102 字）。

```text
整份文档（约 2000 字）
├── ## 1. 目的            → 36 字，1 块
├── ## 2. 年假
│   ├── ### 2.1 天数      → 154 字，1 块
│   ├── ### 2.2 结转      → 140 字，1 块   ← 「结转 5 天」在这里
│   └── ### 2.3 申请      → 143 字，1 块
├── ## 3. 病假            → 151 字，1 块   ← 「二级及以上」在这里
└── ## 5. 远程办公        → 116 字，1 块
```

### 2.2 向量化：把文本变成一串数字

计算机不会直接比较两段中文的「意思」，但它会算数字。**Embedding（向量化）** 就是把一段文本映射成一个固定长度的数字数组，比如 256 个浮点数。语义相近的文本，向量方向接近；语义无关的，方向差得远。

真实项目用预训练模型（如 BGE、text-embedding-3）做嵌入，需要联网或本地推理。本章为了「离线、零依赖、可解释」，手写一个 **哈希 Embedding**：

1. 把文本切成 token：中文按 2 字滑窗（「病假」「假需」「需要」……），英文按单词。
2. 每个 token 用 `hashlib.md5` 算一个哈希，取前 8 位十六进制对 256 取模，得到一个 0~255 的下标。
3. 把该下标对应的维度加 1（词频累加）。
4. 最后做 L2 归一化，让向量长度为 1。

它没有「语义」，只有「哪些字一起出现」。所以它能匹配「年假 / 结转」这种字面重叠，但匹配不了「年休」和「年假」这种同义词。这是它的局限，也是本章要你亲手写一遍的原因：**你得先知道向量检索的本质上就是「词袋 + 哈希 + 余弦」**，再去用现成的向量库，才不会被「语义检索」四个字唬住。

### 2.3 余弦相似度：看两个向量的夹角

两个向量越同向，余弦值越接近 1；垂直是 0；反向是 -1。因为我们已经做了归一化，余弦就等于点积：

```text
cos(A, B) = A · B / (|A| × |B|) = A · B      （|A| = |B| = 1）
```

检索时，把问题也向量化，和库里每个块算余弦，取分数最高的 K 个，就是 **Top-K**。本章 K 默认 3。Top-K 之后通常还有一步**重排（Rerank）**，用更贵的模型把候选再排一次；本章先跳过，第 09 章会实现。

### 2.4 拼 Prompt、生成与引用

检索到片段后，Prompt 长这样：

```text
【片段1】leave-2025《年假与休假制度（2025 版）》v2025.1（状态：active）｜2. 年假
- 当年未休完的年假，最多可结转 **5 天** 至次年 **3 月 31 日**，逾期自动作废。
...
问题：年假没休完能转到明年吗？
```

系统提示里三条硬约束：只能依据片段回答、每个结论标出处、片段里没有就拒答。**引用（Citation）** 就是回答末尾的 `【leave-2025 §2. 年假】`，它让人能点回原文核对。

生成之后必须做**引用校验**：回答里引用的 `doc_id` 和条款标题，必须在这次召回结果里。否则模型可能编一个「看起来很像」的出处。校验很简单，但能拦住大部分引用幻觉。

### 2.5 评测：Recall@K

**Recall@K（召回率）** 的定义：在 K 个结果里，有没有包含正确答案所在的文档。本章用 10 条问题、K=3：

```text
Recall@3 = 命中问题数 / 总问题数
```

它只衡量「文档有没有被找出来」，不衡量「片段对不对」「答案对不对」。所以本章还会额外打印一个「正确文档里真有对应证据」的数量——你会看到 Recall@3 是 10/10，但证据命中只有 7/10。这个差距就是 RAG 的第二层问题：**文档对了，片段不一定对**。

## 3. 动手：跑通基础 RAG

> 🧩 **读法**：第 3 节的代码用于解释原理；本章实际运行的 demo 已改为 LangChain 版，完整代码见章末“LangChain 版关键实现”与 `code/` 对应脚本。


在仓库根目录执行：

```powershell
python code/ch08_rag_basic.py
```

完整代码（与 `code/ch08_rag_basic.py` 一致）：

```python
"""第 08 章：RAG 基础 —— 从员工手册到可引用回答。

全链路：读清单 → 切片 → 哈希向量化 → 余弦检索 → 拼 Prompt → MockLLM 带引用回答
→ 引用校验 → 10 条问题算 Recall@3。不联网、不用向量库，256 维 + 纯 Python 余弦。
"""

from __future__ import annotations

import hashlib
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.data import all_policy_documents, policy_manifest
from common.llm import MockLLM, system, user
from common.text import chunk_markdown, estimate_tokens, mask_pii

CITE = re.compile(r"【([a-z0-9-]+) §([^】]+)】")
QUESTIONS: list[tuple[str, str, str]] = [
    ("年假没休完能转到明年吗？", "leave-2025", "结转"), ("病假需要提供什么材料？", "leave-2025", "病假"),
    ("入职第一天要完成哪些事？", "onboarding-2025", "入职"), ("出差住宿标准是多少？", "expense-2025", "住宿"),
    ("绩效评级为 C 会有什么影响？", "performance-2025", "PIP"), ("候选人面试记录保留多久？", "privacy-2025", "保留"),
    ("远程办公讨论稿打算把每周远程天数改成几天？", "remote-2027-draft", "3 天"),
    ("试用期可以远程办公吗？", "leave-2025", "试用期"), ("招聘面试一般有几轮？", "recruitment-2025", "面试"),
    ("加班调休怎么规定的？", "handbook-2025", "加班"),
]

@dataclass
class Chunk:
    doc_id: str
    title: str
    version: str
    status: str
    heading: str
    text: str

    @property
    def label(self) -> str:
        return f"{self.doc_id} §{self.heading}"

class HashingEmbedder:
    """把文本映射成 256 维：字符 bigram + 英文单词，hashlib 决定落点。

    没有训练、没有语义，只看「哪些字一起出现」；零依赖、确定性、可解释。
    不同词撞到同一维度是常态，所以 chunk 不能太碎。
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    @staticmethod
    def tokens(text: str) -> list[str]:
        text = text.lower()
        words = re.findall(r"[a-z0-9]+", text)
        grams = [
            run[i : i + 2]
            for run in re.findall(r"[\u4e00-\u9fff]+", text)
            for i in range(len(run) - 1)
        ]
        return words + grams

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        counts: dict[str, int] = {}
        for token in self.tokens(text):
            counts[token] = counts.get(token, 0) + 1
        for token, count in counts.items():
            bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16) % self.dim
            vector[bucket] += count  # 词频直接累加：朴素，但对短文本够用
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))  # 已归一化，点积即余弦
class VectorStore:
    def __init__(self, embedder: HashingEmbedder) -> None:
        self.embedder = embedder
        self.chunks: list[Chunk] = []
        self.vectors: list[list[float]] = []

    def add(self, chunks: list[Chunk]) -> None:
        self.chunks.extend(chunks)
        # 标题也进向量：条款标题里的「结转」「住宿标准」本身就是强信号
        self.vectors.extend(self.embedder.embed(f"{chunk.heading}\n{chunk.text}") for chunk in chunks)

    def search(self, query: str, k: int = 3) -> list[tuple[Chunk, float]]:
        query_vector = self.embedder.embed(query)
        scored = [(chunk, cosine(query_vector, vector)) for chunk, vector in zip(self.chunks, self.vectors)]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:k]

def build_chunks(max_chars: int = 400) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in all_policy_documents():
        for piece in chunk_markdown(doc["content"], max_chars=max_chars):
            if not piece["heading"]:  # 文首的文档编号块没有正文价值，不进索引
                continue
            chunks.append(
                Chunk(
                    doc_id=doc["doc_id"],
                    title=doc["title"],
                    version=doc["version"],
                    status=doc["status"],
                    heading=piece["heading"],
                    text=piece["text"],
                )
            )
    return chunks

def build_prompt(question: str, hits: list[tuple[Chunk, float]]) -> list[dict]:
    blocks = "\n\n".join(
        f"【片段{index}】{chunk.doc_id}《{chunk.title}》v{chunk.version}（状态：{chunk.status}）｜{chunk.heading}\n{chunk.text}"
        for index, (chunk, _) in enumerate(hits, 1)
    )
    return [
        system(
            "你是 HR 共享服务中心的助手。只能依据给定片段回答；"
            "每个结论后用【doc_id §条款标题】标注出处；片段里没有答案就拒答。"
        ),
        user(f"片段：\n{blocks}\n\n问题：{question}"),
    ]

def mock_answer(messages: list[dict], tools: list[dict] | None = None) -> dict:
    prompt = messages[-1]["content"]
    question = prompt.rsplit("问题：", 1)[-1].strip()
    first = re.search(r"【片段1】([^\n]+)\n(.+?)(?=\n\n【片段|\Z)", prompt, re.S)
    if not first:
        return {"content": "片段中没有找到依据，无法回答。"}
    header, body = first.group(1), first.group(2).strip()
    doc_id = header.split("《")[0].strip()
    heading = header.split("｜", 1)[-1].strip()
    query_grams = set(HashingEmbedder.tokens(question))
    sentences = [s.strip() for s in re.split(r"[。；\n]", body) if s.strip()]
    best = max(sentences, key=lambda s: len(query_grams & set(HashingEmbedder.tokens(s)))).strip("- *")
    return {"content": f"根据《{header.split('《')[1].split('》')[0]}》：{mask_pii(best)}。【{doc_id} §{heading}】"}

def validate_citation(answer: str, hits: list[tuple[Chunk, float]]) -> tuple[bool, list[str]]:
    allowed = {(chunk.doc_id, chunk.heading) for chunk, _ in hits}
    cited = CITE.findall(answer)
    problems = [f"{doc} §{heading} 不在召回结果中" for doc, heading in cited if (doc, heading) not in allowed]
    if not cited:
        problems.append("回答没有给出任何引用")
    return (not problems and bool(cited)), problems
def main() -> None:
    print("=== 1. 读清单：一共有多少份制度、多少块 ===")
    manifest = policy_manifest()
    chunks = build_chunks(max_chars=400)
    print(f"清单 {len(manifest)} 份文档，切成 {len(chunks)} 块，平均 {sum(len(c.text) for c in chunks) // len(chunks)} 字/块")
    print("状态分布：", {status: sum(1 for c in chunks if c.status == status) for status in sorted({c.status for c in chunks})})

    print("\n=== 2. 切片示例：标题就是天然的语义边界 ===")
    for chunk in [c for c in chunks if c.doc_id == "leave-2025"][:2]:
        print(f"[{chunk.label}] {chunk.text[:60].replace(chr(10), ' ')}…")
    print("\n=== 3. 手写向量：相近的文本，余弦更大 ===")
    embedder = HashingEmbedder(256)
    pairs = [
        ("年假没休完怎么办", "当年未休完的年假，最多可结转 5 天"),
        ("年假没休完怎么办", "差旅住宿标准按城市分级"),
    ]
    for left, right in pairs:
        print(f"  cos({left!r}, {right[:16]!r}…) = {cosine(embedder.embed(left), embedder.embed(right)):.3f}")

    print("\n=== 4. 建索引并检索：2024 和 2025 两版会一起回来 ===")
    store = VectorStore(embedder)
    store.add(chunks)
    question = "年假没休完能转到明年吗？"
    hits = store.search(question, k=3)
    for rank, (chunk, score) in enumerate(hits, 1):
        print(f"  Top{rank} {score:.3f}  {chunk.label:<28} v{chunk.version} {chunk.status}")

    print("\n=== 5. 拼 Prompt：把片段编号、版本、状态都写进去 ===")
    messages = build_prompt(question, hits)
    print(f"Prompt 估算 {estimate_tokens(messages[-1]['content'])} token，片段 {len(hits)} 个")

    print("\n=== 6. MockLLM 生成回答 + 引用校验 ===")
    llm = MockLLM(mock_answer)
    answer = llm.chat(messages).content or ""
    print("回答：", answer)
    ok, problems = validate_citation(answer, hits)
    print("引用校验：", "通过" if ok else problems)
    forged = "根据制度：年假可以无限结转。【leave-2024 §9.9 不存在的条款】"
    print("伪造引用校验：", validate_citation(forged, hits)[1])

    print("\n=== 7. 10 条问题算 Recall@3（文档级命中）===")
    hit_count, evidence_count, failures = 0, 0, []
    for text, expected, keyword in QUESTIONS:
        top = store.search(text, k=3)
        docs = [chunk.doc_id for chunk, _ in top]
        hit = expected in docs
        evidence = any(keyword in chunk.text and chunk.doc_id == expected for chunk, _ in top)
        hit_count += hit
        evidence_count += evidence
        if not hit:
            failures.append((text, expected, docs))
        flag = "✓" if hit else "✗"
        print(f"  {flag} {text:<22} 期望 {expected:<17} Top3 {docs}")
    recall = hit_count / len(QUESTIONS)
    print(f"Recall@3 = {hit_count}/{len(QUESTIONS)} = {recall:.0%}；"
          f"其中「正确文档里真有对应证据」{evidence_count}/{len(QUESTIONS)}")

    print("\n=== 8. 版本冲突：2024 和 2025 一起被召回，甚至旧版排第一 ===")
    for rank, (chunk, score) in enumerate(store.search("病假需要提供什么材料？", k=2), 1):
        print(f"  Top{rank} {score:.3f} {chunk.doc_id}（{chunk.status}）v{chunk.version}：{chunk.text[:34].replace(chr(10), ' ')}…")
    relevant = [chunk for chunk, _ in hits if chunk.doc_id == "leave-2025" and "5 天" in chunk.text]
    print("「年假没休完」的 Top3 里，2025 版『结转 5 天』片段存在：", bool(relevant))
    for text, expected, docs in failures:
        print(f"  失败案例：{text} 期望 {expected}，实际 {docs}")

    assert cosine(embedder.embed("年假"), embedder.embed("年假")) > 0.999
    assert relevant, "2025 版『结转 5 天』的片段必须能被召回"
    assert ok and not problems
    assert recall >= 0.8
    print(f"\n断言通过：同文本余弦为 1、2025 版证据在 Top3、引用可校验、Recall@3={recall:.0%}。")

if __name__ == "__main__":
    main()
```

运行结果（节选）：

```text
=== 1. 读清单：一共有多少份制度、多少块 ===
清单 10 份文档，切成 61 块，平均 102 字/块
状态分布： {'active': 52, 'archived': 7, 'draft': 2}

=== 4. 建索引并检索：2024 和 2025 两版会一起回来 ===
  Top1 0.278  leave-2025 §2. 年假            v2025.1 active
  Top2 0.224  leave-2025 §1. 目的            v2025.1 active
  Top3 0.186  leave-2024 §2. 结转规则          v2024.1 archived

=== 6. MockLLM 生成回答 + 引用校验 ===
回答： 根据《年假与休假制度（2025 版）》：当年未休完的年假，最多可结转 **5 天** 至次年 **3 月 31 日**，逾期自动作废。【leave-2025 §2. 年假】
引用校验： 通过
伪造引用校验： ['leave-2024 §9.9 不存在的条款 不在召回结果中']

=== 7. 10 条问题算 Recall@3（文档级命中）===
  ✓ 年假没休完能转到明年吗？           期望 leave-2025        Top3 ['leave-2025', 'leave-2025', 'leave-2024']
  ✓ 病假需要提供什么材料？            期望 leave-2025        Top3 ['leave-2024', 'leave-2025', 'leave-2025']
  ✓ 入职第一天要完成哪些事？           期望 onboarding-2025   Top3 ['onboarding-2025', 'recruitment-2025', 'performance-2025']
  ✓ 出差住宿标准是多少？             期望 expense-2025      Top3 ['expense-2025', 'expense-2025', 'handbook-2025']
  ✓ 绩效评级为 C 会有什么影响？        期望 performance-2025  Top3 ['performance-2025', 'performance-2025', 'remote-2025']
  ✓ 候选人面试记录保留多久？           期望 privacy-2025      Top3 ['onboarding-2025', 'recruitment-2025', 'privacy-2025']
  ✓ 远程办公讨论稿打算把每周远程天数改成几天？  期望 remote-2027-draft Top3 ['leave-2025', 'remote-2027-draft', 'leave-2024']
  ✓ 试用期可以远程办公吗？            期望 leave-2025        Top3 ['leave-2025', 'leave-2024', 'remote-2027-draft']
  ✓ 招聘面试一般有几轮？             期望 recruitment-2025  Top3 ['recruitment-2025', 'recruitment-2025', 'recruitment-2025']
  ✓ 加班调休怎么规定的？             期望 handbook-2025     Top3 ['handbook-2025', 'leave-2024', 'onboarding-2025']
Recall@3 = 10/10 = 100%；其中「正确文档里真有对应证据」7/10

=== 8. 版本冲突：2024 和 2025 一起被召回，甚至旧版排第一 ===
  Top1 0.503 leave-2024（archived）v2024.1：病假需提供三级甲等医院证明，当天报备，返岗后 3 个工作日内补交材料…
  Top2 0.441 leave-2025（active）v2025.1：- 病假需提供二级及以上医院出具的病假证明；急诊可后补。 - 员工应…
「年假没休完」的 Top3 里，2025 版『结转 5 天』片段存在： True
```

三个值得停下来看的现象：

1. **Top3 里同时出现 2024 和 2025**。检索只看「字面像不像」，不看「是不是现行版本」。这是基础 RAG 最大的坑。
2. **病假问题里，已归档的 2024 版排第一**（0.503 对 0.441）。如果直接拿 Top1 生成回答，员工会拿到「三级甲等医院」这个过期要求。
3. **Recall@3 是 100%，但证据命中只有 70%**。问题「候选人面试记录保留多久」命中了 `privacy-2025`，但排第三，前两名是 `onboarding` 和 `recruitment` 的附则。文档对了，片段错了，回答照样可能错。

> 🧪 **动手**：把第 4 节的 `k=3` 改成 `k=1`，看「病假」问题会答哪一版；再改成 `k=5`，看 2027 讨论稿会不会混进来。这个练习没有标准答案，但能让你体会「K 越大越全，也越容易混入过期内容」。

## 4. 逐行拆解

### 4.1 为什么用 bigram 而不是分词

`HashingEmbedder.tokens` 只做两件事：

```python
words = re.findall(r"[a-z0-9]+", text)
grams = [run[i : i + 2] for run in re.findall(r"[\u4e00-\u9fff]+", text) for i in range(len(run) - 1)]
```

中文没有空格，分词需要词典或模型。教程不能引入 jieba 之类的依赖，所以退一步：用 2 字滑窗。「年假没休完」会变成「年假」「假没」「没休」「休完」——粒度粗，但零依赖、确定性、可解释。

代价是同义词匹配不上：「年休」和「年假」的 bigram 完全不同。真实项目会用预训练 embedding 或 BM25 补这块，第 09 章会讲混合检索。

### 4.2 为什么标题也要进向量

```python
self.vectors.extend(self.embedder.embed(f"{chunk.heading}\n{chunk.text}") for chunk in chunks)
```

正文里可能只写「最多可结转 5 天」，不出现「年假」两个字；标题「2. 年假」正好补上这个关键词。实测把标题拼进向量后，「年假没休完」的 Top1 分数从 0.263 提到 0.278，Top1 没变但领先更多。它属于「零成本、小幅但稳定」的优化，不要指望它单独解决召回质量问题——真正的噪声来自哈希碰撞，下一节会讲。

### 4.3 为什么用无符号词频，而不是带符号哈希

哈希把无限的词映射到 256 个桶，碰撞不可避免。带符号哈希（每个 token 随机 +1/-1）理论上能抵消碰撞偏差，但在 256 维、短查询、长文档的组合下，实测会出现「明明共享 4 个 bigram，余弦只有 0.03」的抵消现象。

本章选择朴素的词频累加：

```python
vector[bucket] += count
```

它的问题是任意两段中文都会有一点相似度（因为常用字碰撞），但排序仍然可靠。这是一个典型的工程取舍：**在维度受限时，先保证信号不被抵消，再谈偏差**。真实向量库维度是 768 或 1024，碰撞少得多，带符号哈希才划算。

### 4.4 引用校验只做了一件事，但很关键

```python
allowed = {(chunk.doc_id, chunk.heading) for chunk, _ in hits}
cited = CITE.findall(answer)
problems = [f"{doc} §{heading} 不在召回结果中" for doc, heading in cited if (doc, heading) not in allowed]
```

它校验的是「引用是否来自这次召回」，不是「引用是否支持结论」。前者能拦住「编造出处」，后者需要人工或 LLM 判断。本章先做前者，因为它便宜、确定、能自动化；后者放到第 15 章的引用准确率评测里。

伪造引用的输出是 `['leave-2024 §9.9 不存在的条款 不在召回结果中']`——注意，`leave-2024` 本身在库里，但 `§9.9` 不在召回结果里，所以照样被拦。这说明校验要精确到「文档 + 条款」，不能只校验文档编号。

### 4.5 Recall@3 的口径要说清楚

代码里：

```python
hit = expected in docs
```

只判断「期望文档是否出现在 Top3 的文档列表里」，不判断片段。这是业界最常见的文档级 Recall 口径。它的好处是简单、可自动算；坏处是会把「文档对了但片段错了」算成成功。

所以本章额外算了证据命中：

```python
evidence = any(keyword in chunk.text and chunk.doc_id == expected for chunk, _ in top)
```

两个数字一起看，才知道系统到底行不行。第 15 章会把口径细化为「文档命中率、片段命中率、引用准确率、答案正确率」四个指标。

### 4.6 版本冲突为什么是「设计问题」而不是「bug」

2024 和 2025 都被召回，不是代码写错了，而是索引里本来就该有历史版本（审计、追溯都要用）。错的是**检索时没有按状态和生效日期过滤**。基础 RAG 只做「相似度排序」，不做「业务规则过滤」，所以它会忠实地把最像的片段端上来，哪怕那个片段已经作废。

这也是本章故意留的悬念：修法不是把 2024 从库里删掉（审计需要它），而是在检索阶段加元数据过滤，在生成阶段要求「只引用 active 版本」，在评测阶段把「是否引用过期版本」作为一个独立指标。第 09 章会逐一实现。

> ⚠️ **生产提醒**：制度类 RAG 必须把 `status`、`effective_from`、`effective_to`、`sensitivity` 作为一等公民。只按相似度检索，迟早会把归档版、讨论稿、甚至别的部门的内部制度答给员工。候选人和员工信息属于 L2，拼 Prompt 前要按角色过滤字段并做脱敏。

## 5. 实验：改切片、改过滤、改 K

### 实验一：chunk_size 从 400 改到 800

把 `build_chunks(max_chars=400)` 改成 `max_chars=800`。预期现象：块数**仍然是 61**，结果完全不变。因为这份语料每个小节都短于 400 字，`max_chars` 根本没机会触发二次切分。这本身是个重要发现：**真正决定切片的是文档的标题结构，不是 `max_chars`**。

把 `max_chars` 改成 150，块数会从 61 涨到 72，Top3 里开始混进 `privacy-2025` 的表格段，噪声变多；再小就会把「5 天」和「3 月 31 日」切到两块里。想验证「切片大小影响召回」，得先把同级小节合并成更长的段落，或者用人造长文做实验。

### 实验二：只索引 active 文档

在 `build_chunks` 里加一行过滤：

```python
if doc["status"] != "active":
    continue
```

重跑。预期现象：块数从 61 降到 52，「病假」问题的 Top1 变成 2025 版，答案正确。但这只是「眼不见为净」：历史版本被彻底排除，员工问「2024 年我休了几天」就查不到了。生产上更稳的是「索引全量 + 检索时按状态过滤」，而不是「索引时删掉」。

### 实验三：K 从 3 改到 1 和 5

把第 4 节和第 7 节的 `k=3` 改成 1，再改成 5。K=1 时，「病假」只给 2024 版（0.503），答案错；K=5 时，「年假」问题会多出两段 `privacy-2025` 噪声段，远程类问题则会把 2027 讨论稿一并带回候选。结论：**K 不是越大越好，Top-K 之后还需要过滤和重排**。

### 实验四：换一个问法

把「年假没休完能转到明年吗？」改成「年假可以结转到次年吗？」。预期现象：`结转` 直接命中 2024 版的条款标题，2024 版排第一（0.327），2025 版只差 0.004 排第二——版本冲突在换一种问法后反而更严重。再改成「年休没用完怎么办」，bigram 几乎不重叠，Top3 全变成噪声（加班调休、数据出境、调薪）。这暴露了哈希 Embedding 的同义词短板，也是第 09 章上 BM25 + 向量的动机。

## 6. 工程化视角

基础 RAG 到生产，中间隔着五道工程：

**向量库。** 本章用纯 Python 列表遍历（61 个块没问题），真实库有几万到几百万块，需要 Milvus、pgvector、Qdrant 之类的向量索引（HNSW、IVF）。接口还是 `add / search`，但要做批量、分片、持久化。

**增量索引。** 制度更新时不能全量重建。要按 `doc_id` 做 upsert / delete，并且保证「旧版本可查、新版本生效」的切换是原子的。索引版本和文档版本要能对账，否则会出现「文档改了、索引没更新」的静默错误。

**元数据过滤。** 检索时先按 `status=active`、`effective_from <= today`、`sensitivity <= 用户级别` 过滤，再算相似度。过滤放在向量检索前叫 pre-filter，放在后叫 post-filter；前者快但可能漏，后者全但慢，要按数据量选。

**重排（Rerank）。** 向量召回是「粗排」，Top-20 里常有噪声。用 cross-encoder 或规则做精排，把真正相关的 3~5 条挑出来。本章的「证据命中 7/10」就是重排要解决的问题。

**评测与回归。** 10 条问题只是演示。生产要有 100~500 条 Golden Case，覆盖各文档、各版本、各类问法，每次改切片/改模型/改 Prompt 都跑一遍，看 Recall@K、引用准确率、拒答率有没有退化。

> ⚠️ **生产提醒**：评测集必须固定，不能每次换题。至少留三类 bad case 各 10 条做回归：引用了过期版本、引用了不存在的条款、证据不足却硬答。没有这三类样本，Recall@3 再高也说明不了上线安全。

## 7. 常见坑

**坑 1：把归档版和现行版一起索引、一起检索。**
现象：员工拿到过期口径，投诉「上次说的和这次不一样」。
原因：检索只看相似度，不看状态。
解法：元数据过滤 + 版本优先级 + 评测里单独统计「引用过期版本」的比例。

**坑 2：切片太碎。**
现象：检索到的片段只有半句话，「5 天」找到了，「3 月 31 日」丢了。
原因：按固定字符切，切断了条款。
解法：按标题/条款切，保留标题元数据；chunk 之间留少量重叠。

**坑 3：只校验文档编号，不校验条款。**
现象：模型引用 `leave-2024 §9.9`，系统说「文档在召回里，通过」。
原因：校验粒度太粗。
解法：`(doc_id, heading)` 二元组校验；更严的还要校验原文片段是否包含引用句。

**坑 4：把 Recall@K 当成 RAG 的唯一指标。**
现象：Recall@3 100%，线上仍然被投诉答错。
原因：文档命中不等于片段命中，更不等于答案正确。
解法：分层指标：文档召回、片段命中、引用准确、答案正确、拒答正确。

**坑 5：用哈希 Embedding 上生产。**
现象：换个说法就搜不到，同义词全军覆没。
原因：哈希只捕捉字面 bigram。
解法：本章的实现用于理解原理；生产用预训练 embedding，或 BM25 + 向量混合。

**坑 6：忽略 PII 与权限。**
现象：候选人面试记录被普通员工问到，手机号原样输出。
原因：索引里没有密级字段，Prompt 里没有脱敏。
解法：`sensitivity` 进元数据，检索前按最小权限鉴权，展示前 `mask_pii`，L2/L3 读取写审计。

## 8. 练习

### 练习 1（易）：数一数你的索引

打印每个文档的块数和平均块长，找出被切得最碎的文档。它为什么碎？是标题太多，还是段落太短？

<details><summary>参考答案</summary>

```python
from collections import Counter
counter = Counter(chunk.doc_id for chunk in chunks)
for doc_id, count in counter.most_common():
    print(doc_id, count)
```

通常「员工手册」这种多级标题的文档块最多。如果某份文档每块只有几十字，说明它的 `##` 标题太密，或者正文本身是短条目。可以考虑「同级标题合并到 300 字以上再切」，或者对短文档整份索引。

</details>

### 练习 2（中）：给检索加状态过滤

实现 `search(query, k=3, status="active")`，只返回指定状态的块，并对比过滤前后的 Recall@3。

<details><summary>参考答案</summary>

```python
def search(self, query, k=3, status=None):
    query_vector = self.embedder.embed(query)
    scored = [
        (chunk, cosine(query_vector, vector))
        for chunk, vector in zip(self.chunks, self.vectors)
        if status is None or chunk.status == status
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:k]
```

过滤后，「病假」问题的 Top1 会变成 `leave-2025`，2024 版不再出现。注意这只解决了「答错版本」，没解决「历史查询」——真正的做法是「按时间点过滤」：查 2024 年的政策时，`status` 参数应该变成「在 2024 年生效的版本」。

</details>

### 练习 3（中）：让引用必须包含条款号

现在引用格式是 `【doc_id §标题】`。请改成 `【doc_id §条款号 标题】`，并校验条款号必须出现在召回片段里。

<details><summary>参考答案</summary>

先改 Prompt：要求模型输出 `【leave-2025 §2.2 使用与结转】`。校验时把标题拆出条款号：

```python
num = heading.split(" ")[0]           # 2.2
if num not in chunk.heading + chunk.text:
    problems.append(f"{doc_id} 缺少条款号 {num}")
```

更稳的做法是切片时就给每块打上 `clause_no` 元数据，引用只允许填元数据里的值，而不是让模型自由生成。

</details>

### 练习 4（难）：加一条「证据不足就拒答」

现在即使 Top1 分数很低，模型也会硬答。请加一个阈值：Top1 余弦低于 0.15 时直接拒答，并统计 10 条问题里有多少条被拒。

<details><summary>参考答案</summary>

```python
hits = store.search(question, k=3)
if not hits or hits[0][1] < 0.15:
    return "当前知识库没有找到足够依据，无法回答，请联系 HRBP。"
```

阈值不能拍脑袋，要用验证集调：把「应该拒答」的问题（比如「食堂几点开饭」）和「应该回答」的问题混在一起，画一条阈值-准确率曲线。阈值太低会瞎答，太高会拒答正常问题。

</details>

### 练习 5（难）：把 10 条问题扩到 30 条并分组

按「假期 / 招聘 / 隐私 / 财务」分组，每组至少 5 条，统计分组 Recall@3，找出最弱的一组。

<details><summary>参考答案</summary>

```python
GROUPS = {"假期": [...], "招聘": [...], "隐私": [...], "财务": [...]}
for group, items in GROUPS.items():
    hit = sum(expected in [c.doc_id for c, _ in store.search(q, k=3)] for q, expected in items)
    print(group, f"{hit}/{len(items)}")
```

通常「隐私」和「财务」最弱，因为它们的问法和文档措辞差异大（员工说「我信息会不会被看到」，文档写「数据分级与访问要求」）。这组数据就是第 09 章混合检索和同义词扩展的输入。

</details>

## 9. 小结与下一章

三句话记住本章：

1. RAG 是「先检索、再生成」：切片、向量化、Top-K、拼 Prompt、引用校验，每一步都能单独评测。
2. 手写哈希 Embedding 的意义不是替代向量库，而是让你看清「向量检索 = 词袋 + 哈希 + 余弦」，以及它在同义词上的天花板。
3. 引用必须可校验：`doc_id` 要在召回结果里，条款标题也要对得上；Recall@K 只说明「找没找到」，不说明「答没答对」。

本章留下了一个明显的悬念：2024 和 2025 两版被同时召回，已归档的旧版甚至排第一。下一章我们用 BM25 + 向量混合检索、元数据过滤和引用质检来解决它，并回答一个更根本的问题：当证据不足时，系统应该拒答，而不是硬编。

---

## 10. 附：LangChain 版关键实现

> 本章实际运行的 demo 使用 **RecursiveCharacterTextSplitter + InMemoryVectorStore**，完整代码见 `code/ch08_rag_basic.py`。下面只保留骨架，方便你对照前面的原理示意阅读。

```python
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=60)
docs = splitter.split_documents(raw_documents)
store = InMemoryVectorStore(embedding=HashEmbeddings())
store.add_documents(docs)
retriever = store.as_retriever(search_kwargs={"k": 3})
evidence = retriever.invoke("年假没休完可以结转到什么时候？")
```

| 本章概念 | LangChain / LangGraph 对应物 |
| --- | --- |
| 切片 | `RecursiveCharacterTextSplitter` |
| 向量库 | `InMemoryVectorStore` |
| 检索 | `as_retriever()` |

> 🧩 **怎么读**：先看正文理解“为什么需要这一层”，再看上面的骨架理解“框架怎么表达这一层”，最后打开 `code/ch08_rag_basic.py` 看完整实现与断言。面试时两条线都要能讲：原理线 + 框架线。
