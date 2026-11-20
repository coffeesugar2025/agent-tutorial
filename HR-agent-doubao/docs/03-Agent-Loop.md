# 03 · Agent Loop：从 `create_agent` 到自己搭图

## 3.1 本章目标

跑通一个真正的工具循环，并且**亲手拆开它**：

1. 先用 `create_agent` 一行拿到"能用"的 Agent；
2. 再用 `StateGraph(MessagesState) + ToolNode + tools_condition` 复现同一个循环——证明它不是黑魔法；
3. 最后加三种刹车，否则它一定会在某天转圈烧钱。

跑法：`python ch03_agent_loop/main.py`

## 3.2 一行版：`create_agent`

```python
from langchain.agents import create_agent

agent = create_agent(model, tools=[get_employee, get_leave_balance],
                     system_prompt="查员工数据必须调工具，不许估算。")
out = agent.invoke({"messages": [{"role": "user", "content": "张伟是哪个部门的？"}]})
```

一次调用内部发生了什么：

```
Human("张伟是哪个部门的？")
  → AIMessage(tool_calls=[{name: "get_employee", args: {"emp_id": "E1001"}}])
  → ToolMessage("张伟 / 技术中心 / 苏州 / P6 / active")
  → AIMessage("张伟在技术中心。")          ← 没有 tool_calls，循环结束
```

`create_agent` 帮你做了三件事：绑定工具 schema、跑循环、把消息按序放进 state。
**但它只内置了一种刹车：`recursion_limit`。**

## 3.3 手搭版：把循环画出来

```python
from langgraph.graph import StateGraph, END
from langgraph.graph import MessagesState
from langgraph.prebuilt import ToolNode, tools_condition

builder = StateGraph(MessagesState)
builder.add_node("model", model_node)        # 调模型
builder.add_node("tools", ToolNode(TOOLS))   # 执行工具
builder.add_edge(START, "model")
builder.add_conditional_edges("model", tools_condition,
                              {"tools": "tools", END: END})   # 有 tool_calls → 去工具
builder.add_edge("tools", "model")                            # 工具跑完 → 回模型
graph = builder.compile()
```

看懂这张图，你就理解了所有 Agent 框架的共同骨架：

- **节点**负责"干活"（调模型 / 跑工具）；
- **条件边**负责"往哪走"（`tools_condition` 只看一件事：最后一条 AIMessage 有没有 `tool_calls`）；
- **回边** `tools → model` 就是"循环"本身。

`messages` 用的是 `MessagesState` 预置的 reducer（`operator.add`）：每个节点返回的消息会**追加**而不是覆盖。这是 LangGraph 里最容易忘的一条：自定义 state 字段不加 `Annotated[list, operator.add]`，两个节点写同一个字段就会互相覆盖。

## 3.4 三种刹车（真跑出来的）

### ① 步数上限：`recursion_limit`

```python
graph.invoke(input, config={"recursion_limit": 4})
# → GraphRecursionError: Recursion limit of 4 reached without hitting a stop condition.
```

步数上限是**最硬**的刹车，也是最容易设错的。经验值：一次正常任务 ≈ 工具数 × 2 + 3。别按"怕它多想"设成 30，那等于没设。

### ② 重复动作检测

模型有时会拿同一个参数反复调同一个工具（"我觉得它没生效，再试一次"）。做法是在回边之前查一遍最近的动作：

```python
def guard(state):
    last = next((m for m in reversed(state["messages"]) if m.tool_calls), None)
    sig = [(c["name"], json.dumps(c["args"], sort_keys=True)) for c in last.tool_calls]
    ...  # 同一签名出现 >2 次 → 直接 END + 报"空转"
```

★ 这里有个真实的坑：`guard` 如果排在 `tools` **之后**，state 里最后一条是 `ToolMessage`（它没有 `tool_calls`），你得**反向找最近一条带 tool_calls 的 AIMessage** 才数得对。我第一次就写错在这。

### ③ 空转（模型不说话也不调工具）

最后一条 AIMessage 既没有 content 又没有 tool_calls → 继续跑只会空转，必须收口。

## 3.5 四道刹车的分工

| 刹车 | 管什么 | `create_agent` 有吗 |
|---|---|---|
| 步数（recursion_limit） | 不问"为什么"，只防跑飞 | ✅ 有 |
| token 预算 | 防单个任务烧光预算 | ❌ 要自己写 |
| 时长 | 防超时拖死上游 | ❌ 要自己写 |
| 重复动作 | 防"同样的错试 20 次" | ❌ 要自己写 |

实测输出：

```
  ① 步数上限（recursion_limit）：触发上限：GraphRecursionError →
     Recursion limit of 4 reached without hitting a stop condition.
  ② 重复动作检测（同一工具 + 同参数调太多次）：
     【中止】重复动作 get_position:{'position_id': 'P1001'} 超过 2 次，模型在空转
  ★ 四道刹车：步数、token、时长、重复动作。create_agent 只内置了第一个
```

## 3.6 常见坑

1. **`tools_condition` 认的是"最后一条消息"**。你在中间插了别的消息（比如日志节点往 messages 里塞了一条 Human），判断就会错。
2. **`ToolNode` 要求工具名对得上**。模型的 `tool_calls[].name` 必须和 `@tool` 的 name 完全一致，否则报"没有这个工具"。
3. **`MessagesState` 之外别乱加字段**。想加 `steps: int`，得声明 reducer，否则多个节点写同一个键会互相覆盖（第 05、06 章都踩过）。
4. **同步 `stream_events(version="v2")` 已不支持**（1.x）。要看事件流用 `astream_events(version="v2")`，第 18 章会写。
5. **以为 `create_agent` 会自动重试工具失败**。它不会。工具抛异常会变成 `ToolMessage(status="error")` 交回模型，模型可能自己改，也可能就此放弃。

## 3.7 自检清单

- [ ] 能画出 Human → AI(tool_calls) → Tool → AI 这条环
- [ ] 知道 `tools_condition` 依据什么做判断
- [ ] 能说出 `create_agent` 没给你哪三道刹车
- [ ] 知道为什么 `guard` 节点要反向找 AIMessage

## 3.8 练习

1. 把 `recursion_limit` 设成 2，观察正常任务会在哪一步被砍断（体会"设太小的代价"）。
2. 给图加一个 `log` 节点（只往一个自定义字段写"第几步"），练习给 state 加 reducer。
3. 用 `graph.stream(...)` 打印每个节点的输入输出，看清一次循环里 state 是怎么变的。
