---
title: "04 | Planning：ReAct、Plan-and-Solve 与任务拆解"
slug: "planning"
order: 4
part: "单 Agent 核心"
minutes: 60
difficulty: "进阶"
prerequisites: ["03"]
summary: "同一个招聘任务跑两种规划：计划、依赖、重规划与预算。"
---
> 🧩 **框架说明**：本章 demo 基于 **LangChain 1.x + LangGraph 1.x**，核心 API：`create_agent`、`StateGraph`、`Command`。正文中的代码若标注“原理示意”（包括旧版 MockLLM / 手写循环片段），用于解释内部机制，不是最终运行代码；完整可运行代码见 `code/ch04_planning.py`。


## 0. 本章你会得到什么

1. 用自己的话说清 CoT、ReAct、Plan-and-Solve 三者的区别与适用场景。
2. 让模型输出可执行的结构化计划：步骤、依赖、验收标准，而不是一段散文。
3. 用代码按依赖执行计划，并在某一步失败时只重规划失败分支。
4. 识别“计划幻觉”：工具不存在、依赖成环、验收标准无法执行。
5. 给 Agent 设预算与终止条件，能比较 ReAct 与 Plan 的调用次数和 token。

## 1. 场景

Acme 科技 HR 总监林芳把招聘负责人郑爽叫进会议室：“算法组要在 3 周内进 2 名 P6，月薪上限 45K，11 月 20 日启动。你让 Agent 跑一版方案给我。”

郑爽上次用 ReAct 模式跑过类似任务。Agent 想一步做一步，看起来很灵活，但实际跑了 23 次模型调用、4.1 万 token，中间还给一位已经标记“淘汰”的候选人安排了面试——因为它在第 12 轮忘了第 4 轮看到的结论。林芳只问了三个问题：钱花在哪、现在到哪一步、如果第 3 步失败怎么办。郑爽一个都答不上来。

这次她换成 Plan-and-Solve：先让模型给出 5 步计划，每步写清目标、调用哪个工具、依赖哪一步、什么算完成；代码按依赖执行，某一步不达标就只重写那一步。最后账单是 3 次模型调用、408 token，计划本身还能存档、能给林芳看、能复盘。

这一章我们就把这两种模式放在同一个任务上跑一遍，用数字说话。

> 💡 **小白提示**：Planning 不是“让模型多想一会儿”。想得久不等于有计划。计划是一份**可执行、可验收、可修改**的结构，代码能按它一步一步做事，失败了知道改哪一步。

## 2. 概念

### 2.1 CoT 不等于 Planning

CoT（Chain of Thought，思维链）让模型写出推理过程，例如“先看 HC，再看渠道，最后排面试”。它改善的是**单次回答的质量**，本质仍是一段文本。

Planning 多做了三件事：

- **结构化**：输出步骤列表，每步有 id、工具、依赖、验收标准，代码能解析。
- **可执行**：步骤与真实工具绑定，执行权在代码，不在模型的想象里。
- **可修正**：某步失败时，知道失败的是哪一步、影响哪些下游，只改这一段。

一句话：CoT 是“想清楚再答”，Planning 是“想清楚、写下来、按它做、做坏了改”。

### 2.2 ReAct：想一步，做一步

ReAct = Reasoning + Acting。每一轮模型输出一个 Thought（想法），选择一个 Action（工具调用），代码执行后把 Observation（观察结果）回填，模型再想下一步。

```text
Thought ──▶ Action ──▶ Observation
   ▲                        │
   └────────────────────────┘
         （锯齿状，一步一回头）
```

优点是对环境变化反应快：查到“只有 1 个候选人达标”，下一轮立刻补渠道。缺点是没有全局计划：容易漏步骤、重复调用，而且每一轮都要把全部历史再喂给模型，token 随轮数上升。

### 2.3 Plan-and-Solve：先画图，再施工

Plan-and-Solve 把一次任务拆成两个阶段：先让模型产出一份完整计划，再由执行器按依赖顺序执行。执行中某步失败，进入 Replan 阶段，只修补失败分支。

