---
title: "13 | Multi-Agent：招聘小组如何协作"
slug: "multi-agent"
order: 13
part: "生产级可靠性"
minutes: 70
difficulty: "高阶"
prerequisites: ["12"]
summary: "用 Supervisor 编排招聘、合规、面试三个角色，处理冲突并设好终止条件。"
---
> 🧩 **框架说明**：本章 demo 基于 **LangChain 1.x + LangGraph 1.x**，核心 API：`StateGraph`、`Command`、`supervisor`。正文中的代码若标注“原理示意”（包括旧版 MockLLM / 手写循环片段），用于解释内部机制，不是最终运行代码；完整可运行代码见 `code/ch13_multi_agent.py`。


## 0. 本章你会得到什么

学完这章，你应该能：

1. 判断什么时候需要多 Agent，什么时候单 Agent + 工具就够了。
2. 用 `MessageBus` + `Agent` 基类 + `Supervisor` 搭一个星型协作拓扑，让招聘、合规、面试三个角色共享 `CaseState`。
3. 给多 Agent 设计消息协议、交接规则、冲突仲裁和**明确的终止条件**。
4. 用“覆盖率 / token / 轮次”三个指标，诚实地比较单 Agent 与多 Agent，而不是只讲“人多力量大”。

这一章的主角不是“让三个模型聊天”，而是**分工之后，谁负责、谁仲裁、什么时候停**。

## 1. 场景

2026 年 9 月，秋招。

一家公司的校招团队只有三个人：HRBP 赵敏负责简历与流程，两位技术面试官负责评估，合规专员每周只来半天。他们要在一周内处理 50 名候选人——本章的代码用种子数据里的 6 人做演示，规模缩小，但角色冲突一点没少。

6 名候选人的情况各不相同：

- 林晓，后端，86 分，期望 35k；
- 张蕾，前端，91 分，可立即到岗；
- 王浩，算法，88 分，期望 45k，在职，交接要一个月；
- 李婷，HRBP，84 分，在职 7 年；
- 陈坤，测试，72 分，自动化基础扎实但业务经验弱；
- 刘敏，产品，87 分，在职，需要确认是否接受出差。

如果只用一个“全能 Agent”，最常见的失败是这样的：

1. **合规被跳过。** 招聘 Agent 觉得王浩技术强，直接推进到面试；没人注意到 45k 已经超出校招带宽 18–35k。等 Offer 审批时被打回，前面两轮面试白约。
2. **角色目标冲突。** 业务想快，希望今天就约面；合规要慢，要等竞业核查。单 Agent 在一个上下文里“和稀泥”，最后哪个目标都没守住。
3. **上下文爆炸。** 6 名候选人 × 简历 + 制度 + 面试记录 + 邮件，很快超过窗口；模型开始忘记前面的结论，重复问同样的问题。
4. **责任不清。** 出了问题，你无法回答“这个结论是招聘给的，还是合规给的”。日志里只有一大段模型输出。

所以我们把工作拆给三个角色，再找一个“班长”负责分派和叫停。

## 2. 概念

### 2.1 什么时候真的需要多 Agent

多 Agent 不是默认答案。先看三个判断条件，满足两个以上再考虑拆：

| 判断条件 | 单 Agent 的表现 | 多 Agent 的价值 |
| --- | --- | --- |
| 目标会冲突（快 vs 稳） | 一个上下文里互相妥协 | 各自守住目标，由 Supervisor 仲裁 |
| 工具/权限不同 | 一个 Agent 拿到过大权限 | 合规只能读、招聘只能推进、面试只能排期 |
| 需要独立审计 | 一段混合输出，难归因 | 每个角色一条消息，责任可追溯 |
| 只是步骤多 | 加工具 + 状态机即可 | 拆了反而增加协调成本 |

一句话：**多 Agent 买的是“责任边界”和“冲突处理”，不是免费的速度。** 如果任务只是“查余额 → 查制度 → 回答”，单 Agent 加两个工具更简单。

### 2.2 星型拓扑：Supervisor 只做三件事

本章用 Supervisor（主管）模式，不让 Agent 之间自由聊天：

