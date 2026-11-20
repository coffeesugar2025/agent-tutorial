---
title: "05 | Workflow 与状态机：确定的事交给代码"
slug: "workflow"
order: 5
part: "单 Agent 核心"
minutes: 60
difficulty: "进阶"
prerequisites: ["04"]
summary: "把入职流程做成可恢复的状态机：守卫、幂等、checkpoint 与补偿。"
---
> 🧩 **框架说明**：本章 demo 基于 **LangChain 1.x + LangGraph 1.x**，核心 API：`StateGraph`、`InMemorySaver`、`Command`。正文中的代码若标注“原理示意”（包括旧版 MockLLM / 手写循环片段），用于解释内部机制，不是最终运行代码；完整可运行代码见 `code/ch05_workflow.py`。


## 0. 本章你会得到什么

1. 分清哪些环节该让模型判断，哪些必须由代码保证。
2. 用状态、事件、转移、守卫、动作描述入职流程，并拒绝非法转移。
3. 把状态写成 JSON checkpoint，模拟崩溃后从断点恢复。
4. 理解“幂等属于副作用系统”，而不是流程内存。
5. 给终止分支设计补偿动作，并知道补偿本身也要幂等。

## 1. 场景

林晓是 Acme 科技的候选人，12 月 1 日入职，岗位是后端工程师。HR 赵敏要在她来之前完成六件事：收齐材料、签合同、开账号、发设备、确认 Day 1 清单、进入试用期。

11 月 28 日，赵敏发现林晓的离职证明还没上传。按制度，缺离职证明不能签劳动合同。如果系统只会“下一步”，它会把合同签了，等法务发现再回滚；如果系统是状态机，它会在“签约”这个转移上直接拦住，并告诉赵敏缺什么。

去年还出过两次事故。一次是赵敏休假，新员工第一天到公司没有电脑，因为流程卡在“等 HR 点下一步”；一次是王浩背调未通过，但工牌已经做好、账号已经开通，人没入职，门禁却还能刷。前者是**流程不能恢复**，后者是**终止没有补偿**。

入职流程的特点是：步骤确定、顺序确定、责任明确、错了代价高。这类问题不该交给模型即兴发挥，而应该交给状态机。模型可以帮你解释制度、生成清单、回答员工问题，但“能不能签约”“账号开没开”必须由代码说了算。

> 💡 **小白提示**：状态机（Finite State Machine，FSM）就是“有限个状态 + 状态之间允许的转移”。红绿灯只有红、黄、绿三个状态，闯红灯不是“另一个状态”，而是非法转移。入职流程同理。

## 2. 概念

### 2.1 五个词：状态、事件、转移、守卫、动作

- **状态（State）**：流程当前在哪。入职流程有 `CREATED`、`DOCS_VERIFIED`、`CONTRACT_SIGNED`、`ACCOUNTS_READY`、`EQUIPMENT_READY`、`DAY1_READY`、`PROBATION`，外加终止态 `TERMINATED`。
- **事件（Event）**：外界发生了什么，例如 `VERIFY_DOCS`、`SIGN_CONTRACT`、`FAIL_BACKGROUND_CHECK`。
- **转移（Transition）**：在某个状态下收到某个事件，允许去哪个新状态。
- **守卫（Guard）**：转移的前置条件。缺离职证明时，`SIGN_CONTRACT` 的守卫返回失败，状态不变。
- **动作（Action）**：转移真正产生的副作用，例如开通账号、发设备、回收权限。

把五者放在一起，一条转移就是：`(当前状态, 事件) → 守卫 → 动作 → 新状态`。

```text
                    ┌──────────────────────────────┐
                    │            CREATED           │
                    └──────────────┬───────────────┘
                          VERIFY_DOCS │ guard: 材料齐全
                                   ▼
                    ┌──────────────────────────────┐
                    │        DOCS_VERIFIED         │
                    └───────┬──────────────┬───────┘
              SIGN_CONTRACT │              │ FAIL_BACKGROUND_CHECK
              guard: 离职证明│              ▼
                            ▼       ┌──────────────┐
                    ┌──────────────┐│  TERMINATED  │
                    │CONTRACT_SIGNED│└──────────────┘
                    └──────┬───────┘        ▲
         PROVISION_ACCOUNTS│                │ FAIL_BACKGROUND_CHECK
                           ▼                │（任一未完成状态）
                    ┌──────────────┐        │
                    │ACCOUNTS_READY├────────┘
                    └──────┬───────┘
         ASSIGN_EQUIPMENT  │
                           ▼
                    ┌────────────────┐
                    │EQUIPMENT_READY │
                    └──────┬─────────┘
              DAY1_CHECK   │ guard: 账号+设备+导师
                           ▼
                    ┌──────────────┐
                    │  DAY1_READY  │
                    └──────┬───────┘
         START_PROBATION   │
                           ▼
                    ┌──────────────┐
                    │  PROBATION   │
                    └──────────────┘
```

