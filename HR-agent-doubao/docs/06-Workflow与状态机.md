# 06 · Workflow 与状态机：该定死的地方别让模型发挥

## 6.1 本章目标

1. 把"审批流程"写成**转移表**（纯数据，可审查），而不是写进 prompt；
2. 用 `StateGraph` 一个节点推进一格，条件边做守卫；
3. 用 `InMemorySaver` 做 checkpointer，让"走到哪一步"可持久、可恢复；
4. 用版本号（CAS）解决并发，用"非法转移校验"堵住跳步。

跑法：`python ch06_workflow/main.py`

## 6.2 转移表

```python
STATES = ["草稿", "业务审批", "HRBP审批", "薪酬审批", "待发出", "已发出"]
TRANSITIONS = {
    ("草稿", "业务审批"):      {"guard": lambda p: bool(p.get("candidate_id")), "why": "缺候选人号"},
    ("业务审批", "HRBP审批"):  {"guard": lambda p: p.get("biz_ok") is True,     "why": "业务未通过"},
    ("HRBP审批", "薪酬审批"):  {"guard": lambda p: p.get("hb_ok") is True,      "why": "HRBP 未通过"},
    ("薪酬审批", "待发出"):    {"guard": lambda p: p.get("salary_ok") is True,  "why": "薪酬超带宽未特批"},
    ("待发出", "已发出"):      {"guard": lambda p: p.get("mail_sent") is True,  "why": "邮件未发出"},
}
```

注意这里**没有任何一条边能从"草稿"直达"薪酬审批"**。跳步不是靠 prompt 拦的，是这张表里根本不存在。

## 6.3 图的形状

```python
builder.add_node("transition", transition_node)
builder.add_edge(START, "transition")
builder.add_conditional_edges("transition", route, {"transition": "transition", END: END})
graph = builder.compile(checkpointer=InMemorySaver())
```

`transition_node` 每次只推一格：

```python
for (frm, to), rule in TRANSITIONS.items():
    if frm != cur: continue
    if not rule["guard"](payload):
        return {"log": ..., "stalled": True}      # 推不动
    row = store.cas(offer_id, version, to)         # 乐观锁
    return {"state": row["state"], "version": row["version"], "log": row["log"], "stalled": False}
```

## 6.4 第一个必须自己加的终止条件

`route` 最初只有"到终态就 END"：

```python
return END if state["state"] in TERMINAL else "transition"
```

结果：停在"业务审批"等人时，守卫一直不放行，图就**在同一个状态上无限自旋**，直到 `GraphRecursionError`。

正确的写法是加一个 `stalled` 标记：

```python
return END if (state["state"] in TERMINAL or state.get("stalled")) else "transition"
```

★ **工作流也需要终止条件。** 这一条很多人以为只有 Agent 循环才需要。

## 6.5 CAS：版本号解决并发

```python
def cas(self, offer_id, expect_version, new_state, patch=None):
    row = self.rows[offer_id]
    if new_state != row["state"] and (row["state"], new_state) not in TRANSITIONS:
        raise RuntimeError(f"非法转移：{row['state']} → {new_state}（SOP 里没有这条边）")
    if row["version"] != expect_version:
        raise RuntimeError(f"版本冲突：期望 v{expect_version}，实际 v{row['version']}")
    row["state"] = new_state
    row["payload"] = {**row["payload"], **(patch or {})}
    row["version"] += 1
    row["log"].append(f"{new_state}@v{row['version']}")
```

两个校验都必须有：

- **非法转移**：`cas` 是数据的最后一道门。没有它，"跳步"只是没人试过——一旦有人试，它真的会成功。我第一次写 demo 就漏了这个，结果"草稿 → 薪酬审批"静默成功，把后面的演示全带歪了。
- **版本冲突**：两个审批人同时点"通过"，只有一个能成功（实测：`期望 v10，实际 v11（有人先改了）`）。

外部系统写数据（审批人点通过、上传附件）走 `patch()`：只改 payload，不动状态，但**照样 bump 版本号**——因为版本号描述的是"这条记录被改过几次"，不是"状态走了几步"。

## 6.6 实测：一条 offer 的完整审计流水

```
  第 1 次推进后：业务审批@v2（停在'业务审批'等人）
  checkpoint 里的状态：业务审批 v2
  业务审批通过 → HRBP审批@v4
  HRBP 通过 → 薪酬审批@v6
  薪酬特批通过 → 待发出@v8
  offer 邮件发出 → 已发出@v10
  最终：已发出
  审计流水：['草稿@v1','业务审批@v2','HRBP审批@v4','薪酬审批@v6','待发出@v8','已发出@v10']
```

审计流水里版本号是跳着涨的（v2→v4）：因为每次外部审批写入也占一个版本。这正是真实系统该有的样子——**流水记录所有变更，不只是状态变更**。

## 6.7 checkpoint 的意义

```python
snapshot = graph.get_state({"configurable": {"thread_id": "K1001"}})
snapshot.values["state"]      # 现在停在哪一步
```

进程崩了、服务重启了、要人工介入——都能从 checkpoint 原地恢复。这是 LangGraph 相比"自己写状态机"最实际的优势：`InMemorySaver` 换成 `SqliteSaver` 就是生产可用的持久化。

## 6.8 模型在这套流程里的位置

```python
model.invoke("行，就这样吧")     # → {"intent":"approve","confidence":0.92}
model.invoke("给 C1024 生成 offer 通知邮件正文")   # → 文案
```

- **不该交给模型**：能不能跳步、能不能发出、走哪条分支；
- **可以交给模型**：这句用户话是什么意图、这段文案怎么写、这条异常怎么解释给用户。

这是 HR / 财务 / 审批类系统的通用架构：**模型做事件分类与状态内执行器，流程由代码保证。**

## 6.9 常见坑

1. **状态机没有终止条件** → 自旋（见 6.4）。
2. **把 SOP 写进 prompt** → 模型迟早跳步。SOP 必须是数据 + 校验。
3. **只校验版本、不校验边** → 非法转移静默成功。
4. **状态字段用自由文本** → `"已通过"` / `"通过"` / `"approved"` 三种写法混着来，没过两周就查不清。用枚举。
5. **忘记把外部写入也 bump 版本** → 图里的版本号永远落后，恢复时状态对不上。

## 6.10 自检清单

- [ ] 能说清 `TRANSITIONS` 与 prompt 的分工
- [ ] 知道工作流为什么也需要终止条件
- [ ] 能解释 CAS 两个校验各自防的什么
- [ ] 知道 checkpoint 在生产上换成什么

## 6.11 练习

1. 加一条"驳回"边（回到草稿并记录原因），跑完看审计流水是否完整。
2. 把 `InMemorySaver` 换成 `SqliteSaver`，杀进程后 `get_state` 恢复。
3. 把意图分类改成 `with_structured_output(Intent)`，比较两种写法在"含糊回答"上的稳定性。