```text
                    ┌──────────────────┐
                    │    Supervisor     │  分派 / 计时 / 仲裁
                    └────────┬─────────┘
            ┌────────────────┼─────────────────┐
            v                v                 v
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │ Recruiter    │  │ Compliance   │  │ Interviewer  │
    │ 初筛、推进    │  │ 合规一票否决  │  │ 排期、评估    │
    └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
           └─────────────────┴─────────────────┘
                             v
                  ┌─────────────────────┐
                  │ 共享 CaseState       │
                  │ stage / checks / 结论 │
                  └─────────────────────┘
```

Supervisor 不替角色做判断，它只做三件事：

1. **分派**：根据 `CaseState.stage` 决定下一个该谁上。
2. **计时**：轮次上限、token 预算、单 case 连续无进展。
3. **仲裁**：合规否决时终止该 case；角色卡住时升级人工。

Agent 之间不直接对话，所有消息都发回 Supervisor，由 Supervisor 决定下一步。这比“让 Agent 互相 @”啰嗦，但可观测、可测试、不会出现两个 Agent 互相客套 20 轮。

### 2.3 消息协议：每条消息都能被审计

消息不是一句自然语言，而是一个结构化对象：

| 字段 | 含义 | 例子 |
| --- | --- | --- |
| `round_no` | 第几轮 | `9` |
| `sender` | 谁发的 | `compliance` |
| `recipient` | 发给谁 | `supervisor` |
| `topic` | 消息类型 | `compliance` |
| `case_id` | 哪名候选人 | `C003` |
| `text` | 人类可读摘要 | `王浩 一票否决：...` |
| `payload` | 机器可读结论 | `{"veto": true}` |

`text` 给人看，`payload` 给程序看。不要只存 `text`，否则下游只能再用一次模型去解析它；也不要只存 `payload`，否则排障时人看不懂。

### 2.4 共享 CaseState：结论只有一份

`CaseState` 是一块共享黑板：候选人、当前阶段、已完成的检查、是否被否决、否决原因。三个角色读写同一份状态，谁也不能在自己的上下文里“私藏”一个结论。

这解决了一个常见问题：招聘 Agent 说“我觉得他行”，合规 Agent 说“我觉得他不行”，面试官说“我排了”。三个结论散落在三段对话里，没人知道最终以谁为准。共享状态把“结论”收敛成一份，消息只是“我做了什么”的通知。

### 2.5 合规一票否决：规则判定，模型解释

王浩的期望薪资 45k，超出校招带宽 18–35k。这条判定不能交给模型“感觉一下”，必须是确定性规则：

```python
if candidate["expected_salary_k"] > SALARY_CAP_K:
    veto.append(f"期望薪资 {candidate['expected_salary_k']}k 超出校招薪酬带宽 18-35k")
```

模型在这个环节只做一件事：把规则结论写成人能读懂的一句话。它不能改判，也不能因为“候选人很优秀”而放过。这是本章最重要的设计选择：**越接近法律、薪酬、隐私的判定，越要规则化；越接近表达、总结、谈判，越可以让模型发挥。**

### 2.6 终止条件：不设上限的协作就是聊天

多 Agent 最常见的反模式是“无止境聊天”：A 让 B 补充，B 让 A 确认，C 又提出一个新问题。必须提前写死终止条件。本章的 `Supervisor.run` 检查五条：

1. **队列为空**：所有 case 都完成、淘汰或被否决。
2. **轮次上限**：最多 12 轮，到点停。
3. **token 预算**：累计超过 6000 token 就停，防止单次运行成本失控。
4. **合规否决**：该 case 立即终止，不再进入面试。
5. **连续两轮无进展**：同一个 case 状态没变化，升级人工。

只要命中任意一条，Supervisor 就停止分派，并输出停止原因。**“停不下来”不是模型的问题，是编排代码没有写终止条件。**

## 3. 动手

> 🧩 **读法**：第 3 节的代码用于解释原理；本章实际运行的 demo 已改为 LangChain 版，完整代码见章末“LangChain 版关键实现”与 `code/` 对应脚本。


完整代码在 `code/ch13_multi_agent.py`，从仓库根目录运行：

```powershell
python code/ch13_multi_agent.py
```

第一段是消息总线。它把每条消息打印出来，同时留在 `log` 里供后续统计：