### 2.2 Workflow 与 Agent 的边界

| 问题 | 交给 Workflow | 交给 Agent |
| --- | --- | --- |
| 步骤是否固定 | 固定、可枚举 | 需要临场决定 |
| 失败后果 | 漏签合同、漏开权限 | 回答不够好、多问一句 |
| 输入 | 结构化事件 | 自然语言、模糊需求 |
| 验收 | 状态与字段可判定 | 需要人判断或评测 |
| 例子 | 签约、开账号、发薪 | 解释制度、生成 JD、安抚候选人 |

一个实用的判断方法是：**如果这件事做错了要上法庭、要赔钱、要道歉，就别让模型决定“做不做”，最多让它决定“怎么解释”。**

### 2.3 checkpoint：把状态写下来

流程不能只活在内存里。进程重启、机器宕机、HR 下班，状态都得还在。最小实现是每次成功转移后，把状态、材料、历史、动作结果写进一个 JSON 文件。

关键在写入方式：先写临时文件，再原子替换目标文件。直接覆盖原文件时，如果进程在写到一半崩溃，留下的是半个 JSON，恢复时连状态都读不出来。

```text
时间轴：
动作执行成功 ──▶ 写 checkpoint ──▶ 返回成功
                     │
                     └─ 若在这里崩溃：动作已发生，状态没保存
                        恢复后重放同一事件，必须靠幂等避免重复副作用
```

### 2.4 崩溃恢复与幂等

看上面那条时间轴：动作（开账号）已经成功，checkpoint 还没落盘，进程挂了。恢复后状态仍是 `CONTRACT_SIGNED`，系统会再次执行 `PROVISION_ACCOUNTS`。

如果幂等只做在流程内存里，这次重放会再开四个账号。正确做法是让**副作用系统**自己幂等：账号服务收到“给 C001 开域账号”，发现已存在就返回“已存在”，不重复创建。

本章用一个 `AccountService` 模拟外部账号系统。它有自己的字典，不依赖流程的 checkpoint。流程重放时，`ensure()` 返回 `created=[]`、`existing=[四个系统]`，状态正常推进，账号没有翻倍。

> ⚠️ **生产提醒**：checkpoint 只保证“流程状态不丢”，不保证“副作用不重复”。副作用必须由下游系统的唯一约束或幂等键兜底，两者缺一不可。

### 2.5 补偿：终止也要收尾

正常流程往前走，异常流程要往回退。背调未通过在 `ACCOUNTS_READY` 被发现时，不能只把状态改成 `TERMINATED`，还要回收账号、取消工牌、通知 IT 和行政。这类“撤销已发生动作”的操作叫补偿（compensation）。

补偿有三个要求：

1. **可重试**：回收接口必须幂等，网络超时会重试。
2. **可审计**：谁在什么时候回收了什么，要留记录。
3. **有边界**：已发的工资、已签的合同不能假装“撤销”，需要人工介入。

### 2.6 超时与人工节点

状态机最怕“卡住”：流程停在 `DOCS_VERIFIED` 等 HR 上传材料，HR 休假一周，没人知道。生产上要给每个等待态设 SLA，超时发提醒或升级；人工节点要能看到“在等谁、等了多久、下一步是什么”。

本章不实现定时器，但把等待信息写进 checkpoint，读者可以在此基础上加 `deadline` 字段和扫描任务。

## 3. 动手

> 🧩 **读法**：第 3 节的代码用于解释原理；本章实际运行的 demo 已改为 LangChain 版，完整代码见章末“LangChain 版关键实现”与 `code/` 对应脚本。


运行：

```powershell
python code/ch05_workflow.py
```

状态和事件用 `StrEnum` 定义。为了篇幅，脚本用了函数式写法，等价于逐个声明 `CREATED = "CREATED"`：

```python
State = StrEnum("State", {name: name for name in [
    "CREATED", "DOCS_VERIFIED", "CONTRACT_SIGNED", "ACCOUNTS_READY",
    "EQUIPMENT_READY", "DAY1_READY", "PROBATION", "TERMINATED"]})
Event = StrEnum("Event", {name: name for name in [
    "VERIFY_DOCS", "SIGN_CONTRACT", "PROVISION_ACCOUNTS", "ASSIGN_EQUIPMENT",
    "DAY1_CHECK", "START_PROBATION", "FAIL_BACKGROUND_CHECK"]})
```