```text
        ┌──────────────────────────────┐
        │ Plan：s1 → s2 → s3 → s4 → s5 │
        └──────────────┬───────────────┘
                       │ 按依赖执行
                       ▼
        ┌──────────────────────────────┐
        │ Execute：逐步调用工具、验收   │
        └──────────────┬───────────────┘
                       │ s3 未达标
                       ▼
        ┌──────────────────────────────┐
        │ Replan：只替换 s3 为 s3b      │
        │ 下游 s4 自动改依赖 s3b        │
        └──────────────┬───────────────┘
                       │
                       ▼
              继续执行 s4 → s5
```

这个任务对应的依赖 DAG 是：

```text
s1 确认 HC
 │
 ▼
s2 发布 JD
 │
 ▼
s3 筛选候选人 ──失败──▶ s3b 拓宽渠道
 │                        │
 └──────────┬─────────────┘
            ▼
s4 安排面试
 │
 ▼
s5 发起 offer 审批
```

注意 s3 和 s3b 是“二选一”的关系：s3 达标就继续，不达标才走 s3b；s4 只依赖最终达标的那一个。

### 2.4 计划长什么样

本章的计划是一个 JSON 对象，`steps` 里每一步有五个字段：

```json
{
  "id": "s3",
  "goal": "筛出至少 2 名 P6 算法候选人",
  "tool": "screen",
  "depends_on": ["s2"],
  "done_when": "qualified >= 2"
}
```

- `id`：步骤唯一标识，重规划时靠它定位。
- `goal`：给人看的目标，也进日志和汇报。
- `tool`：这一步调用哪个工具，必须是注册表里真实存在的名字。
- `depends_on`：前置步骤列表，决定执行顺序。
- `done_when`：验收标准。模型写自然语言，代码要编译成可执行的判断。

最后这一点最容易糊弄。`done_when` 写成“候选人质量不错”，模型和代码都无法判断；写成 `qualified >= 2`，代码才能决定“过”还是“重规划”。

### 2.5 计划幻觉的四种样子

模型生成的计划看起来很像回事，但经常不能执行。常见四类：

1. **工具不存在**：调 `launch_rocket` 或 `post_jd_v2`，注册表里没有。
2. **依赖成环**：s2 依赖 s3，s3 又依赖 s2，拓扑排序直接卡死。
3. **验收不可执行**：`done_when` 是“HR 满意”，代码无法判断。
4. **副作用重复**：计划和 ReAct 历史里都安排了面试，执行时给同一候选人排了两次。

代码能挡住的只有前两类（工具白名单、环检测），后两类要靠“验收谓词”和幂等键。所以 `Plan` 在 `model_validator` 里检查 id 唯一、工具存在、依赖存在、无环；`ACCEPT` 字典把每个工具的完成条件编译成函数。

> ⚠️ **生产提醒**：不要把模型生成的计划直接执行。计划必须先过三道闸：Schema 校验、工具白名单、依赖环检测；涉及写操作的步骤还要加人工审批或幂等键。计划是“建议”，不是“命令”。

### 2.6 重规划：只改坏掉的那一段

失败后的第一反应往往是“让模型重新规划整单”。这很贵，而且会把已经成功的步骤再跑一遍，产生重复副作用。

正确做法是：把失败步骤、观察结果、原计划交给模型，让它只输出**替代步骤**；代码把失败步骤摘掉，把下游依赖改指到替代步骤，再重新拓扑排序。已经完成的步骤记在 `done` 里，不会重跑。

本章的 s3 只筛出 1 人（`qualified=1`），不满足 `>= 2`。Replan 产出 s3b“放宽到相邻技能并启动猎头补位”，s4 的依赖从 s3 改成 s3b，执行继续。

### 2.7 预算与终止条件

Planning 并不能保证不失控，必须设硬边界：

- **步数上限**：最多执行多少步，防止计划越补越长。
- **重规划次数**：例如最多 1 次，第二次失败就交给人。
- **token 预算**：累计超过阈值就停，返回“预算耗尽”。
- **无进展检测**：连续两步没有推进 `done`，视为卡死。

本章设了 `MAX_STEPS=8`、`MAX_REPLANS=1`、`TOKEN_BUDGET=8000`。真实系统还要加墙钟超时和单步超时。

## 3. 动手

> 🧩 **读法**：第 3 节的代码用于解释原理；本章实际运行的 demo 已改为 LangChain 版，完整代码见章末“LangChain 版关键实现”与 `code/` 对应脚本。


运行：

```powershell
python code/ch04_planning.py
```

脚本先跑 ReAct，再跑 Plan-and-Solve，最后打印对比表。计划模型和执行器的核心是这两段：

