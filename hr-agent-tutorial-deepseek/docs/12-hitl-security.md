---
title: "12 | Human-in-the-loop 与权限：敏感操作必须有人签字"
slug: "hitl-security"
order: 12
part: "生产级可靠性"
minutes: 65
difficulty: "高阶"
prerequisites: ["11"]
summary: "用调薪场景实现审批中断、RBAC 与可验证的审计哈希链。"
---
> 🧩 **框架说明**：本章 demo 基于 **LangChain 1.x + LangGraph 1.x**，核心 API：`StateGraph`、`interrupt`、`Command`、`InMemorySaver`。正文中的代码若标注“原理示意”（包括旧版 MockLLM / 手写循环片段），用于解释内部机制，不是最终运行代码；完整可运行代码见 `code/ch12_hitl.py`。


## 0. 本章你会得到什么

学完这章，你应该能：

1. 说清 HITL（Human-in-the-loop，人在回路）与“弹窗点确认”的本质区别：前者是**状态持久化 + 职责分离 + 可追责**，后者只是一个 UI 动作。
2. 写出一个 `ApprovalGate`：在敏感工具执行前创建审批单、抛出 `Interrupted`、把 Agent 状态序列化成 JSON。
3. 用 `resume(approved=True/False)` 恢复执行，并保证被拒绝时一行数据都不改。
4. 用 RBAC（Role-Based Access Control，基于角色的访问控制）与最小权限，在工具层拦住越权请求。
5. 实现一条带 `prev_hash` 的 sha256 审计链，并演示“改一条就露馅”。

这章不再追求“让 Agent 更聪明”，而是回答一个更硬的问题：**谁有权让它动手？**

## 1. 场景

5 月 12 日，周二，上海。

技术部后端工程师张伟（工号 `E1001`，职级 P5，薪资档 `P5-2`）通过了晋升评审，技术总监徐明在评审会上口头同意：“张伟这次升 P6，薪资档调到 `P6-1`，6 月 1 日生效。”

会议结束后，HRBP 赵敏打开 HR 智能助理，输入一句话：

> 把张伟的薪资档从 P5-2 调到 P6-1，依据是晋升审批单 PR-2026-118。

如果这个助理是一个“听话”的 Agent，它最直接的做法是调用 `execute_salary_adjustment`，改数据库，然后回一句“已完成”。看起来只花了 3 秒，但它同时制造了四个问题：

- **审批缺失**：薪酬委员会 5 月的调薪预算会还没开，P6-1 的带宽占用没有确认。赵敏有“发起”的权限，但没有“批准预算”的权限。
- **职责不分**：申请人赵敏、执行人赵敏、系统操作人赵敏，三个身份重叠。出了错，没人能证明“这是谁批的”。
- **证据缺失**：半年后内审问“这次调薪经过谁批准”，系统里只有一条聊天记录，而聊天记录可以被删除、改写、截图伪造。
- **数字代价**：`P5-2` 到 `P6-1` 的月薪差约 2000 元；按 13 薪、年终奖基数、社保公积金基数联动估算，一年影响约 3 万元。如果错调成 `P6-2`，差额接近翻倍，而且会污染后续的薪酬带宽占用。

更糟的是，员工自己也会来“帮忙”。张伟在自助入口说：“我已经晋升了，帮我把薪资调一下。”如果 Agent 把“用户说了”当成“用户有权”，越权就发生了。

所以我们需要的不是一句“请确认”，而是一条**可恢复、可拒绝、可审计**的流程。

## 2. 概念

### 2.1 HITL 不是弹窗，是“执行权交接”

很多教程把 HITL 写成“执行前弹一个 `confirm()`”。这不够，原因很具体：

| 维度 | 前端弹窗 | 真正的 HITL |
| --- | --- | --- |
| 状态在哪 | 浏览器内存 | 服务端持久化，可跨进程恢复 |
| 谁批准 | 当前登录的任何人 | 有审批权限的特定角色 |
| 申请人能否批准自己 | 能 | 不能（职责分离） |
| 刷新/断网后 | 丢失，重来 | 审批单还在，状态可恢复 |
| 审计 | 一条前端日志 | 带哈希链的不可抵赖记录 |

HITL 的本质是：**把“执行权”从模型手里拿走，交给一个可追责的人。** 模型可以提议、可以准备材料、可以解释影响，但不能替人签字。

### 2.2 四个动作：提议、中断、决定、恢复

一次调薪审批会经历四个动作：

