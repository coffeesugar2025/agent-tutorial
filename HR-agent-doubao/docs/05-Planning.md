# 05 · Planning：把"计划"变成可校验的数据

## 5.1 本章目标

1. 用 `with_structured_output` 让模型产出**结构化的计划**（`Step` 列表），而不是一段散文；
2. 用拓扑排序保证执行顺序，并在执行前就抓出**环**和**死依赖**；
3. 一步失败 → 只重排剩余步骤（重规划），不是整条重来；
4. 知道什么情况下**不该**用 Planning。

跑法：`python ch05_planning/main.py`

## 5.2 计划是数据，不是文字

```python
class Step(BaseModel):
    id: str
    action: str
    depends_on: list[str] = Field(default_factory=list)
    acceptance: str = Field(description="这一步怎么算完成（可验证的判据）")

class Plan(BaseModel):
    goal: str
    steps: list[Step]
```

`acceptance`（验收判据）是整个设计的关键。没有它，计划就是"看起来有条理的废话"；有它，每一步都能被程序判断"到底完成没有"。

一条 prompt 拿到它：

```python
prompt | model.with_structured_output(Plan)
```

## 5.3 拓扑排序 + 环检测

```python
def topo_order(plan: Plan) -> list[str]:
    ids = {s.id for s in plan.steps}
    deps = {s.id: [d for d in s.depends_on if d in ids] for s in plan.steps}
    for s in plan.steps:
        for d in s.depends_on:
            if d not in ids:
                raise ValueError(f"步骤 {s.id} 依赖了不存在的 {d}")
    order, done = [], set()
    while len(order) < len(ids):
        ready = [i for i in ids if i not in done and all(d in done for d in deps[i])]
        if not ready:
            raise ValueError(f"计划里有环或死锁：剩余 {sorted(ids - done)}")
        order.append(sorted(ready)[0]); done.add(order[-1])
    return order
```

实测（反面）：

```
  计划里有环或死锁：剩余 ['a', 'b']
  ★ 计划是数据 → 数据就能校验。校验放在执行前，比事后 debug 便宜一百倍
```

## 5.4 图结构：planner → executor（循环）→ summarize，中间插 replan

```python
builder.add_conditional_edges("executor", route,
    {"execute": "executor", "replan": "replan", "summarize": "summarize", "give_up": "give_up"})
```

`route` 的判断只有三行逻辑：这一步失败了没？还有没有剩下的步骤？重规划次数超了没？

## 5.5 重规划的真正工作量：改写依赖边

这是本章最容易翻车的地方。`s2` 失败后，我们加了一个 `s2_alt` 顶上，但下游 `s3` 还写着 `depends_on=["s2"]` —— 于是 `topo_order` 直接抛"步骤 s3 依赖了不存在的 s2"。

正确的做法：

```python
new_steps = [
    s.model_copy(update={"depends_on": [alt_id if d == failed else d for d in s.depends_on]})
    for s in rest
] + [Step(id=alt_id, action="用缓存的人才库快照代替实时库", depends_on=[], acceptance="能拿到候选人列表")]
```

**重规划不只是"加一步"，是把依赖关系图一起改。** 这一点在真实项目里同样是坑：任何"替换节点"都要顺手修边。

实测输出：

```
  计划：把 P1001 的候选人初筛做完并给出建议
    s1 解析 JD 得到岗位画像  depends_on=[]
    s2 拉取该岗位全部简历    depends_on=['s1']
    s3 按评分卡打分并排序    depends_on=['s2']
  拓扑序：['s1', 's2', 's3']
    执行 s1：✓ JD 已解析
    执行 s2：✗ 简历库连接超时（模拟下游故障）
    重规划 #1：s2 失败，改用降级路径
    执行 s2_alt：✓
    执行 s3：✓ 已按评分卡打分：C1001 82 分 / C1024 76 分
  结果：完成 3/4 步；建议约面 C1001（82 分）
```

## 5.6 什么时候不该用 Planning

| 判据 | 该用什么 |
|---|---|
| 步骤固定、每次都一样（查余额、发通知） | Workflow / 状态机（第 06 章） |
| 一句话就能答完 | 单条链或 `create_agent` |
| 每步结果不可预估且强耦合（边做边看） | ReAct 循环（第 03 章） |
| 步骤多、可并行、需要人看中间结果 | Plan-and-Execute（本章） |

判断口诀：**"你能不能提前写出这 4 步？"** 能→Planning；不能→ReAct。

## 5.7 常见坑

1. **计划不校验就执行**：模型给的顺序常常不是依赖顺序。拓扑排序不是"锦上添花"，是必需品。
2. **重规划次数没上限**：本章 `MAX_REPLANS=2`。没有上限就是"无限重试"的另一种写法。
3. **重规划时丢了已完成的进度**：只重排 `results` 之外的步骤，已完成的不动。
4. **`TypedDict` 里加了私有字段但没声明**：`_plan_args`、`_failed` 这类字段要写进 `TypedDict`，否则 LangGraph 更新时会报 KeyError。
5. **每步都让模型重新规划**：那是 ReAct，不是 Plan-and-Execute。计划只在开头和失败时重排。

## 5.8 自检清单

- [ ] 计划里为什么必须有 `acceptance`
- [ ] 拓扑排序能抓哪三类问题
- [ ] 重规划为什么必须改写下游依赖
- [ ] 能说出"什么场景不该用 Planning"

## 5.9 练习

1. 给 `Step` 加 `est_tokens`，在 planner 里拒绝总预算超标的计划。
2. 把 `s2` 改成"先试两次再降级"，观察 replan 次数与总耗时的变化。
3. 把 Plan-and-Execute 换成 `create_agent` + 一个 `write_plan` 工具，对比两种做法的可控性与可解释性。