```python
class Plan(BaseModel):
    steps: list[PlanStep]

    @model_validator(mode="after")
    def check_graph(self):
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step id 重复")
        for step in self.steps:
            if step.tool not in TOOLS:
                raise ValueError(f"{step.id} 调用了不存在的工具 {step.tool}")
            missing = [dep for dep in step.depends_on if dep not in ids]
            if missing:
                raise ValueError(f"{step.id} 依赖不存在的步骤 {missing}")
        rest = {step.id: set(step.depends_on) for step in self.steps}
        while rest:
            ready = [sid for sid, deps in rest.items() if not deps]
            if not ready:
                raise ValueError("依赖成环，计划不可执行")
            for sid in ready:
                rest.pop(sid)
            for deps in rest.values():
                deps.difference_update(ready)
        return self
```

执行器按拓扑序取第一个未完成步骤，验收失败就触发一次 replan：

```python
for _ in range(MAX_STEPS + MAX_REPLANS + 1):
    pending = [step for step in topo(plan) if step.id not in done]
    if not pending:
        return executed, replans, "success"
    step = pending[0]
    result = TOOLS[step.tool]()
    if result["ok"] and ACCEPT[step.tool](result["data"]):
        done[step.id] = result
        executed.append(step.id)
        continue
    if replans >= MAX_REPLANS:
        return executed, replans, "failed"
    replans += 1
    content = ask(llm, [system("只输出替代步骤的 JSON。"), user(prompt)], stats, "replan")
    replacements = [PlanStep.model_validate(item) for item in json.loads(content)["steps"]]
    plan = patch(plan, step.id, replacements)
```

ReAct 则是一个标准的“模型 → 工具 → 回填”循环：

```python
for _ in range(MAX_STEPS):
    response = llm.chat(messages, tools=TOOL_SCHEMAS)
    if not response.tool_calls:
        return {"answer": response.content, "status": "success", ...}
    messages.append(assistant(response.content, response.tool_calls))
    for call in response.tool_calls:
        result = TOOLS[call.name]()
        messages.append(tool_message(call, result))
```

运行结果的关键部分：

```text
ReAct                    7      2029         6  success
Plan-and-Solve           3       408         6  success
计划模式重规划 1 次，执行步骤 ['s1', 's2', 's3b', 's4', 's5']
```

同一个任务、同样的工具调用次数（6 次），ReAct 用了 7 次模型调用、2029 token；Plan-and-Solve 用了 3 次、408 token。差距主要来自 ReAct 每一轮都要把不断变长的历史重新发给模型。

## 4. 逐行拆解

**第一，`done_when` 必须由代码兑现。** 计划里的 `done_when` 是给模型看的，真正的验收在 `ACCEPT` 字典：

```python
ACCEPT = {
    "screen": lambda data: data.get("qualified", 0) >= 2,
    ...
}
```

这不是重复劳动。自然语言验收标准是“意图”，谓词才是“契约”。没有谓词，执行器只能假装验收，失败永远不触发。

**第二，拓扑排序保证“依赖先做”。** `topo()` 反复找出没有未完成依赖的步骤，逐个取出，并把已取出的 id 从其他步骤的依赖里删掉。如果某一轮一个都找不到，说明有环；`Plan` 校验阶段已经先拦一次。

**第三，重规划要打补丁，不要重开。** `patch()` 做两件事：移除失败步骤；把任何依赖失败步骤的下游改成依赖全部替代步骤。它不碰 `done` 里的结果，所以 s1、s2 不会重跑，也不会重复发 JD。

**第四，token 账要记在调用点。** `ask()` 每次调用后累加 `usage.total_tokens`，ReAct 循环也单独累加。不要用“字符数除以 4”事后估算，真实账单以模型返回的 usage 为准；MockChatModel 的 usage 是估算值，但口径一致，足够做模式对比。

**第五，ReAct 的“灵活”是有代价的。** 它每一步都重新看全量历史，决策质量随上下文变长而下降，token 也线性增长。本章的 ReAct 第 3 步发现只剩 1 人、第 4 步补渠道，确实灵活；但真实模型很可能在第 12 轮忘记前面的结论——这正是第 1 节事故的由来。