```text
HRBP 赵敏              Agent                ApprovalGate           HRD 林芳
   |  "调到 P6-1"         |                      |                     |
   |--------------------->|                      |                     |
   |                      | 1. 模型提出工具调用     |                     |
   |                      |--------------------->|                     |
   |                      |                      | 2. 创建审批单 AP-0001 |
   |                      |<---- Interrupted ----|                     |
   |                      | 3. state 序列化进库    |                     |
   |                      |                      | 4. 待办通知 -------->|
   |                      |                      |                     | 5. 看脱敏摘要
   |                      |                      |<--- approved=True ---|
   |                      | 6. resume(state_json) |                     |
   |                      |<---------------------|                     |
   |                      | 7. 查权限 + 职责分离   |                     |
   |                      | 8. 执行 + 写审计       |                     |
   |<---- 最终答复 --------|                      |                     |
```

注意第 3 步：**必须把状态存下来**。如果 Agent 进程重启、服务器发布、用户关掉浏览器，审批单和 Agent 的上下文都不能丢。状态里至少要有：会话 id、申请人、申请角色、原始指令、消息历史、待执行的工具和参数、审批单 id、当前状态。

### 2.3 RBAC：角色决定“能不能发起”，不决定“模型想不想”

RBAC 把权限挂在角色上，再把角色挂到人身上，而不是写进 Prompt。Prompt 里的“你是管理员”只是文字，模型可以忽略、可以被注入覆盖；代码里的权限检查才是硬约束。

本章的矩阵只有四行，但已经把关键边界划出来了：

| 权限点 | employee | hrbp | hrd | auditor |
| --- | --- | --- | --- | --- |
| `salary:propose` | - | Y | Y | - |
| `salary:approve` | - | - | Y | - |
| `salary:execute` | - | - | Y | - |
| `audit:read` | - | - | Y | Y |

两个设计点：

- **最小权限**：HRBP 只能发起，不能审批，也不能执行；审计角色只能看审计，不能改薪酬。
- **职责分离（Separation of Duties）**：申请人不能是审批人。即使赵敏哪天被授予了 `salary:approve`，她也不能批自己提交的单子。

这两条不是“多加一个 if”，而是内控的基本假设：**一个人不能同时拥有“提议、批准、执行、核查”中的全部权力。**

### 2.4 PII 脱敏：展示层最小化

PII（Personally Identifiable Information，个人可识别信息）指手机号、邮箱、身份证号这类能定位到具体自然人的数据。审批人需要看到“是谁、从哪档到哪档、依据是什么”，但不需要看到完整手机号和邮箱。脱敏应该发生在**展示层**：

```text
原始：13800001001  zhangwei@acme.example
展示：138****1001   zha***@acme.example
```

数据库里仍然保存原始值（执行时需要），但审批单、日志、通知、模型上下文里只出现脱敏后的版本。反过来做——只在页面上打码，日志里却是明文——等于没做。

### 2.5 审计哈希链：让“改一条”变成“全链报警”

普通日志的问题是：有写权限的人可以改。哈希链用一行公式解决“事后篡改”。这里的 sha256 是一种哈希函数：把任意长度的内容压成 64 位十六进制指纹，内容改一个字符，指纹就完全不同：

```text
事件 0：prev_hash = 0000...0000   hash = sha256(事件0 + prev_hash)
事件 1：prev_hash = hash(事件0)     hash = sha256(事件1 + prev_hash)
事件 2：prev_hash = hash(事件1)     hash = sha256(事件2 + prev_hash)
```

验证时从创世哈希开始，逐条重算：

- 改了事件 1 的任何一个字段 → 事件 1 的 `hash` 对不上；
- 改了事件 1 还想蒙混 → 必须同时改事件 2 的 `prev_hash`，再改事件 3……直到链尾；
- 删掉事件 1 → 事件 2 的 `prev_hash` 指向一个不存在的哈希，立刻暴露。

但要说清楚它的边界：**哈希链防的是“事后悄悄改”，不是“有权限的人整体重写”。** 如果攻击者能改应用库、也能改链，他可以从头重算一条新链。生产上要把链头每天锚定到外部（对象存储的 WORM 桶、另一套账、时间戳服务），才能把“改写成本”抬高。

> ⚠️ **生产提醒**：审计日志不要和业务表放在同一个可写账号下。至少做到“应用只能追加、不能更新/删除”，并每天把链头哈希抄送到独立存储。否则哈希链只是一条好看的装饰。

