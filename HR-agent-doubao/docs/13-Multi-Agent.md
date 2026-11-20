# 13 · Multi-Agent：分工、交接、仲裁

## 13.1 本章目标

1. 想清楚"为什么需要多智能体"——答案不是"模型不够聪明"，是"权限与责任要分开"；
2. 用 Supervisor 模式做串行派活，并加交接上限；
3. 用 `Send` 做并行 fan-out + join，知道它的代价；
4. 能收口冲突（合规一票否决），而不是"三个都说没问题"。

跑法：`python ch13_multi_agent/main.py`

## 13.2 三个专家（各自有权、也有禁区）

```python
WORKERS = {
    "recruiter": {"role": "招聘专员", "scope": "候选人匹配、面试安排", "may_not": "定薪、改带宽"},
    "comp":      {"role": "薪酬专员", "scope": "带宽核对、特批测算",     "may_not": "承诺候选人薪资"},
    "legal":     {"role": "合规审核", "scope": "合同条款、用工风险",     "may_not": "做业务决策"},
}
```

★ **多智能体的真正理由：定薪的人和合规的人不能是同一个。** 一个"全能 Agent"给它全套工具，它就能既定薪又给自己开绿灯。

## 13.3 Supervisor：调度者只决定"谁下一个"

```python
def supervisor(state):
    if state.get("turns", 0) >= MAX_HANDOFFS:
        return {"next": "FINISH", "handoffs": ... + ["达到交接上限，强制收口"]}
    done = state.get("findings", {})
    nxt = model.invoke(ROUTE_PROMPT).content.strip()   # recruiter / comp / legal / FINISH
    return {"next": nxt, "turns": state.get("turns", 0) + 1}
```

三个设计决定：

1. **supervisor 不干活**。它只做路由。干活会污染判断。
2. **交接上限 `MAX_HANDOFFS`**。没有它，A→B→A 会转到天亮。
3. **每个 worker 只拿"自己该看的那部分上下文"**，不是全量。这是成本与安全的双重要求。

实测：

```
    supervisor → recruiter
    recruiter 输出：C1024 与 P1001 匹配度 82%，可约二面
    supervisor → comp
    comp 输出：C1024 期望 28K，带宽 22-25K，超 3K，需薪酬特批
    supervisor → legal
    legal 输出：合规提示：offer 需写明试用期与竞业条款；28K 超出带宽须留特批书面记录
    supervisor → FINISH
    仲裁结果：有条件通过：走薪酬特批后再发 offer
```

## 13.4 仲裁：必须有人署名

```python
def judge(state):
    legal_veto = "须留特批书面记录" not in state["findings"].get("legal", "")
    if legal_veto:                      verdict = "退回：合规未通过"
    elif "特批" in comp:                verdict = "有条件通过：走薪酬特批后再发 offer"
    else:                               verdict = "通过"
```

规则要显式写出来：**合规有一票否决；薪酬与招聘冲突时以制度为准，不以"谁先说"为准。**

生产上更稳的做法是让 legal 输出结构化判决（`veto: bool + reason`），而不是靠字符串匹配。

## 13.5 Send：并行 fan-out 与 join

```python
class ReviewState(TypedDict, total=False):
    case: str
    reviews: Annotated[list[dict], operator.add]   # ★ 并行分支写同一字段 → 必须声明 reducer
    merged: str

def fan_out(state):
    return [Send(w, {"case": state["case"], "reviews": []}) for w in WORKERS]

r.add_conditional_edges(START, fan_out, list(WORKERS))
for n in WORKERS: r.add_edge(n, "join")
```

两个要点：

- **`Send` 的第二个参数是"发给这个节点的初始 state"**。三个节点并行跑，结果无序返回。
- **写同一个字段必须加 reducer**（`Annotated[list, operator.add]`），否则后写的覆盖先写的。

实测：

```
    [recruiter] 并行评审完成
    [comp] 并行评审完成
    [legal] 并行评审完成
    合并结果：共 3 份评审，有条件通过；待处理：['comp:期望 28K 超带宽 3K']
```

★ `Send` 的价值：**墙钟时间 = 最慢那个**；代价：结果无序、冲突要自己收口。

## 13.6 四个最容易翻车的点

| 坑 | 后果 | 解法 |
|---|---|---|
| 无限交接 | A↔B 永远收不了口 | 交接上限 + 收敛判据 |
| 上下文污染 | token 翻三倍，互相带偏 | 每个 worker 只给切片 |
| 责任真空 | 三个都说没问题，没人负责 | 必须有仲裁节点署名 |
| 成本失控 | 串行 5 个专家 = 5 倍成本 | 先问"单 Agent + 工具门禁够不够" |

★ **能用单 Agent + 工具门禁解决的，别上多智能体。** 多智能体的门槛是"权限必须分开"，不是"任务看起来复杂"。

## 13.7 单 Agent 还是多 Agent：一个判断流程

```
需要不同的人（或不同权限）签不同的字？   ── 是 → 多智能体
  └ 否
任务能拆成"互不依赖的子任务"并行跑？      ── 是 → Send 并行（也是一种多智能体）
  └ 否
工具数量 > 10 且经常选错？                ── 是 → 按角色分组（挂载不同工具集）
  └ 否 → 单 Agent + 严格门禁
```

## 13.8 常见坑

1. **supervisor 也调工具**：判断被污染，路由摇摆。
2. **worker 之间共享全部历史**：成本与干扰双爆。
3. **并行分支忘了 reducer**：review 只剩最后一份。
4. **没有仲裁节点**：多智能体最常见的"看似完成，实则无人负责"。
5. **按"角色扮演"而非"权限边界"分工**：给三个 agent 起名叫"资深 HR""薪酬专家"，但工具集完全一样——那只是同一件事跑三遍。

## 13.9 自检清单

- [ ] 能说出"必须多智能体"的唯一硬理由
- [ ] 知道 supervisor 为什么不能干活
- [ ] 能解释 `Send` + `Annotated[list, operator.add]` 的组合
- [ ] 能说出多智能体的四个坑

## 13.10 练习

1. 把 `MAX_HANDOFFS` 改成 2，观察结论质量与成本的变化。
2. 把 legal 的输出改成 `with_structured_output(Verdict)`（带 `veto` 字段）。
3. 把三个 worker 指向不同档位的模型（T1/T2/T3），统计"每正确一次"的成本。