```python
class MessageBus:
    def __init__(self):
        self.log = []
        self.inboxes = defaultdict(list)

    def send(self, message):
        self.log.append(message)
        self.inboxes[message.recipient].append(message)
        print(f"[轮 {message.round_no:02d}] {message.sender} → "
              f"{message.recipient} | {message.case_id} | {message.topic} | {message.text}")
```

第二段是共享状态。注意 `stage` 是唯一的“下一步”依据，`checks` 记录已经做过的维度：

```python
@dataclass
class CaseState:
    case_id: str
    candidate: dict
    stage: str = "new"          # new → screening_done → compliance_ok
    done: bool = False
    blocked: bool = False
    block_reason: str = ""
    checks: list[str] = field(default_factory=list)
    stuck: int = 0
```

第三段是合规的否决逻辑。规则先算出 `veto`，模型只负责写说明：

```python
def act(self, round_no, case):
    candidate = case.candidate
    veto = []
    if candidate["expected_salary_k"] > SALARY_CAP_K:
        veto.append(f"期望薪资 {candidate['expected_salary_k']}k 超出校招薪酬带宽 18-35k")
    masked = mask_pii(f"{candidate['phone']} {candidate['email']}")
    explanation = self.think(f"候选人 {candidate['name']}，期望 ...")
    case.checks.append("compliance")
    if veto:
        case.blocked = case.done = True
        case.stage = "blocked"
        case.block_reason = "；".join(veto)
        self.report(round_no, case, "compliance", f"{candidate['name']} 一票否决：{case.block_reason}", veto=True)
        return
    case.stage = "compliance_ok"
    self.report(round_no, case, "compliance", f"{candidate['name']} 合规通过", veto=False)
```

第四段是 Supervisor 的分派循环。它只按 `stage` 路由，并在每轮结束后检查终止条件：

```python
ROUTES = {"new": "recruiter", "screening_done": "compliance", "compliance_ok": "interviewer"}

while queue:
    if self.rounds >= self.max_rounds:
        self.stop_reason = "达到轮次上限 12"
        break
    if self.used_tokens() >= self.token_budget:
        self.stop_reason = "达到 token 预算"
        break
    self.rounds += 1
    case = queue.popleft()
    before = (case.stage, case.done, case.blocked)
    self.agents[self.ROUTES[case.stage]].act(self.rounds, case)
    if case.done:
        continue
    if (case.stage, case.done, case.blocked) == before:
        case.stuck += 1
        if case.stuck >= 2:
            case.done, case.block_reason = True, "连续两轮无进展，升级人工"
            continue
    queue.append(case)
```

运行后，消息流大致是这样（节选）：

```text
[轮 01]  recruiter → supervisor | C001 | screening  | 林晓 86 分 → 通过初筛
[轮 07] compliance → supervisor | C001 | compliance | 林晓 合规通过（展示层 137****1001）
[轮 09] compliance → supervisor | C003 | compliance | 王浩 一票否决：期望薪资 45k 超出薪酬带宽
[轮 12] interviewer → supervisor | C001 | interview  | 林晓 一面安排 2026-12-01 10:00
```

最终结果：

- 12 轮打满上限，12 条消息；
- 完成 1 人（林晓）、淘汰 1 人（陈坤 72 分）、否决 1 人（王浩 45k）；
- 3 人（张蕾、李婷、刘敏）停在“已合规、未面试”，转人工；
- 三个 Agent 的 token 分别是 recruiter 522、compliance 480、interviewer 74；
- 加 12 条消息 × 40 token 的序列化开销，多 Agent 共约 1556 token；单 Agent 基线约 1050 token；
- 覆盖率：单 Agent 只做筛选，6/18；多 Agent 完成 12/18。

这里有一个很容易被误读的数字：**多 Agent 的 token 比单 Agent 高约 48%，但覆盖的检查维度是它的两倍。** 这不是“多 Agent 更便宜”，也不是“多 Agent 一定更贵”，而是“你花了更多钱，买到了合规和面试两个维度”。如果业务不需要这两个维度，单 Agent 就够了。

## 4. 逐行拆解

### 4.1 为什么用 `stage` 路由，而不是让模型决定下一个角色

让模型决定“下一步找谁”听起来很智能，但在校招这种流程里，下一步是确定的：没初筛就找招聘，没合规就找合规，合规过了才找面试。把路由写成 `ROUTES` 字典，有三个好处：