## 3. 动手

> 🧩 **读法**：第 3 节的代码用于解释原理；本章实际运行的 demo 已改为 LangChain 版，完整代码见章末“LangChain 版关键实现”与 `code/` 对应脚本。


完整代码在 `code/ch12_hitl.py`，从仓库根目录运行：

```powershell
python code/ch12_hitl.py
```

下面挑四段核心代码。第一段是权限矩阵，它把“谁能做什么”写成了数据：

```python
ROLE_PERMISSIONS = {
    "employee": {"profile:read_self"},
    "hrbp": {"profile:read", "salary:read", "salary:propose"},
    "hrd": {"profile:read", "salary:read", "salary:propose",
            "salary:approve", "salary:execute", "audit:read"},
    "auditor": {"audit:read"},
}
```

第二段是闸门。它在敏感工具执行前创建审批单，把待执行动作写进状态，然后抛出 `Interrupted`：

```python
def open_ticket(self, state, action, args):
    target = employee(args["employee_id"])
    self._seq += 1
    ticket = ApprovalTicket(
        ticket_id=f"AP-{self._seq:04d}",
        employee_id=target["id"],
        from_band=SALARY_DB[target["id"]],
        to_band=args["new_band"],
        requested_by=state.actor,
        contact=f"{target['phone']} {target['email']}",
    )
    self.tickets[ticket.ticket_id] = ticket
    state.status, state.ticket_id = "awaiting_approval", ticket.ticket_id
    state.pending_action, state.pending_args = action, dict(args)
    self.audit.append("approval_requested", state.actor, {"ticket": ticket.ticket_id})
    raise Interrupted(ticket, state)
```

第三段是恢复。注意顺序：**先查职责分离，再查审批权限，最后才执行**：

```python
def resume(self, state_json, *, approved, approver, approver_role, reason=""):
    state = AgentState.from_json(state_json)
    ticket = self.gate.tickets[state.ticket_id]
    if approver == ticket.requested_by:
        raise PermissionDenied("职责分离：申请人不能审批自己提交的单据")
    PermissionChecker.require(approver, approver_role, "salary:approve")
    if not approved:
        ticket.status = "rejected"
        state.status = "rejected"
        return state
    PermissionChecker.require(approver, approver_role, "salary:execute")
    SALARY_DB[ticket.employee_id] = ticket.to_band
    self.audit.append("salary_executed", approver, {"ticket": ticket.ticket_id})
    state.status = "done"
    return state
```

第四段是链校验，只有十几行，却是整章的“验收器”：

```python
def verify_chain(events):
    prev = GENESIS_HASH
    for index, event in enumerate(events):
        if event.get("prev_hash") != prev:
            return False, index
        if event.get("hash") != _hash_event(event):
            return False, index
        prev = event["hash"]
    return True, None
```

运行后你会依次看到：

- 张伟以 `employee` 身份发起调薪，被拒绝：缺少 `salary:propose`；
- 赵敏以 `hrbp` 身份发起，拿到审批单 `AP-0001`，联系方式显示为 `138****1001 zha***@acme.example`；
- 林芳以 `hrd` 身份 `resume(approved=True)`，张伟的薪资档变成 `P6-1`；
- 赵敏试图审批自己的单，被职责分离拦下；
- 第二单 `AP-0002` 被拒绝，李娜的薪资档保持 `P6-1`；
- 审计链 6 条事件校验通过；把第 2 条事件的 `to` 改成 `P7-1` 后，校验在**第 2 条**失败。

## 4. 逐行拆解

### 4.1 为什么在“执行前”拦截，而不是“执行后记录”

事后记录只能证明“发生过”，不能阻止“发生”。调薪这种写操作一旦落库，即使马上回滚，也可能已经触发工资单、社保申报、个税计算、通知邮件。等这些下游系统跑完，回滚就不只是改一个字段了。

所以闸门必须放在**工具真正产生副作用之前**。这也是 `open_ticket` 里先创建审批单、再 `raise Interrupted` 的原因：异常就是控制流的“刹车”，而状态里的 `pending_action` 就是“下次从哪里继续”的路标。

> 💡 **小白提示**：`Interrupted` 不是错误，是一种正常的流程信号。就像电梯按了“暂停”，不是电梯坏了，是有人在等一个决定。

### 4.2 状态里为什么连 `messages` 都要存