转移表是纯数据，守卫和动作只是名字：

```python
TRANSITIONS: dict[tuple[State, Event], Transition] = {
    (State.CREATED, Event.VERIFY_DOCS): Transition(State.DOCS_VERIFIED, "verify_docs", "docs_complete"),
    (State.DOCS_VERIFIED, Event.SIGN_CONTRACT): Transition(State.CONTRACT_SIGNED, "sign_contract", "has_resignation"),
    (State.CONTRACT_SIGNED, Event.PROVISION_ACCOUNTS): Transition(State.ACCOUNTS_READY, "provision_accounts"),
    (State.ACCOUNTS_READY, Event.ASSIGN_EQUIPMENT): Transition(State.EQUIPMENT_READY, "assign_equipment"),
    (State.EQUIPMENT_READY, Event.DAY1_CHECK): Transition(State.DAY1_READY, "day1_check", "day1_ready"),
    (State.DAY1_READY, Event.START_PROBATION): Transition(State.PROBATION, "start_probation"),
}
for state in (State.DOCS_VERIFIED, State.CONTRACT_SIGNED, State.ACCOUNTS_READY, State.EQUIPMENT_READY, State.DAY1_READY):
    TRANSITIONS[(state, Event.FAIL_BACKGROUND_CHECK)] = Transition(State.TERMINATED, "terminate")
```

执行入口把守卫、动作、状态更新、checkpoint 串起来：

```python
def apply(self, event: Event) -> dict:
    transition = TRANSITIONS.get((self.state, event))
    if transition is None:
        allowed = [item.value for (state, item) in TRANSITIONS if state == self.state]
        raise IllegalTransition(f"{self.state} 不允许 {event}；可执行 {allowed or '无（终态）'}")
    if transition.guard:
        ok, reason = GUARDS[transition.guard](self)
        if not ok:
            raise GuardFailed(f"{transition.guard} 未通过：{reason}")
    result = ACTIONS[transition.action](self) if transition.action else {}
    previous = self.state
    self.state = transition.target
    self.history.append({"from": previous.value, "event": event.value, "to": self.state.value, "result": result})
    self.effects[event.value] = result
    if event is self.crash_on:
        raise SimulatedCrash(f"{event} 动作已完成，checkpoint 尚未落盘")
    self.save()
    return result
```

checkpoint 的写入是“临时文件 + 原子替换”，恢复时重新构造对象：

```python
def save(self) -> None:
    payload = {"employee_id": self.employee_id, "name": self.name, "join_date": self.join_date,
               "state": self.state.value, "docs": self.docs, "mentor": self.mentor,
               "history": self.history, "effects": self.effects}
    tmp = self.checkpoint.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(self.checkpoint)
```

运行输出会依次展示：缺离职证明被拒、补交后签约、开通账号后崩溃、从 `CONTRACT_SIGNED` 恢复且账号不重复、终态与跳步被拒、背调未通过回收账号。

```text
拒绝：has_resignation 未通过：缺少离职证明，不能签署劳动合同
崩溃：PROVISION_ACCOUNTS 动作已完成，checkpoint 尚未落盘
从 CONTRACT_SIGNED 恢复；新建=[] 已存在=['域账号', '企业邮箱', 'IM', 'VPN']
拒绝：PROBATION 不允许 SIGN_CONTRACT；可执行 无（终态）
状态=TERMINATED 回收=['域账号', '企业邮箱', 'IM', 'VPN'] 离职工单=OFF-C003
```

## 4. 逐行拆解

**第一，转移表是数据，不是 `if/elif`。** 把 `(状态, 事件) → 转移` 写进字典后，非法转移的报错可以自动列出“当前状态允许哪些事件”，测试也可以遍历整张表。新增一条分支只改数据，不改执行逻辑。

**第二，守卫必须在动作之前。** `SIGN_CONTRACT` 的守卫检查离职证明；守卫失败时状态不变，也不会产生合同编号。如果先签约再检查，回滚成本会高得多。守卫只做只读判断，不要在里面发消息、写数据库。

**第三，崩溃点要卡在“动作之后、save 之前”。** 脚本用 `crash_on` 精确模拟这个窗口。这个窗口是分布式系统最经典的故障：副作用已经发生，但协调者不知道。恢复逻辑不能假设“没保存就等于没发生”，只能靠下游幂等。