- 可测试：给定 `stage`，下一个 Agent 是确定的；
- 可审计：路由决策不依赖模型当次的“心情”；
- 可恢复：进程重启后，只要 `CaseState` 还在，路由就能继续。

模型该负责的是“这个候选人是否匹配”“这段面试记录说明了什么”，而不是“流程下一步该谁走”。

### 4.2 合规否决为什么必须是规则

薪酬带宽、竞业限制、隐私授权，这三类判断的共同点是：**错了要承担责任，而且必须能解释。** 如果让模型判断“45k 是否超预算”，它可能说“考虑到候选人优秀，可以特批”——这句话在业务上也许有道理，但在合规上是灾难：它把一条硬规则变成了可协商的建议。

规则化之后，模型的位置很清楚：

- 规则负责“是不是违规”；
- 模型负责“怎么把违规原因说清楚”；
- 人负责“要不要特批”（走例外审批，而不是让 Agent 放行）。

这也是“LLM 在真实系统中的位置”的标准答案：**LLM 是语言与推理组件，不是政策执行器。** 真实系统里，招聘 Agent 可以用 LLM 做简历要点抽取和匹配打分（带评分 rubric），面试官 Agent 可以用 LLM 总结面试记录，合规 Agent 的判定则必须落到规则引擎 + 人工复核。

### 4.3 消息日志为什么比“最终答案”更重要

多 Agent 排障时，你几乎不会先看最终答案，而是先看消息流：谁在第几轮说了什么、case 卡在哪个阶段、哪条消息之后状态没变。

本章的 `MessageBus.log` 同时承担三个用途：

- **可观测**：终端直接打印，读者不用调试器就能看懂；
- **可统计**：轮次、消息数、每个 Agent 的调用次数；
- **可回放**：把 `log` 落库后，可以重放出一次完整的协作过程。

生产上还要给每条消息加 `trace_id`、`span_id`、时间戳、耗时，接到 OpenTelemetry 或 Langfuse 这类系统里。没有消息级 Trace 的多 Agent，出问题只能靠猜。

### 4.4 12 轮上限不是拍脑袋

12 是怎么来的？6 名候选人，每人最多 3 个动作（初筛、合规、面试），理论上 18 个动作。但被淘汰和被否决的 case 会提前结束，所以实际需要的轮次少于 18。设 12 轮，既能覆盖大部分正常流程，又能在异常时及时刹车。

更重要的是：**上限要写进代码，而不是写在文档里。** 本章的 `Supervisor` 在 `while` 循环顶部检查 `self.rounds >= self.max_rounds`，任何新增角色、新增分支都不能绕过它。这比“大家注意不要聊太久”可靠一万倍。

### 4.5 token 账要算上“消息开销”

很多多 Agent 的 token 对比只算模型调用，忽略了消息序列化、共享状态复制、重复上下文。本章在对比时加了 `len(bus.log) * 40` 的消息开销，让数字更接近真实。

即便如此，这个估算仍然偏乐观：真实系统里，每个 Agent 往往要带一份系统提示、工具描述、政策片段，重复上下文的成本会更高。所以我们在文档里不说“多 Agent 更省钱”，只说“多 Agent 用更多 token 换覆盖率和责任边界”。

## 5. 实验

**实验一：把轮次上限从 12 改成 20。** 预期：张蕾、李婷、刘敏三人能走完面试，完成人数从 1 变成 4，但总 token 上升，消息数从 12 变成 15 左右。观察“完成率”和“成本”如何一起变化。

**实验二：把 `SCREEN_PASS` 从 80 改成 75。** 预期：陈坤（72）仍然淘汰，但如果有 73–79 分的候选人，会进入合规。想一想：降低门槛会提高覆盖率，但会不会让面试官过载？

**实验三：拿掉合规否决。** 把 `SALARY_CAP_K` 调到 100，王浩不再被否决。预期：他进入面试，完成人数增加，但“超额 Offer”会留到人工审批才暴露。这个实验说明：多 Agent 不是越严越好，而是要把否决放在正确的阶段。

**实验四：增加“候选人拒绝 Offer”分支。** 在 `InterviewerAgent` 之后加一个 `stage = "offer"`，由 Supervisor 读一个 `offer_accepted` 字段；如果拒绝，`stage = "closed"`，并记录原因。提示：不要新增第四个 Agent，先问“这是不是 Supervisor 的一个状态转移就够了”。