**第六，终止条件要写在代码里，不要写在 Prompt 里。** “最多想 8 步”“最多重规划 1 次”“超过 8000 token 就停”都是循环里的 `if`，不是系统提示里的一句“请勿无限循环”。模型不执行预算，执行器才执行。

> ⚠️ **生产提醒**：计划要存版本。每次 replan 都保留旧计划和补丁记录（谁改的、为什么改、改了哪几步），否则线上出问题时无法回答“为什么最终跑了这 5 步”。计划 diff 比最终答案更有复盘价值。

## 5. 实验

**实验一：打乱依赖。** 把 s4 的 `depends_on` 改成 `["s1"]`，再运行。你会发现 s4 在 s3 之前执行，面试安排在没有筛选结果的情况下发生。观察拓扑序如何变化，以及最终 `booked` 是否仍然为 2。

**实验二：让重规划失败。** 把 `REPLAN_JSON` 里的 `qualified` 改成 1，或把 `MAX_REPLANS` 改成 0。前者会让 s3b 也不达标，后者直接不重规划；两种都会让状态变成 `failed`，但失败步骤和已执行列表不同。

**实验三：压低预算。** 把 `TOKEN_BUDGET` 改成 100，再运行。ReAct 会在第一轮之后就被预算截断，Plan 模式会在 plan 调用后停。观察状态字段是 `budget_exhausted` 而不是 `success`，这比抛异常更适合上层降级。

**实验四：删掉环检测。** 把 s5 的 `depends_on` 改成 `["s4", "s5"]`（自依赖），再运行。`Plan` 校验会抛“依赖成环”，整个计划在第一个工具调用之前就被拒绝。把校验去掉，`topo()` 会陷入死循环——这就是为什么校验必须在执行前。

## 6. 工程化视角

第一，**计划是产物，不是中间变量**。把 `Plan` 存进数据库或对象存储，带版本、创建人、任务 id。这样做有三个好处：可审计、可回放、可人工修改后重跑。

第二，**计划要有人审**。招聘、调薪、裁员这类任务，Plan 生成后应先给 HR 看一遍，确认步骤和验收标准再执行。第 12 章把审批做成可中断、可恢复的 `ApprovalGate`。

第三，**DAG 可以并行**。本章按拓扑序串行执行，是为了日志清楚。真实 DAG 里，无依赖的只读步骤可以并行；写步骤仍要串行并带幂等键，否则无法保证副作用顺序。

第四，**重规划要有上限和降级**。模型可能连续给出不可执行的替代步骤。超过 `MAX_REPLANS` 后应转人工，而不是继续烧 token；降级结果至少包含“已完成步骤 + 失败原因 + 人工建议动作”。

第五，**用评测证明规划变好**。规划质量可以量化：计划可执行率、首次验收通过率、平均重规划次数、单任务 token、人工接管率。第 15 章会用 Golden Case 和回归门禁把这些指标跑起来。

## 7. 常见坑

**坑一：把 CoT 当 Planning。** 现象是模型输出一大段“首先、其次、最后”，代码却无法执行。原因是只有文本，没有结构和工具绑定。解法是强制 JSON Schema，并校验步骤字段。

**坑二：计划粒度太细。** 现象是 20 步里 15 步都是“查一下”。原因是没有按目标拆，而是按工具调用拆。解法是按“可验收的目标”拆步，一步可以包含多个工具调用，但必须有明确的完成条件。

**坑三：失败就重规划整单。** 现象是已经发出去的 JD 又发一遍，面试重复安排。原因是 replan 没保留 `done`，或把整个计划重新生成。解法是只替换失败步骤，下游改依赖，已完成步骤不重跑。

**坑四：`done_when` 写成形容词。** 现象是“质量达标”“HR 满意”无法判断，执行器只能默认通过。解法是每条验收标准都能翻译成布尔表达式，翻译不了说明目标没想清楚。

**坑五：把 token 预算写成 Prompt。** 现象是模型说“我会注意预算”，然后继续调 20 次。原因是预算没有落到代码的循环条件里。解法是 `if stats["tokens"] > TOKEN_BUDGET: return ...`。

**坑六：忽略工具白名单。** 现象是模型编了一个不存在的工具名，执行时 `KeyError`。原因是直接 `TOOLS[step.tool]` 而没有校验。解法是 `Plan` 校验 `step.tool in TOOLS`，执行器再兜一层。

## 8. 练习

