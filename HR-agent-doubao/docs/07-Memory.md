# 07 · Memory：会话记忆、长期记忆、用户记忆

## 7.1 本章目标

分清三种"记忆"，并用 LangChain 的现成积木实现，再补上生产必须自己写的三件事（抽取、去重、可删除）。

| 类型 | 存什么 | 生命周期 | 本章用什么 |
|---|---|---|---|
| 会话记忆 | 本次对话的消息 | 一次会话 | `RunnableWithMessageHistory` + `InMemoryChatMessageHistory` |
| 长期记忆 | "事实"（偏好、约束、背景） | 跨会话、跨设备 | `InMemoryVectorStore` + Embeddings |
| 用户记忆 | 按用户隔离的人格化信息 | 永久，可删 | 元数据 `user_id` + 删除接口 |

跑法：`python ch07_memory/main.py`

## 7.2 会话记忆：`RunnableWithMessageHistory`

```python
chain = (
    ChatPromptTemplate.from_messages([("placeholder", "{history}"), ("human", "{input}")])
    | get_model([...])
)
chat = RunnableWithMessageHistory(chain, get_history,
                                  input_messages_key="input", history_messages_key="history")
chat.invoke({"input": "张伟是哪个部门的？"}, {"configurable": {"session_id": "A"}})
```

它只做一件小事：**每次调用前按 `session_id` 把历史消息捞出来，塞进 `{history}` 占位符**。

实测：

```
  会话 A 第一轮：张伟在技术中心。
  会话 A 第二轮：你刚问过张伟的部门，还需要别的吗？
  会话 B 第一轮：没有你的工号记录，先告诉我工号。
  会话 A 里的消息数：4，会话 B：2
  ★ 只做隔离，不做裁剪：历史长了它照发，token 会炸（第 08 章解决）
```

### 1.x 的弃用提示（必须知道）

跑这个 demo 你会看到两条 `LangChainDeprecationWarning`：

- `RunnableWithMessageHistory is deprecated. Use LangGraph's built-in persistence instead.`
- `InMemoryChatMessageHistory was deprecated in LangChain 1.6.4, will be removed in 2.0.0`

官方推荐的新写法是 **LangGraph 的 checkpointer**：把消息放进 graph state，`compile(checkpointer=...)` 就自动按 `thread_id` 持久化。第 06、14 章用的就是这个。

**本书的口径**：`RunnableWithMessageHistory` 当作"过渡写法"讲（因为大量存量项目还在用，面试也会问），新项目直接上 checkpointer。两处口径一致：看到 deprecated 不慌，但别在 2026 年的新项目里继续用它。

## 7.3 长期记忆：存事实，不存聊天记录

```python
class Fact(BaseModel):
    kind: Literal["preference", "constraint", "background"]
    text: str = Field(description="一句话事实，不超过 40 字")
    source: str = Field(description="从哪句话抽出来的原文片段")
```

三个设计决定：

1. **存"事实"而不是"原话"**：聊天记录里 90% 是寒暄，塞进向量库只会污染召回。
2. **`kind` 分类型**：`constraint`（硬约束，如"不接受倒班"）在召回时必须**优先注入**，不能被相似度排掉。
3. **`source` 必填**：任何一条记忆都要能追回原文。用户问"你凭什么记我这个"，你要答得出来。

## 7.4 写入三件事：抽取 → 去重 → 打标

```python
def remember(user_id, utterance, max_facts=3):
    facts = extractor.invoke({"utterance": utterance}).facts[:max_facts]
    for f in facts:
        hit = store.similarity_search_with_score(f.text, k=1, filter=_mine(user_id))
        if hit and hit[0][1] > 0.92:
            continue                       # 太像了，视为同一条
        store.add_texts([f.text], metadatas=[{"user_id": user_id, "kind": f.kind, "source": f.source}])
```

`max_facts` 上限很重要：一段话抽出 20 条"事实"，说明抽取器在瞎编。

实测：

```
  用户说：'我不接受倒班，夜班也不行，最好在园区这边'
    + constraint: 不接受倒班与夜班
    + preference: 倾向苏州园区内的岗位
  再次说一遍同样的约束（应被去重）：
    ~ 跳过重复：不接受倒班与夜班
  召回（问'能安排夜班岗位吗？'）：
    · [必须遵守] 不接受倒班与夜班
    · 倾向苏州园区内的岗位
```

## 7.5 `filter` 是函数不是 dict（1.x 高频坑）

```python
def _mine(user_id: str):
    return lambda doc: doc.metadata.get("user_id") == user_id
```

在 `langchain-core 1.8.0` 里，`InMemoryVectorStore.similarity_search_with_score(..., filter=...)` 的 `filter` 类型是 `Callable[[Document], bool]`。传 dict 会得到：

```
TypeError: 'dict' object is not callable
```

而且这个报错栈落在 `in_memory.py` 构造 `Document` 的地方，看起来跟 filter 完全无关，非常难猜。**记住这一条就能省两小时。**

顺带：`store.store` 里存的是 **dict**（`{'id','text','metadata','vector'}`），不是 `Document`。要按元数据删除时：

```python
ids = [key for key, row in store.store.items() if row["metadata"].get("user_id") == user_id]
for i in ids: store.delete([i])
```

## 7.6 合规：用户说"忘掉我"，必须真删

```
  删除前 2 条，删除 2 条，剩余 0 条
  删完再召回：[]
```

红线清单：

| 不该记 | 该记 | 必须有的机制 |
|---|---|---|
| 身份证号、银行卡、住址 | 偏好（班次/城市） | 来源标注 |
| 健康诊断、绩效排名 | 硬约束 | 时间戳 |
| 离职倾向 | 已办事项 | 可删除 |
| 家庭情况 | 沟通语言与称呼 | 按用户隔离（filter 永远带 `user_id`） |

## 7.7 常见坑

1. **把整段对话塞进向量库**：召回一堆寒暄，且每条都在泄露隐私。
2. **去重阈值拍脑袋**：0.92 是经验值。换 Embeddings 模型就要重调（不同模型的相似度分布不同）。
3. **忘了 `user_id` 隔离**：A 用户的记忆被 B 用户召回，这是最严重的事故类型。
4. **会话记忆不裁剪**：第 20 轮时上下文爆掉，模型开始"忘记"最早的约束（第 08 章）。
5. **只写不删**：合规审计时"无法删除"比"存了不该存的"更致命。

## 7.8 自检清单

- [ ] 三种记忆各自的存储介质与生命周期
- [ ] 为什么长期记忆要存"事实 + 类型 + 来源"
- [ ] `filter` 参数在 1.x 里为什么是函数
- [ ] 删除接口为什么是合规红线

## 7.9 练习

1. 把 `DeterministicFakeEmbedding` 换成真 Embeddings（BGE/OpenAI），重调 0.92 阈值。
2. 给 `Fact` 加 `expired_at`，召回时过滤过期事实（记忆衰减）。
3. 用 LangGraph checkpointer 重写会话记忆，对比 `RunnableWithMessageHistory` 的差别。
