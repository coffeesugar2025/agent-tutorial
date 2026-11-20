# 14 · Human-in-the-loop：该停的地方必须停下来等人

## 14.1 本章目标

1. 用 `interrupt()` 在"高危动作"前挂起，用 `Command(resume=...)` 续跑；
2. 理解 checkpointer 在这里的作用（挂起期间进程可以退出）；
3. 三种人的回答：approve / edit / reject；
4. 四道校验：身份、时效、幂等、审计。

跑法：`python ch14_hitl/main.py`

## 14.2 红线动作清单

HR 场景里**一律不许自动执行**的动作：

- 发 offer / 调薪 / 定级
- 批量导出个人信息
- 开除、调岗、绩效结论
- 对外发送任何口径文件

判断标准：**不可逆 + 影响一个人 / 影响一笔钱 / 影响合规** → 必须 HITL。

## 14.3 三件套

```python
def gate_node(state):
    decision = interrupt({
        "action": "send_offer",
        "risk": "high",
        "reason": "月薪 28,000 超出带宽 22-25K，需薪酬特批 + HRD 签批",
        "content": state["content"],
        "options": ["approve", "reject", "edit"],
        "sla_hours": 24,
        "created_at": time.time(),
    })
    return {"approval": decision}
```

`interrupt()` 抛出一个特殊信号，图**停在这里**，状态由 checkpointer 保住。外面的人拿到的是一个**结构化的问题**（不是一句话）：

```
  图已挂起：next=('gate',)
  等人批准的内容：月薪 28,000 超出带宽 22-25K，需薪酬特批 + HRD 签批
```

★ 给审批人的 payload 必须含：**要批什么（action）、为什么、风险等级、原文、可选项、时限**。只丢一句"请确认"，等于把责任推回给系统。

## 14.4 续跑

```python
app.invoke(Command(resume={"decision": "approve", "approver": "薪酬负责人-王强"}), cfg)
```

实测三种：

```
  ① 直接批准
    结果：sent=True，内容：【offer】K1001：月薪 28,000…
    轨迹：['已生成 offer 草稿', '已发送（审批人 薪酬负责人-王强）']

  ② 编辑后批准
    结果：sent=True，内容：【offer】K1002：月薪 25,000（已压回带宽内）…

  ③ 拒绝
    结果：sent=None
    轨迹：['已生成 offer 草稿']
```

注意 ② 的价值：**人改内容，流程不重跑**。这是真实审批最需要的——领导把 28K 改成 25K，系统应该直接用新内容往下走，而不是让 Agent 重新生成一遍。

## 14.5 四道校验（必须有）

```python
def validate(state, ap):
    if ap.get("approver") == state.get("applicant"):     return "审批人不能是申请人本人"
    if waited > 24 * 3600:                               return "审批超时，自动失效"
    if 超带宽 and "HRD" not in ap["approver"]:            return "超带宽必须 HRD 签批"
    return None
```

实测：

```
    申请人自批    → ⛔ 审批人不能是申请人本人
    超时未批     → ⛔ 审批超时 30h > 24h，自动失效
    越权批准     → ⛔ 超带宽 offer 必须 HRD 签批
    合规批准     → ✅ 通过
```

四道校验对应四个真实事故：

| 校验 | 防的事故 |
|---|---|
| 身份 | 自己批自己（最常见的流程漏洞） |
| 时效 | 挂起永远不处理，任务永远"进行中" |
| 幂等 | 同一个审批点批两次，发了两个 offer |
| 审计 | 出了问题查不到"谁批的、批的哪一版" |

## 14.6 checkpointer 为什么是前提

`interrupt()` 之后图的状态必须能被**另一个进程**读出来——审批人可能在手机上点，可能在两天后点。`InMemorySaver` 只适合教学；生产用 `SqliteSaver` 或 Postgres saver：

```python
from langgraph.checkpoint.sqlite import SqliteSaver
graph = builder.compile(checkpointer=SqliteSaver.from_conn_string("hitl.db"))
```

## 14.7 别把 HITL 做成"确认弹窗"

★ **HITL 的本质不是加个按钮，是把不可逆的动作拆成三步：生成 → 人审 → 执行。**

- "生成"阶段可以自动；"执行"阶段必须由人触发；
- 人审要看到"要批的东西本身"，不是"要不要继续"；
- 执行阶段要能带上人的修改，不要重跑生成。

## 14.8 常见坑

1. **`interrupt()` 放在工具里**：工具调用是模型驱动的，挂起后模型会再试一次。放在**图节点**里。
2. **没配 checkpointer**：`interrupt()` 直接报错（没有地方存状态）。
3. **`thread_id` 冲突**：同一 thread 两次中断会串。用业务单号 + 审批点做 thread_id。
4. **resume 的 payload 结构变了**：上一版存的是 `{"ok": true}`，新版要 `{"decision": ...}`，恢复时报 KeyError。payload 结构也要版本化。
5. **审批人看不到原文**：只给一句"是否批准"，人只能凭感觉点——这是最坏的 HITL。

## 14.9 自检清单

- [ ] 能列出 HR 场景的 HITL 红线动作
- [ ] 知道 `interrupt` + `Command(resume)` + checkpointer 三者的关系
- [ ] 能说出四道校验各防什么事故
- [ ] 理解"生成/人审/执行"三段式

## 14.10 练习

1. 给 gate 加第二个 `interrupt`（财务复核），跑通两级审批。
2. 把 `InMemorySaver` 换成 `SqliteSaver`，杀掉进程后再 `Command(resume)` 续跑。
3. 给审批加"超时自动转上级"分支，观察 `next` 的变化。