只存“待执行工具 + 参数”也能恢复动作，但恢复后的 Agent 会“失忆”：它不知道自己为什么提出这个动作，也无法向用户解释依据。真实系统里，审批通过后通常要由 Agent 继续生成一段收尾答复（“已按 AP-0001 执行，生效日期 6 月 1 日”），这段答复依赖原始指令和工具调用记录。

本章的 `AgentState` 因此把 `messages` 一起序列化。代价是状态可能很大（长对话几十 KB），生产上要做三件事：只存必要消息、敏感字段加密、设置过期时间。

### 4.3 职责分离为什么放在权限检查之前

如果先查 `salary:approve`，赵敏会得到“缺少权限”的提示；这当然也对，但没有点出真正的问题。她就算被授予了审批权限，仍然不能批自己的单。把“申请人 == 审批人”放在最前面，是为了让拒绝理由准确，也让审计事件记成 `separation_violation`，而不是笼统的 `permission_denied`。

安全代码的可读性很重要：**拒绝理由本身就是审计证据的一部分。**

### 4.4 哈希链能发现什么、不能发现什么

能发现：改字段、删事件、调换顺序、插入伪造事件。因为下一个事件的 `prev_hash` 会断开。

不能发现：拥有完整写权限的人从创世哈希开始重算整条链；也不能发现“一开始就记了假事件”。所以链要和**外部锚定**配合：每天把链头哈希写到一个应用改不了的地方，第二天校验时只要链头对不上，就知道历史被重写。

### 4.5 脱敏放在 `render()` 而不是数据库

代码里 `ApprovalTicket.contact` 保存原始值，`render()` 才调用 `mask_pii`。这是有意为之：

- 执行时需要原始值（发通知、写工资系统）；
- 展示、日志、审批摘要只需要脱敏值；
- 把“原始值”和“展示值”分开，才能分别做权限控制。

如果一开始就把原始值删掉，执行阶段反而拿不到；如果一开始就把原始值到处传，泄漏面会失控。正确做法是**同一份数据，两种视图**。

## 5. 实验

改完代码后，从仓库根目录重新运行 `python code/ch12_hitl.py`，观察输出变化。

**实验一：给 HRBP 加上审批权限。** 把 `hrbp` 的权限集合里加上 `salary:approve` 和 `salary:execute`，再让赵敏审批自己的单。预期：仍然被“职责分离”拒绝，因为审批人等于申请人。这个实验说明权限和职责分离是两道独立的门。

**实验二：给审批单加过期时间。** 在 `ApprovalTicket` 里加 `expires_at`（例如创建后 24 小时），`resume` 时先比较当前时间。预期：过期的单子即使 `approved=True` 也被拒绝，并写入 `approval_expired` 审计事件。生产上还要加提醒和升级。

**实验三：批量调薪加双人复核。** 把“一次调 10 人”拆成一张批次单，要求两个不同角色的审批人（HRD + 财务）都通过才执行。预期：只签一个时状态仍是 `awaiting_approval`；第二个人签完才 `done`。注意两个审批人不能是同一个人。

**实验四：篡改不同位置。** 把 `tampered[index]` 的下标换成 0、1、5，观察 `verify_chain` 返回的坏点下标是否等于你改动的位置。预期：等于。再试着直接 `del tampered[2]`，观察坏点是否落在被删位置的下一条。

## 6. 工程化视角

把本章的 240 行放到生产，还缺不少东西。下面按优先级列。

**第一，审批单要落库，不能放内存。** 本章用 `self.tickets` 字典是为了让代码短。生产上至少是一张 `approval_ticket` 表：单号唯一、状态机（`pending/approved/rejected/expired/cancelled`）、申请人、审批人、角色、payload、创建/过期时间、版本号。并发审批要用乐观锁或 `UPDATE ... WHERE status='pending'`，防止两个人同时点“通过”。

**第二，执行要幂等。** 审批通过后网络可能重试，`resume` 可能被调用两次。幂等（同一操作重复执行，结果不变）是这里唯一的解药：执行前检查 `ticket.status == 'pending'`，执行时带幂等键（例如 `ticket_id`），下游系统按幂等键去重。否则“审批一次、调薪两次”会比不审批更糟。

**第三，审批要有过期、提醒、升级。** 一张单子挂 7 天没人处理，业务就卡住了。要有 SLA：2 小时提醒、24 小时升级到上级、72 小时自动过期并通知申请人重提。过期不是失败，是流程的一部分。