**练习一（基础）**：给计划加一个 `budget_tokens` 字段，每步执行后检查累计 token，超过就返回 `budget_exhausted`。要求 `Plan` 校验 `budget_tokens` 不超过全局上限。

**练习二（基础）**：让 `replan` 只重写失败步骤。提示：替代步骤应继承失败步骤的依赖，下游依赖自动改指。

**练习三（进阶）**：比较两种模式的 token 成本：把 ReAct 的 `MAX_STEPS` 从 8 改成 4，观察它是否还能完成任务；再把 Plan 的 `MAX_REPLANS` 改成 0，观察失败路径。

**练习四（进阶）**：给 `Plan` 增加“同一工具最多出现 N 次”的校验，防止模型把“搜索候选人”重复写 5 遍。想一想：这个限制应该放在 Schema 校验里，还是执行器里？

<details><summary>参考答案</summary>

练习一在 `PlanStep` 之外给 `Plan` 加字段，并在执行循环里检查：

```python
class Plan(BaseModel):
    steps: list[PlanStep]
    budget_tokens: int = 8000

    @model_validator(mode="after")
    def check_budget(self):
        if self.budget_tokens > TOKEN_BUDGET:
            raise ValueError("计划预算超过全局上限")
        return self
```

执行器每步之后加：

```python
if stats["tokens"] > plan.budget_tokens:
    return executed, replans, "budget_exhausted"
```

练习二的替代步骤由模型给出，但代码要保证依赖不丢：

```python
def patch(plan, failed_id, replacements):
    failed = next(step for step in plan.steps if step.id == failed_id)
    for item in replacements:
        if not item.depends_on:
            item.depends_on = list(failed.depends_on)
    steps = [step for step in plan.steps if step.id != failed_id]
    for step in steps:
        if failed_id in step.depends_on:
            step.depends_on = [dep for dep in step.depends_on if dep != failed_id]
            step.depends_on += [item.id for item in replacements]
    return Plan(steps=steps + replacements)
```

练习三的关键观察：ReAct 在 4 步内只能完成 HC、JD、筛选、补渠道，到不了 offer；Plan 在 `MAX_REPLANS=0` 时 s3 失败即终止，`executed` 只有 `["s1", "s2"]`。两种失败都应该返回结构化状态，而不是抛异常。

练习四建议放在 `Plan` 校验里，因为它和工具白名单一样属于“计划合法性”：

```python
from collections import Counter

counts = Counter(step.tool for step in self.steps)
if max(counts.values(), default=0) > 3:
    raise ValueError(f"同一工具重复过多：{counts}")
```

执行器里再加一层运行时限制也可以，但校验阶段拦掉更便宜，也更容易给模型明确的错误信息。

</details>

## 9. 小结与下一章

1. CoT 改善单次推理，Planning 提供可执行、可验收、可修正的结构。
2. ReAct 灵活但贵；Plan-and-Solve 多一次规划调用，换来更短上下文和更低 token。
3. 计划要过校验、按依赖执行、失败只补失败分支，并用代码守住预算与终止条件。

计划再漂亮，入职、审批、发薪这类流程仍然需要确定性的状态机：谁在什么状态、什么事件能触发转移、失败了怎么补偿。下一章我们把“确定的事”交给代码，把“不确定的判断”留给模型。

---

## 10. 附：LangChain 版关键实现

> 本章实际运行的 demo 使用 **StateGraph 的 plan → execute → replan**，完整代码见 `code/ch04_planning.py`。下面只保留骨架，方便你对照前面的原理示意阅读。

```python
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

graph = StateGraph(PlanState)
graph.add_node("plan", plan_node)
graph.add_node("execute", execute_node)
graph.add_node("replan", replan_node)
graph.add_edge(START, "plan")
graph.add_edge("plan", "execute")
graph.add_conditional_edges("execute", route_after_execute, {"replan": "replan", END: END})
graph.add_edge("replan", "execute")
app = graph.compile()
```

| 本章概念 | LangChain / LangGraph 对应物 |
| --- | --- |
| ReAct | `create_agent` |
| 计划执行 | `StateGraph` |
| 重规划 | `Command` / 条件边 |

> 🧩 **怎么读**：先看正文理解“为什么需要这一层”，再看上面的骨架理解“框架怎么表达这一层”，最后打开 `code/ch04_planning.py` 看完整实现与断言。面试时两条线都要能讲：原理线 + 框架线。
