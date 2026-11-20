# 02 · Prompt 与结构化输出

## 2.1 本章目标

1. 把 prompt 从"一段话"变成"五个部位"的结构化模板；
2. 用 `with_structured_output(Pydantic)` 让**契约成为模型的返回类型**；
3. 校验失败时把错误喂回去重试（带次数上限）；
4. 用 `evidence` 字段让幻觉自己暴露。

跑法：`python ch02_structured/main.py`

## 2.2 五部位 prompt

```python
PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "你是招聘 HR 的结构化抽取器。\n"            # ① 角色
     "任务：把 JD 文本解析成岗位画像。\n"          # ② 任务
     "约束：只依据 JD 原文，不得引入外部知识；\n"   # ③ 约束
     "输出：必须符合给定的 JSON Schema，不要解释。\n" # ④ 输出格式
     "兜底：无法判断的字段填 null，并写'原文未提及'。"), # ⑤ 兜底
    ("human", "<jd>\n{jd}\n</jd>"),
])
```

第 ⑤ 部位最容易被漏，也最值钱：**不说"不知道怎么办"，模型就一定会编**。

## 2.3 契约 = Pydantic 类

```python
class JobProfile(BaseModel):
    title: str = Field(description="岗位名称，如 高级前端工程师")
    city: str = Field(description="工作城市")
    years: str = Field(description="经验要求，如 3-5年")
    must_have: list[str] = Field(description="硬性门槛，逐条列出")
    skills: list[str] = Field(description="核心技能，最多 6 项")
    risk: str = Field(description="这条 JD 的风险点；没看出风险就写'无'")

chain = PROMPT | model.with_structured_output(JobProfile)
profile = chain.invoke({"jd": JD})      # 拿到的就是一个 JobProfile 对象，不是字符串
```

`with_structured_output` 做了什么？两件事：

1. 把你的 Pydantic 模型转成工具 schema 发给模型（模型被要求"调用这个结构"）；
2. 用 `PydanticToolsParser` 把模型返回的 `tool_calls` 解析回你的对象，**校验失败会抛 `OutputParserException` / `ValidationError`**。

这一步的重要性：从"我用正则从文本里抠 JSON"变成"类型系统替我兜底"。字段缺了、类型错了，程序立刻知道。

## 2.4 修复循环：错误回灌

模型第一次少给了 `risk` 和 `must_have`，`ValidationError` 会明确告诉你缺哪个字段。**把这段错误原文塞回下一轮 prompt**，模型大多能自己改：

```python
for attempt in range(MAX_FIX):
    try:
        return chain.invoke({"jd": JD})
    except (ValidationError, OutputParserException) as e:
        history.append(AIMessage(content=str(e)[:500]))   # ← 错误原文进上下文
        continue
raise RuntimeError("修不好，转人工")
```

三个工程要点：

- **上限必须有**（本章 `max_fix=2`）。没有上限的自我修复循环＝无限烧钱。
- **错误信息要截断**（`[:500]`），`ValidationError` 的完整栈可能几千 token。
- **修复只对"格式/字段缺失"有效**。如果是"业务事实错"（比如薪资区间读错），重试一百次也一样错——这类要靠 evidence 校验抓（下一节）。

## 2.5 evidence：让幻觉自己露出来

```python
class EvidenceField(BaseModel):
    value: str | None = Field(description="抽取到的值；原文没有就填 null")
    evidence: str | None = Field(description="支撑该值的原文片段；没有就填 null")

class CandidateFacts(BaseModel):
    姓名: EvidenceField
    最高学历: EvidenceField
    工作年限: EvidenceField
```

然后做一件非常便宜的校验：**evidence 必须能在原文里 grep 到**。

```python
for field, ev in facts:
    if ev.value and ev.evidence not in resume_text:
        errors.append(f"{field}: evidence 在原文中找不到")
```

这比"让另一个模型来审"便宜两个数量级，而且结果确定。生产上这是幻觉率最低成本的度量方式（第 17 章会用它算指标）。

## 2.6 实测输出

```
  第一次调用 → ValidationError：risk Field required；must_have Field required
  第 2 次（把错误喂回去）→ 成功
  ★ 结构化输出的价值：错误在程序里炸，而不是在用户那里炸
```

## 2.7 常见坑

1. **忘了 `description`**：Pydantic 字段没有 description，模型就不知道这个字段要填什么。`Field(description=...)` 不是可选的装饰。
2. **契约太宽**：所有字段都 `str | None`，模型会全部填 null 保守交差。该必填的必填。
3. **把"不要输出解释"当万能**：有些模型仍会带 markdown 代码块。`with_structured_output` 走的是工具调用通道，通常不受影响；如果你用 JSON Mode，就要自己剥外层代码块。
4. **拿 `dict` 硬塞**：`with_structured_output(dict)` 也能跑，但你失去了校验。用 Pydantic。
5. **在假模型下看不到失败**：剧本里写的是"正确调用"，所以只有真模型才会出现"第一次缺字段"。想练修复循环，就把剧本第一条故意写缺字段（本章 demo 就是这么做的）。

## 2.8 自检清单

- [ ] 五部位 prompt 各是什么，为什么"兜底"部位不能省
- [ ] `with_structured_output` 内部做了哪两件事
- [ ] 修复循环为什么必须有上限、为什么只对格式错误有效
- [ ] evidence 校验为什么比"模型自审"更可靠

## 2.9 练习

1. 把 `risk` 改成 `Literal["高","中","低","无"]`，观察模型是否会因为值不在枚举里而失败。
2. 给 `CandidateFacts` 加一个 `期望薪资` 字段，并用 evidence 校验它在简历里是否出现。
3. 把 `max_fix` 从 2 改成 0，看看失败率上升多少——这就是"省一次重试"的代价。