**第四，身份要能落到执行侧。** 本章的 `resume` 用 `approver` 字符串表示“以谁的身份执行”。生产上要有服务账号与委托令牌：Agent 不能拿 HRD 的长期密钥，而应拿一个短期的、限定单号的委托凭证。审计里同时记录“申请人、审批人、执行服务、实际生效时间”。

**第五，审计要可检索、可导出、可验证。** 哈希链适合防篡改，但不适合按员工、按时间范围查询。常见做法是“双写”：业务审计表负责查询，哈希链负责完整性；每天把链头锚定到外部存储，并提供一个 `verify_chain` 的离线校验工具。

**第六，审批界面要展示“影响范围”。** 只给一个“通过/拒绝”按钮是不够的。审批人需要看到：原档位、新档位、月薪差、年度成本、预算占用、依据文档编号、历史调薪记录、同岗位对比。本章的 `render()` 只做了最小摘要，生产上要做得更完整，但**仍然要脱敏**。

### 12.6.1 不能做什么（红线清单）

这一节请当成 checklist 用。以下事情不要做：

1. **不能让模型自己批准自己的工具调用。** 模型输出的“我已确认”不是审批，只是文本。
2. **不能把角色写进 Prompt 当权限。** “你是 HR 总监”挡不住提示注入；权限必须在代码/网关注入。
3. **不能让申请人审批自己的单。** 包括“同一人换了个账号”的情况，要按自然人而不是账号去重。
4. **不能审批后重跑整个 Agent。** 重跑可能再次触发写工具，造成重复副作用；要恢复状态、只执行待办动作。
5. **不能只在前端脱敏。** 日志、Trace、模型上下文、通知短信都要脱敏。
6. **不能把审计日志放在应用可写、可删除的同一个账号下。** 至少要追加写 + 独立备份 + 链头锚定。
7. **不能让“批量调薪”一个人批。** 批次越大，越需要双人复核和抽样复核。
8. **不能把“用户点了确认”当成合规审批。** 普通员工的确认不构成授权，授权来自角色和流程。
9. **不能在拒绝时只返回“失败”。** 要返回具体原因（缺哪个权限、哪条职责分离、哪张单已过期），否则申请人无法修正。
10. **不能把审批单的 payload 当成可信输入。** 恢复时要重新校验员工是否存在、档位是否合法、金额是否超限。

> ⚠️ **生产提醒**：HITL 的验收标准不是“有个弹窗”，而是“断网、重启、重复调用、越权、拒绝、过期”六种情况下，数据都正确、审计都完整。

## 7. 常见坑

**坑一：审批状态只存在浏览器里。** 现象：用户刷新页面后 Agent 忘了自己在等什么，重新发起一次调薪。原因：状态在内存/前端。解法：审批单与服务端 Agent 状态都落库，用 `session_id + ticket_id` 恢复。

**坑二：审批通过后从头跑 Agent。** 现象：模型又“想”了一遍，这次调了另一个字段。原因：把 `resume` 实现成了“重新执行整个任务”。解法：恢复状态后只执行 `pending_action`，并在执行前再次校验参数。

**坑三：申请人和审批人是同一个账号。** 现象：HRBP 给自己提调薪，自己点通过。原因：只查了角色，没查自然人。解法：在 `resume` 里先比较 `approver == requested_by`，并把这个规则写进测试。

**坑四：审计日志可改。** 现象：内审发现日志时间和工资单对不上。原因：日志表用应用账号读写，谁都能 `UPDATE`。解法：追加写权限、哈希链、每日链头锚定、离线校验。

**坑五：脱敏只做在页面上。** 现象：客服在 Trace 里看到候选人的完整手机号。原因：脱敏函数只在前端调用。解法：在数据出口（日志、Trace、模型上下文、通知）统一做脱敏，页面只是其中一个出口。

**坑六：审批单没有过期。** 现象：三个月前的单子突然被执行。原因：没有 `expires_at`。解法：过期校验 + 定时清理 + 过期审计事件。

## 8. 练习

**练习一（基础）**：把 `auditor` 的权限集合改成同时包含 `audit:read` 和 `salary:read`，用 `PermissionChecker.can()` 验证变化。再运行一次脚本，确认审计角色仍然不能发起、审批、执行调薪。

**练习二（进阶）**：给 `ApprovalTicket` 增加 `expires_at` 字段（ISO 8601 字符串），在 `resume` 里做过期校验，并新增 `approval_expired` 审计事件。要求：过期的单子不能执行，但可以重新发起。

