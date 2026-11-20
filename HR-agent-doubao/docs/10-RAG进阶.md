# 10 · RAG 进阶：混合检索、Rerank、版本治理、引用质量

## 10.1 本章目标

1. 用 `BM25Retriever` + 向量检索 + `EnsembleRetriever` 做混合召回；
2. 元数据过滤 + "每标题取最新版本" 解决版本串台；
3. 自己写 rerank（相关性打分 + 低分下限），做到"敢丢"；
4. 引用校验：答案里的 `[来源: x]` 必须能对回原文。

跑法：`python ch10_rag_advanced/main.py`

## 10.2 两路检索各有所长

```python
vec_r  = InMemoryVectorStore(LocalHashEmbedding()).as_retriever(search_kwargs={"k": 3})
bm25_r = BM25Retriever.from_documents(DOCS, k=3)
```

实测（问"E1001 的年假还剩几天"）：

```
  向量检索： ['E1001 年假余额', '年假结转规则', '年假结转规则']
  BM25 检索： ['E1001 年假余额', '技术中心调休补充规定', '请假审批链']
```

结论：问**工号/条款号/专有名词**，BM25 更准（精确词命中）；问**口语同义**（"没休完能留到明年吗"），向量更强。

## 10.3 `EnsembleRetriever`：1.x 里搬去了 `langchain-classic`

```python
from langchain_classic.retrievers import EnsembleRetriever   # ★ 不是 langchain_core
ens = EnsembleRetriever(retrievers=[bm25_r, vec_r], weights=[0.5, 0.5])
```

这是一个真实的踩坑记录：`from langchain_core.retrievers import EnsembleRetriever` 在 1.8 会报 `ImportError`——它在 1.x 归到了 `langchain-classic`。类似的还有不少（`langchain-community` 正在 sunset）。

依赖也别忘了：`BM25Retriever` 需要 `rank_bm25`，否则报 `Could not import rank_bm25`。

## 10.4 版本治理：过滤 + 取最新

只做 `as_of <= T` 的过滤是不够的——旧版本的 `as_of` 更早，一样能通过条件。实测：

```
  as_of=2026-11-15（只过滤不取最新）：
    ← [2025-06-01] 技术中心调休补充规定
    ← [2023-01-01] 年假结转规则       ← 旧制度混进来了
```

正确的口径是"每个标题只取 `as_of` 最新的那个"：

```python
def latest_per_title(hits, as_of):
    best = {}
    for d in hits:
        if d.metadata["as_of"] > as_of: continue
        cur = best.get(d.metadata["title"])
        if cur is None or d.metadata["as_of"] > cur.metadata["as_of"]:
            best[d.metadata["title"]] = d
    return sorted(best.values(), key=lambda d: d.metadata["as_of"], reverse=True)
```

修正后：

```
  as_of=2023-06-30：← [2023-01-01] 年假结转规则：当年清零，不折现，不可结转
  as_of=2026-11-15：← [2026-01-01] 年假结转规则：可结转至次年 3 月 31 日…
```

★ **RAG 里最严重的错误不是"召回不准"，是"用 2023 年的制度回答 2026 年的问题"。**

## 10.5 Rerank：敢丢才是重排

```python
class Score(BaseModel):
    relevant: bool
    score: int = Field(ge=0, le=10)

reranker = RERANK_P | model.with_structured_output(Score)

THRESHOLD = 6
for d in cands:
    s = reranker.invoke({"q": q, "doc": d.page_content})
    if s.score >= THRESHOLD: kept.append(d)
```

实测：

```
    技术中心调休补充规定  score=2 ✗ 丢弃
    年假结转规则         score=9 ✓ 进上下文
    请假审批链          score=4 ✗ 丢弃
  召回 3 条 → 重排后 1 条
  ★ Rerank 的价值不是'排序'，是'敢丢'；没有低分下限的重排，只是给噪声排了个名次
```

生产上换成 cross-encoder（`bge-reranker`）可以省掉这次额外的模型调用，但**阈值照样要设**。

## 10.6 引用质量：解析出来对不上，就当失败

```python
cited = [s.split("]")[0] for s in ans.split("[来源: ")[1:]]
available = {d.metadata["title"] for d in kept}
ok = all(c in available for c in cited)
```

实测通过：

```
  答案：可以。年假未休完可结转至次年 3 月 31 日，逾期作废。 [来源: 年假结转规则]
  解析到的引用：['年假结转规则'] / 可核对的来源：['年假结转规则']
  引用校验：✓ 全部可对回原文
```

对不上时不要"重试一次就算了"，直接返回兜底话术并记一条 bad case。这就是第 17 章要算的**幻觉率**的来源。

## 10.7 四件事的分工

| 手段 | 治什么 |
|---|---|
| 混合检索 | 召不回（专有名词、口语同义各失灵一半） |
| Rerank | 召回里混了噪声 |
| 元数据过滤 + 取最新 | 版本串台 |
| 引用校验 | 答了但没法追责 |

四件都做，才算能上线的 RAG；只做前两件，是 demo。

## 10.8 常见坑

1. **`EnsembleRetriever` 导入路径错了**（见 10.3）。
2. **忘装 `rank_bm25`**。
3. **权重拍脑袋**：`[0.7, 0.3]` 偏向 BM25，适合"查工号/查条款"；制度问答通常 `[0.5, 0.5]`。
4. **只过滤不取最新**（见 10.4）。
5. **阈值定得太低**：`THRESHOLD=3` 等于没设，噪声照样进上下文。
6. **引用标注格式不统一**：模型有时写 `[来源:xx]`，有时写 `（来源：xx）`。要在 prompt 里给死格式，并做正则兜底。

## 10.9 自检清单

- [ ] 能说出 BM25 与向量检索各自强在哪
- [ ] 知道 1.x 里 `EnsembleRetriever` 从哪导入
- [ ] 能解释"过滤"与"取最新"为什么是两步
- [ ] 理解 rerank 的核心是阈值，不是排序

## 10.10 练习

1. 把 weights 改成 `[0.7, 0.3]`，比较两类查询的召回差异。
2. 把 `THRESHOLD` 调到 8，观察拒答率与可信度的权衡。
3. 给 `as_of` 接上"用户当前时间"，跑通历史回溯场景（"2023 年那会儿制度是怎么规定的"）。