**第四，`load()` 恢复的是状态，不是对象。** 它从 JSON 读回员工、状态、材料、历史、动作结果和导师，再绑定同一个 `AccountService`。真实系统里，账号服务是远程的，恢复后重新调用即可；本章用一个共享的内存对象模拟。

**第五，非法转移要给出“能做什么”。** 报错不只说“不允许”，还列出当前状态可执行的事件。这对 HR 和排障都重要：用户知道下一步该点哪个按钮，工程师知道是状态错了还是事件发错了。

**第六，终止是状态，不是删除。** `TERMINATED` 保留完整历史、回收记录和离职工单号。删除记录会让审计断链，也无法回答“这个人到底走到哪一步”。终止态没有出边，任何事件都会被拒绝。

> ⚠️ **生产提醒**：checkpoint 要带 schema 版本号和乐观锁版本号。流程代码升级后，旧 checkpoint 可能缺字段；两个 HR 同时操作同一员工时，后写入的会覆盖先写入的。用 `version` 字段做 CAS，比“最后写入者赢”安全得多。

## 5. 实验

**实验一：拿掉离职证明守卫。** 在 `TRANSITIONS` 里把 `SIGN_CONTRACT` 的 `guard` 改成空字符串，再运行。合同会在缺材料的情况下签成功，说明守卫不是装饰，是唯一的拦截点。

**实验二：换一个崩溃点。** 把 `lin.crash_on` 改成 `Event.ASSIGN_EQUIPMENT`，观察 checkpoint 停在 `ACCOUNTS_READY`，恢复后会重新发设备。设备发放如果也有唯一资产号，重放就是安全的；如果没有，就会发出两台电脑。

**实验三：让补偿也重放。** 在王浩的 `FAIL_BACKGROUND_CHECK` 之后再调用一次 `revoke`，观察它返回空列表而不是报错。补偿接口必须能接受“已经回收过”的状态。

**实验四：加一个超时字段。** 给 `OnboardingWorkflow` 加 `deadline`，在 `save()` 里写入，再写一个扫描函数：超过 3 个工作日仍在 `DOCS_VERIFIED` 就输出提醒。先不接定时器，只验证判断逻辑。

## 6. 工程化视角

第一，**checkpoint 换成数据库**。JSON 文件适合教学，生产要用带事务的存储：SQLite 起步，PostgreSQL 更稳。状态更新、历史写入、outbox 消息要在同一个事务里，避免“状态变了但消息没发”。

第二，**用 outbox 解耦副作用**。开账号、发设备、发邮件都通过 outbox 表异步执行，流程只负责把“要做什么”写进表里。消费者幂等，失败重试，死信人工处理。

第三，**多实例要加锁**。同一员工同时收到两个事件时，用行锁或乐观锁串行化。没有锁，两个进程可能都从 `CONTRACT_SIGNED` 读到状态，各自开通一次账号。

第四，**人工节点要可见**。审批、补材料、背调都是等待态。生产上要有待办列表、SLA、升级规则和“当前卡在谁”的看板；否则流程再正确，人也不知道该干什么。

第五，**考虑成熟引擎**。流程跨部门、跨天、需要定时器和可视化编排时，Temporal、Camunda、Step Functions 能省很多基础设施代码。手写一遍是为了知道引擎内部在做什么。

## 7. 常见坑

**坑一：状态只存在内存。** 现象是服务重启后所有流程回到起点，或者 HR 刷新页面就丢了进度。原因是没有 checkpoint。解法是每次成功转移后持久化，并在启动时按 id 恢复。

**坑二：先保存状态，再执行动作。** 现象是 checkpoint 显示“账号已开通”，实际调用失败。原因是顺序反了。解法是“动作成功 → 保存状态”，并接受保存失败的窗口，用幂等兜底。

**坑三：把守卫写成动作里的 `if`。** 现象是签约动作执行到一半发现缺材料，合同编号已经生成。原因是校验和副作用混在一起。解法是把只读校验提到守卫，动作只做写入。

**坑四：终止态还能收到事件。** 现象是已经终止的流程又被 `START_PROBATION` 推进了。原因是转移表没有限制终态。解法是终态不定义任何出边，`apply()` 对未知转移统一报错。

**坑五：补偿不幂等。** 现象是重试回收账号时，第二次调用报“账号不存在”，整个补偿事务失败。原因是 `revoke` 把“不存在”当异常。解法是回收接口对已删除资源返回成功，并记录实际删除数量。

**坑六：让模型决定确定性步骤。** 现象是模型觉得“离职证明可以后补”，于是跳过了守卫。原因是把签约权交给了 Prompt。解法是模型只能提议，`apply()` 只能接受合法事件，守卫在代码里。