## 6. 工程化视角

**第一，消息和状态要落库。** 本章的 `MessageBus.log` 和 `CaseState` 都在内存。生产上至少要两张表：`case_state`（当前阶段、结论、版本号）和 `agent_message`（消息流水）。`case_state` 用版本号做乐观锁，防止两个 Worker 同时推进同一个 case。

**第二，交接要幂等。** Agent 处理完一个 case 后发消息、改状态，这两步可能只成功一半。用“状态机 + outbox（先写本地表、再异步投递的消息模式）”：先写状态变更和待发消息到同一个事务，再由后台投递。消费方按 `message_id` 去重。

> ⚠️ **生产提醒**：共享状态不要用“最后写入者赢”。两个 Worker 同时推进同一个 case 时，后写的会覆盖先写的结论。给 `CaseState` 加版本号，更新时带 `WHERE version = ?`，冲突就重读重试；跨 case 才考虑并行。

**第三，每个 case 一条 Trace。** Supervisor 的分派、Agent 的模型调用、工具调用，都要挂在同一个 `case_id` 下。这样你能回答“王浩为什么被否决”“林晓的面试为什么排到 12 月 1 日”。

**第四，预算要分层。** 单次模型调用有 token 上限，单个 case 有轮次上限，整批任务有总预算。任何一层超限都要停，并输出“停在哪一层、为什么”。

**第五，人工升级要是流程的一部分。** 本章的“连续两轮无进展 → 升级人工”只是一个占位。生产上要有待办队列、SLA、通知、回填机制：人工处理完，把结论写回 `CaseState`，Supervisor 再继续。

**第六，别让 Agent 直接改共享状态。** 本章为了简洁，让 Agent 直接改 `case`。生产上更稳的做法是“Agent 只返回建议，Supervisor 校验后落状态”，这样非法转移（比如跳过合规直接面试）会被 Supervisor 拦住。

### 13.6.1 多 Agent 的四个反模式

1. **聊天无止境**：没有轮次/预算上限，Agent 互相客套。解法：硬上限 + 无进展检测。
2. **责任不清**：所有 Agent 都能改所有字段，出问题无法归因。解法：按角色划分可写字段。
3. **共享状态污染**：一个 Agent 把半成品写进 `CaseState`，下一个 Agent 当真。解法：状态变更走 Supervisor 校验。
4. **重复上下文**：每个 Agent 都塞完整简历 + 全部制度，token 爆炸。解法：按角色裁剪上下文，只给当前决策需要的信息。

> ⚠️ **生产提醒**：多 Agent 的“智能”很容易掩盖“流程没设计好”。先画出状态机和责任矩阵，再决定要不要拆 Agent；拆完之后，终止条件、幂等、审计一个都不能少。

## 7. 常见坑

**坑一：以为 Agent 越多越准。** 现象：加了第四个、第五个 Agent，结论反而更乱。原因：角色边界重叠，没人对最终结论负责。解法：先写责任矩阵，一个结论只由一个角色拍板。

**坑二：让合规 Agent “综合判断”。** 现象：同样的薪资，今天放过、明天拒绝。原因：合规判定交给了模型。解法：规则判定 + 模型解释 + 人工例外审批。

**坑三：消息只存自然语言。** 现象：想统计“否决率”时，只能再调一次模型解析文本。原因：没有结构化 `payload`。解法：`text` 给人看，`payload` 给程序看，两个都存。

**坑四：没有“停”的条件。** 现象：两个 Agent 来回确认，跑到 token 上限才停。原因：只设了最大轮次，没设“无进展”检测。解法：轮次 + 预算 + 无进展，三保险。

**坑五：Supervisor 成了瓶颈。** 现象：所有 case 串行，50 人跑了一下午。原因：单线程轮询。解法：按 `case_id` 分片并行，Supervisor 只管单个 case 内的顺序；跨 case 用队列。

**坑六：把“合规通过”当成“录用”。** 现象：候选人被自动发 Offer。原因：阶段语义混淆。解法：每个阶段只回答一个问题，录用是另一个需要人签字的阶段。

## 8. 练习

**练习一（基础）**：把 `MAX_ROUNDS` 改成 6，运行并记录哪些 case 没完成。再改回 12，对比“完成率 / token / 消息数”三个数字。

