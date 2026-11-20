# 09 · RAG 基础：解析、切片、向量化、召回、拼 Prompt

## 9.1 本章目标

1. 用 `RecursiveCharacterTextSplitter` 切片，理解"切断了条件—结论"的后果；
2. 用 `InMemoryVectorStore` + `as_retriever()` 做召回；
3. 用 LCEL 把"检索 → 拼 Prompt → 生成 → 解析"串成一条 RAG 链；
4. 知道三种典型失败和三个最低成本的兜底。

跑法：`python ch09_rag_basics/main.py`

## 9.2 切片：三种切法，差别很大

```python
splitters = {
    "固定 80 字（不对）": RecursiveCharacterTextSplitter(chunk_size=80, chunk_overlap=0, separators=[""]),
    "按段落（次优）":     RecursiveCharacterTextSplitter(chunk_size=140, chunk_overlap=20, separators=["\n\n", "\n"]),
    "按标题层级（对）":   RecursiveCharacterTextSplitter(chunk_size=110, chunk_overlap=0,
                                                    separators=["\n## "], keep_separator=True),
}
```

实测（同一份 332 字的《年假管理制度》）：

```
  固定 80 字（不对） → 5 块，平均 66 字
      · 正后按司龄计算年假：满 1 年 5 天…       ← 开头被切掉了"转"
  按段落（次优） → 3 块，平均 109 字
  按标题层级（对） → 5 块，平均 64 字
      · ## 年假天数 / 转正后按司龄计算年假…     ← 条件与结论在同一块里
```

**切片单位应该是"语义单元"，不是"字数"。** 制度文档的语义单元就是"## 一节"。

三个参数的经验值：

| 参数 | 经验 | 说明 |
|---|---|---|
| `chunk_size` | 中文 300–800 字 | 太小丢上下文，太大召回不准且浪费 token |
| `chunk_overlap` | 10%–20% | 防止答案正好落在切口上 |
| `separators` | 按文档结构定 | Markdown 用 `\n## `；合同用条款号；代码用函数边界 |

## 9.3 每块都要挂元数据

```python
Document(page_content=chunk, metadata={
    "source": "sop_leave.md", "section": "年假天数", "version": "v3", "updated": "2026-09-01"})
```

元数据不是"顺手加的"，是后面四件事的基础：**引用标注**（第 10 章）、**版本过滤**（第 10 章）、**权限过滤**（部门/密级）、**增量更新**（第 11 章）。

## 9.4 建库与召回

```python
store = InMemoryVectorStore(LocalHashEmbedding())
store.add_documents(docs)
retriever = store.as_retriever(search_kwargs={"k": 3})
retriever.invoke("年假怎么请")
```

`LocalHashEmbedding` 是本章提供的**离线向量**（中文 2-gram 哈希 + 归一化）。它不是 SOTA 模型，但保留字面相关性，够把"切片/召回/重排"讲清楚。真实项目换：

```python
from langchain_openai import OpenAIEmbeddings
emb = OpenAIEmbeddings(model="text-embedding-3-small", base_url=..., api_key=...)
```

## 9.5 一条完整的 RAG 链

```python
rag = (
    {"context": (lambda x: x["question"]) | retriever | format_docs,
     "question": lambda x: x["question"]}
    | PROMPT | model | StrOutputParser()
)
rag.invoke({"question": "试用期员工有年假吗？"})
```

这个 dict 写法值得记住：**LCEL 里一个 dict 就是并行分支。**

- `context` 分支走检索链；
- `question` 分支原样透传；
- 两个分支的结果作为 prompt 的变量。

## 9.6 三种典型失败

| 失败 | 为什么 | 兜底 |
|---|---|---|
| 召回到了但没答到 | 切片把"条件"和"结论"拆开 | 按语义单元切；`chunk_overlap` 兜住切口 |
| 答了但没来源 | prompt 没强制引用 | 写死 `[来源: 章节]`，答案里没来源就算失败 |
| 该说没有却说有 | 没给兜底话术 | prompt 里写"资料里没有就说不知道，并告诉用户找谁" |

三个最低成本的兜底（按顺序上）：

1. prompt 里写死兜底话术 + 替代动作（找 HRBP）；
2. 强制引用标注，无引用即判失败；
3. 检索分数低于阈值就不硬答，转人工/追问。

## 9.7 常见坑

1. **切片太小**：召回一堆半句话，模型只能编。
2. **没有元数据**：答对了也没法标来源，评审时无法追责。
3. **`k=10` 全塞进去**：上下文被噪声占满，准确率反而下降。先用 k=3，加 rerank 再放宽（第 10 章）。
4. **把 Embedding 模型和向量库混着换**：换模型必须重建索引，旧向量和新向量不在同一个空间。
5. **以为"接个向量库"就叫 RAG**：没有切片策略、没有元数据、没有引用校验，那只是"模糊搜索 + 让模型自由发挥"。

## 9.8 自检清单

- [ ] 能说出切片三个参数各自的取舍
- [ ] 知道元数据在后续四件事里的作用
- [ ] 能画出 RAG 链的四个环节
- [ ] 能说出三种失败对应的兜底

## 9.9 练习

1. 把 `separators` 改成 `["\n\n"]`，观察"年假没休完能折钱吗"的召回变化。
2. 给 `metadata` 加 `effective_from`，检索时过滤未生效的版本。
3. 在 RAG 链前面加一步"查询改写"（把口语问题改成制度术语），比较召回质量。