## 8. 练习

**练习一（基础）**：给终止分支加设备补偿：如果 `TERMINATED` 时已经发过设备，调用资产服务回收笔记本和工牌，并把结果写进 `effects`。要求回收接口幂等。

**练习二（基础）**：把 JSON checkpoint 换成 SQLite，保持 `save()`、`load()` 的接口不变。提示：一张 `workflows` 表存状态 JSON，一张 `events` 表存历史；或者先用单表把 JSON 存进 `TEXT` 字段。

**练习三（进阶）**：给 `DOCS_VERIFIED` 加 SLA：超过 3 个工作日没有签约，产生一条提醒事件 `SLA_BREACH`，但不改变状态。想一想：提醒应该由谁发、发几次、如何避免重复提醒？

**练习四（进阶）**：给 `apply()` 加乐观锁：checkpoint 存 `version`，每次成功转移加 1；调用方带版本号，不一致就拒绝。说明这能防哪两类并发问题。

<details><summary>参考答案</summary>

练习一在 `_terminate` 里判断是否发过设备：

```python
def _terminate(wf):
    revoked = wf.accounts.revoke(wf.employee_id)
    assets = []
    if "ASSIGN_EQUIPMENT" in wf.effects:
        assets = wf.assets.revoke(wf.employee_id)  # 资产服务同样要幂等
    return {"reason": "背景调查未通过", "revoked": revoked,
            "assets": assets, "offboarding_ticket": f"OFF-{wf.employee_id}"}
```

练习二的关键是保持接口不变，内部换存储：

```python
class SqliteCheckpoint:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.execute("CREATE TABLE IF NOT EXISTS workflows (id TEXT PRIMARY KEY, payload TEXT)")

    def save(self, employee_id: str, payload: dict) -> None:
        self.conn.execute("INSERT OR REPLACE INTO workflows VALUES (?, ?)",
                          (employee_id, json.dumps(payload, ensure_ascii=False)))
        self.conn.commit()

    def load(self, employee_id: str) -> dict | None:
        row = self.conn.execute("SELECT payload FROM workflows WHERE id = ?", (employee_id,)).fetchone()
        return json.loads(row[0]) if row else None
```

练习三的提醒应该由独立的扫描任务发，而不是在 `apply()` 里顺手发。扫描任务按 `deadline` 查询超时流程，用 `(employee_id, event, date)` 做幂等键，保证一天只提醒一次；连续超时可以升级给主管。

练习四的乐观锁防两类问题：一是两个 HR 同时点“下一步”，后提交的覆盖先提交的；二是恢复的旧进程带着过期状态写回，把新状态冲掉。调用方带 `expected_version`，SQL 更新时加 `WHERE version = ?`，影响行数为 0 就说明冲突，重新加载后再决定。

</details>

## 9. 小结与下一章

1. 步骤固定、后果严重的流程交给状态机；模型负责解释和提议，不负责放行。
2. 守卫在动作前，动作成功后再 checkpoint；崩溃窗口里的重复副作用靠下游幂等兜底。
3. 终止要有补偿，补偿要幂等、可审计；checkpoint 要版本化，恢复要能回答“卡在谁那里”。

流程有了记忆，助手也需要记忆。下一章我们给 Agent 加上会话、摘要、员工画像和业务事实，让它记住“张伟上周问过年假”，又不会把工资和病历到处乱说。

---

## 10. 附：LangChain 版关键实现

> 本章实际运行的 demo 使用 **StateGraph + InMemorySaver**，完整代码见 `code/ch05_workflow.py`。下面只保留骨架，方便你对照前面的原理示意阅读。

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

graph = StateGraph(OnboardingState)
graph.add_node("dispatch", dispatch)
graph.add_conditional_edges("dispatch", route, {...})
app = graph.compile(checkpointer=InMemorySaver())
config = {"configurable": {"thread_id": "onboarding-E1013"}}
app.invoke({"event": "VERIFY_DOCS"}, config)
state = app.get_state(config)   # 崩溃/重启后从这里恢复
```

| 本章概念 | LangChain / LangGraph 对应物 |
| --- | --- |
| 状态机 | `StateGraph` |
| 持久化 | `InMemorySaver` |
| 恢复 | `get_state` / `update_state` |

> 🧩 **怎么读**：先看正文理解“为什么需要这一层”，再看上面的骨架理解“框架怎么表达这一层”，最后打开 `code/ch05_workflow.py` 看完整实现与断言。面试时两条线都要能讲：原理线 + 框架线。