**练习三（进阶）**：实现“批量调薪”的 `BatchApproval`：一张批次单包含 3 名员工，要求两个不同的审批人（`hrd` 与财务角色）都通过。提示：把 `status` 从 `pending` 改成 `partially_approved`，第二个审批人通过后才执行。

**练习四（挑战）**：把审计日志落到 SQLite（标准库 `sqlite3`），表结构包含 `seq/action/actor/detail/prev_hash/hash`，并实现 `verify_chain_from_db()`。再写一个测试：直接 `UPDATE` 第 3 条事件的 `detail`，验证函数能定位到第 3 条。

<details>
<summary>参考答案</summary>

**练习一**：本章打印的权限矩阵只有 4 行（propose/approve/execute/audit:read），所以矩阵不会多出一行；但 `PermissionChecker.can("auditor", "salary:read")` 会从 `False` 变成 `True`，说明“能看”和“能改”是两回事。审计角色需要独立复核，所以通常给它读权限、不给写权限；一旦能改，审计就失去了独立性。

**练习二**：给 `ApprovalTicket` 加 `expires_at: str`，创建时写入 `datetime.now(timezone.utc) + timedelta(hours=24)`。在 `resume` 开头：

```python
if datetime.fromisoformat(ticket.expires_at) < datetime.now(timezone.utc):
    ticket.status = "expired"
    state.status = "expired"
    self.audit.append("approval_expired", approver, {"ticket": ticket.ticket_id})
    return state
```

注意：过期判断要放在“已处理”判断之前，否则已过期的单子会被当成“已处理”。创建时写入 `(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()`；测试时把 `expires_at` 改成过去的时间即可。

**练习三**：`BatchApproval` 维护 `approvals: dict[str, str]`（审批人 → 决定）。每次 `resume` 先记录，再检查“已投通过票的不同自然人”：

```python
approved_by = {person for person, decision in self.approvals.items() if decision == "approved"}
if len(approved_by) < 2:
    ticket.status = "partially_approved"
    return state
# 两个不同审批人都通过后才执行
```

关键约束：集合里放的是“人”，不是“角色”；同一人换角色不能算两票。执行前同样要过幂等和职责分离检查。

**练习四**：建表时把 `hash` 设成 `PRIMARY KEY`，`prev_hash` 建索引。`verify_chain_from_db()` 按 `seq` 排序读出来，复用 `verify_chain()`。篡改测试用 `sqlite3` 执行 `UPDATE audit SET detail=? WHERE seq=3`，再调用校验函数；预期返回 `(False, 3)`。生产上还要把数据库设成应用账号只能 `INSERT`，并每天把最大 `seq` 的 `hash` 锚定到外部。

</details>

## 9. 小结与下一章

三句话记住这章：

1. **HITL 的核心是状态**：中断时把状态存下来，恢复时只执行待办动作，而不是重跑整个 Agent。
2. **权限的核心是分离**：角色决定“能不能发起”，职责分离决定“能不能批自己的单”，两者缺一不可。
3. **审计的核心是链**：`prev_hash` 让篡改留下痕迹，外部锚定让重写付出代价。

下一章，一个人忙不过来了：校招要同时处理几十名候选人，招聘、面试、合规三个角色的目标还会冲突。我们要把“一个人审批”扩展成“多个 Agent 协作 + 一个 Supervisor 仲裁”。

---

## 10. 附：LangChain 版关键实现

> 本章实际运行的 demo 使用 **StateGraph + interrupt + Command**，完整代码见 `code/ch12_hitl.py`。下面只保留骨架，方便你对照前面的原理示意阅读。

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt

def approval_node(state):
    decision = interrupt({"action": "adjust_salary", "ticket": state["ticket"]})
    return {"approved": decision == "approve"}

app = graph.compile(checkpointer=InMemorySaver())
app.invoke({"message": "把张伟调到 P6-1"}, config)      # 停在审批
app.invoke(Command(resume="approve"), config)          # 审批后执行
```

| 本章概念 | LangChain / LangGraph 对应物 |
| --- | --- |
| 中断 | `interrupt()` |
| 恢复 | `Command(resume=...)` |
| 持久化 | `InMemorySaver` |

> 🧩 **怎么读**：先看正文理解“为什么需要这一层”，再看上面的骨架理解“框架怎么表达这一层”，最后打开 `code/ch12_hitl.py` 看完整实现与断言。面试时两条线都要能讲：原理线 + 框架线。