**练习二（进阶）**：给 `ComplianceAgent` 增加一条规则：“在职且司龄满 6 年，必须人工复核竞业”。要求它不直接否决，而是把 `case.stage` 设为 `needs_review`，由 Supervisor 转人工。提示：新增一个终止条件，别让它卡在队列里。

**练习三（进阶）**：把 Supervisor 的“按 stage 路由”改成“轮询三个 Agent”。观察消息流有什么变化，并解释为什么本章不推荐轮询。

**练习四（挑战）**：给每个 case 加一条独立的 Trace，记录 `case_id`、轮次、每个 Agent 的 token、开始/结束时间。输出一张“最贵的 3 个 case”表，并解释贵在哪里。

<details>
<summary>参考答案</summary>

**练习一**：改成 6 后，6 名候选人都只完成初筛，没有人走到面试；完成人数从 1 降到 0。三个数字会一起下降：轮次 6、消息 6、token 约减半。结论：上限不是越大越好，要按“正常流程需要多少轮”来定。

**练习二**：在合规 Agent 里：

```python
if candidate["current_status"] == "在职" and candidate["years"] >= 6:
    case.stage = "needs_review"
    case.block_reason = "在职满 6 年，需人工复核竞业"
    case.done = True   # 简化：先摘出自动队列；生产建议加 paused 字段
    self.report(round_no, case, "compliance", "...", veto=False, review=True)
    return
```

Supervisor 不需要认识 `needs_review`，因为 `done=True` 后 case 不再入队；人工处理完把 `stage` 改回 `compliance_ok` 并重新入队即可。更干净的做法是给 `CaseState` 加一个 `paused` 字段，让“完成”和“暂停待人工”语义分开。

**练习三**：轮询会让招聘 Agent 在没有新简历时被反复调用，合规 Agent 在没初筛时被空转，消息数暴增，而且每个 Agent 都要判断“现在轮到我了吗”。本章按 `stage` 路由，保证每次调用都有人有活干。轮询适合“角色对等、任务无依赖”的场景，不适合有明确流程的招聘。

**练习四**：在 `Agent.act` 前后记 `time.perf_counter()`，把 `case_id`、`round_no`、`agent.name`、`tokens` 写进一个列表。按 case 聚合后排序。贵的 case 通常是“反复合规复核 + 多轮面试”的 case，而不是简历最长的 case——这能帮你把优化精力放在流程瓶颈上，而不是简历长度上。

</details>

## 9. 小结与下一章

三句话记住这章：

1. **多 Agent 解决的是责任边界和冲突，不是“人多更聪明”。** 单 Agent 加工具能解决的，不要拆。
2. **共享状态收敛结论，消息日志保留过程。** 一个 case 只有一份 `CaseState`，每条消息都能被审计。
3. **终止条件必须写进代码。** 轮次、预算、无进展、否决，四条硬约束缺一不可。

下一章，Agent 不只“说话”，还要“跑代码”：模型生成的 Python 可能删文件、读密钥、死循环。我们要给它一个沙箱，还要让 50 份、1000 份简历的长任务在中途崩溃后能接着跑。

---

## 10. 附：LangChain 版关键实现

> 本章实际运行的 demo 使用 **StateGraph supervisor + Command**，完整代码见 `code/ch13_multi_agent.py`。下面只保留骨架，方便你对照前面的原理示意阅读。

```python
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

def supervisor_node(state) -> Command:
    if state["done"]:
        return Command(goto=END)
    return Command(goto=next_agent(state), update={"round": state["round"] + 1})

graph = StateGraph(TeamState)
graph.add_node("supervisor", supervisor_node)
graph.add_node("recruiter", recruiter_node)
graph.add_node("compliance", compliance_node)
graph.add_edge(START, "supervisor")
app = graph.compile()
```

| 本章概念 | LangChain / LangGraph 对应物 |
| --- | --- |
| 编排 | `StateGraph` |
| 交接 | `Command(goto=...)` |
| 共享状态 | `TeamState` |

> 🧩 **怎么读**：先看正文理解“为什么需要这一层”，再看上面的骨架理解“框架怎么表达这一层”，最后打开 `code/ch13_multi_agent.py` 看完整实现与断言。面试时两条线都要能讲：原理线 + 框架线。
