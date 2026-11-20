---
title: "15 | 可观测性与评测：用数据证明 Agent 变好了"
slug: "observability-eval"
order: 15
part: "生产级可靠性"
minutes: 75
difficulty: "高阶"
prerequisites: ["14"]
summary: "建 Golden 评测集，用 Trace/Log/Metric 对比两版 Agent，并设置回归门禁。"
---

# 15 | 可观测性与评测：用数据证明 Agent 变好了

> 🧩 **框架说明**：本章 demo 基于 **LangChain 1.x + LangGraph**，核心 API：`create_agent` / `@tool` / `TracerCallbackHandler` / `BaseCallbackHandler`。正文中的代码若标注“原理示意”（包括旧版 MockLLM / 手写循环片段），用于解释框架内部机制，不是最终运行代码；完整可运行代码见 `code/ch15_eval.py`，章末有“LangChain 版关键实现”。

## 0. 本章你会得到什么

学完这一章，你应该能：

1. 说清 Trace（调用树）、Log（结构化日志）、Metric（聚合指标）三者的分工，并为一次 Agent 运行设计出可排查的记录。
2. 给 HR 服务台定义可计算的指标：意图准确率、工具集合准确率、`must_include` 命中率、任务成功率、P50/P95 延迟、单任务 token 与成本。
3. 建一个 20 条的 Golden Case（黄金评测集），做 baseline 与 improved 的 A/B 对比，输出 bad case 表。
4. 写出“成功率下降不超过 2%”的回归门禁，并知道它漏掉什么。
5. 用 MockJudge 演示 LLM-as-judge（让大模型当评委）能做什么、会偏在哪。

> 💡 **小白提示**：这一章几乎没有新业务功能，主角是“尺子”。前 14 章我们一直在造东西，这一章开始回答一个更硬的问题：你怎么证明它变好了？

## 1. 场景

6 月，HR 共享服务中心的 HRBP 赵敏遇到一件怪事。

团队在 6 月 10 日发了一版新 Prompt，改动很小：把“回答要简洁”改成“回答要完整、专业、面向员工”。上线后大家试用了一圈，一致反馈“读起来舒服多了”。但接下来两周，员工投诉从每月 12 单涨到 40 单，工单里出现三类抱怨：

- “Agent 说我年假有 12 天，HR 系统里明明是 13 天。”
- “它引用了 2024 版制度，说要提前 2 个工作日申请，我按这个时间提交，被主管退回。”
- “我问它能不能开除一个长期旷工的员工，它居然给了我一段操作步骤。”

赵敏把 40 单投诉逐条读了一遍，发现一个更麻烦的事实：团队没人能说清问题出在哪。有人猜是检索变差，有人猜是模型胡说，有人猜是路由错了。改 Prompt 的同事说：“我本地试了 5 个问题，都正常啊。”

5 个问题当然正常。问题是，线上每天有 200 多个不同的问题，而团队的验证方式是“感觉”和“五条样例”。这就是没有评测的代价：你不知道自己是在改进，还是在制造新的失败。

举个具体的后果。张伟（E1001）问“我还有几天年假”，Agent 答“12 天”。他按 12 天规划了旅行，提交申请时系统只剩 13 天额度里的 3 天可用——因为他忘了自己已经休过 2 天。申请被退回，机票改签，多花了 480 元。这个错误不是“回答不好听”，而是**把业务事实算错了**。

所以这一章我们做三件事：给一次运行装上“行车记录仪”（可观测性）；给 Agent 建一套可重复的考题（Golden Case）；用数据决定一版改动能不能上线（回归门禁）。

## 2. 概念

### 2.1 三支柱：Trace、Log、Metric 各管什么

先用一个类比。你去医院看病：

- **Trace** 是这次就诊的完整流程单：挂号 → 分诊 → 化验 → 复诊 → 开药，每一步几点开始、花了多久、谁做的。
- **Log** 是病历上的逐条记录：几点几分发生了什么，带了哪些参数。
- **Metric** 是月底医院的统计报表：平均候诊时间、化验阳性率、投诉率。

三者缺一不可。只有 Metric，你知道“成功率 90%”，但不知道那 10% 死在哪一步；只有 Trace，你能看单次，但看不了趋势；只有 Log，信息全但没人读得完。

顺便说清“结构化日志”和 `print` 的区别。`print("出错了")` 只能被人看见；`{"trace_id": "...", "case_id": "G02", "intent": "leave_policy", "tools": ["search_policy"], "success": false}` 才能被程序聚合。字段一旦定下来，就当成数据库表结构来维护：改字段要通知下游，加字段要写默认值。赵敏那次排查之所以卡住，就是因为日志里只有一句“检索失败”，没有 `doc_id`、没有版本、也没有查询词。

```text
                  ┌──────────────────────────────────────────┐
                  │            一次员工提问                   │
                  └───────────────────┬──────────────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
      ┌───────────────┐       ┌───────────────┐       ┌───────────────┐
      │     Trace     │       │      Log      │       │    Metric     │
      │  一次请求的树  │       │ 结构化事件流   │       │  聚合后的数字  │
      │ route/retrieve│       │ trace_id/case │       │ 成功率/P95/成本│
      │ /tool/compose │       │ intent/tokens │       │ 按版本、按意图 │
      └───────┬───────┘       └───────┬───────┘       └───────┬───────┘
              │                       │                       │
              ▼                       ▼                       ▼
        排查"死在哪一步"        排查"当时输入是什么"       回答"有没有变好"
```

> ⚠️ **生产提醒**：Trace 里最容易泄露 PII（个人敏感信息）。员工的手机号、身份证、薪资、绩效都不能原样进 Trace。做法是：入口处脱敏，Trace 只存 `employee_id` 和“已脱敏”标记，需要原文时走独立审计流程并留痕。

### 2.2 一次运行的 Trace 长什么样

LangChain 把每次模型调用、每次工具调用都做成回调（Callback）事件。我们继承公共层的 `TracerCallbackHandler`，加一个 `CaseTracer` 记录时间线——这就是一次运行的 Trace：

```text
TRACE improved-G02  14.79ms
  - llm (3.07ms)
  - tool:search_policy (6.73ms)
  - llm (14.79ms)
  llm=2 tool=1 token=362 error=0
```

注意 `llm=2`：`create_agent` 跑了两轮模型调用——第一轮模型决定“调 `search_policy`”，工具节点执行完，第二轮模型基于工具结果写出回答。`token=362` 来自 `MockChatModel` 的 `usage_metadata`，由回调累加；接真实模型后换成 `ChatOpenAI`，同一个回调拿到的就是厂商返回的 `usage`，指标口径不变。

这就是“用框架反而更好观测”的地方：你不需要在每个函数里手写计时，只要注册一个 handler，框架会在正确的时机调它。

> 💡 **小白提示**：`TracerCallbackHandler` 只汇总计数（`on_llm_end` / `on_tool_start` / `on_tool_end`）。时间线、span 层级、落库、上报 LangSmith，都可以在它的子类里加，接口不变。

### 2.3 指标：先把“好”定义清楚

“回答更好了”不是指标。下面这几个才是：

| 指标 | 口径 | 为什么需要 |
| --- | --- | --- |
| 意图准确率 | 预测意图 == 标注意图 | 路由错，后面全错 |
| 工具集合准确率 | 调用的工具集合 == 期望集合 | 该查余额却查了制度，答案必错 |
| `must_include` 命中率 | 答案包含全部必含关键词/数字 | 最便宜的事实校验 |
| 任务成功率 | 以上三项同时成立 | 唯一能进门禁的综合口径 |
| P50 / P95 延迟 | 中位数 / 95 分位 | 平均延迟会掩盖长尾卡顿 |
| token 与成本 | 输入/输出 token 按单价折算 | 决定这个功能能不能规模化 |

为什么用 P95 而不是平均值？假设 20 次请求里 19 次 0.2 秒、1 次 8 秒。平均值 0.59 秒，看起来还行；P95 会直接告诉你“有 5% 的用户在等 8 秒”。员工问年假这种事，超过 3 秒就会切走去问人。

> 📌 **考点**：面试里说“我把成功率从 35% 提到 90%”时，一定要补口径——“20 条 Golden Case，意图 + 工具集合 + 关键词三项全中才算成功，样本小，置信区间很宽”。只报数字不报口径，是最容易被追问翻车的点。

### 2.4 Golden Case：把线上问题冻成考题

Golden Case 就是“标准答案已写好”的固定考题集。一条用例至少包含：

```json
{"id": "G01", "input": "我还有几天年假？", "employee_id": "E1001",
 "expected_intent": "leave_balance", "expected_tools": ["get_leave_balance"],
 "must_include": ["13"], "category": "假期", "difficulty": "easy"}
```

`code/data/golden_cases.jsonl` 里有 20 条，覆盖假期、制度、招聘、薪酬、入职、工单、边界七类，其中 3 条是“应该转人工”的边界题。它们不是拍脑袋写的，而是从真实工单里挑的高频 + 高风险问题。

挑题有三条经验。第一，**从投诉里长出来**：每一条线上投诉都该变成一条用例，这是最便宜的回归防护。第二，**覆盖边界而不只是主路径**：20 条里必须有“该拒答的”“该要审批的”“该查版本的”，否则成功率再高也说明不了什么。第三，**期望值由业务方签字**：制度类的 `must_include` 是 HRBP 确认的数字和条款，不是工程师从代码里反推出来的——3.3 节里 baseline 把 2024 版答成 12 天，就是“期望值写对、实现错了”的典型，如果期望值跟着实现走，这个错误永远暴露不了。

> 💡 **小白提示**：`must_include` 不是“参考答案”，而是“答案里必须出现的证据锚点”。比如年假题必须出现 `13`，审批题必须出现 `审批`，边界题必须出现 `转人工`。它便宜、可自动跑，但很笨——第 4 节会看到它误判的样子。

### 2.5 回归门禁：改动能上线吗

有了 baseline（当前线上版本）和 improved（候选版本），就可以设门禁：

```text
              改动（Prompt / 检索 / 工具）
                        │
                        ▼
              ┌───────────────────┐
              │   跑 20 条 Golden  │
              └─────────┬─────────┘
                        ▼
        ┌───────────────────────────────┐
        │ improved 成功率 - baseline 成功率│
        └───────────────┬───────────────┘
                ≥ -2%   │    < -2%
                 ┌──────┴──────┐
                 ▼             ▼
              允许合并       打回重做
```

门禁不是“越高越好”，而是“不许明显变差”。为什么是 2%？20 条用例里 1 条就是 5 个百分点，所以 2% 实际意味着“一条都不许掉”。样本更大时可以放宽到 2%，样本小时应当直接要求“失败集合不扩大”。这句话在面试里很加分，因为它说明你知道指标的粒度限制。

## 3. 动手

> 🧩 **读法**：第 3 节的代码用于解释原理；本章实际运行的 demo 已改为 LangChain 版，完整代码见章末“LangChain 版关键实现”与 `code/` 对应脚本。


### 3.1 跑起来

```powershell
cd hr-agent-tutorial
python code/ch15_eval.py
```

这一章用了 LangChain 的四个抽象：`@tool` 把普通函数变成带 JSON Schema 的工具，`create_agent` 把“模型 → 工具 → 模型”的循环编译成一张 LangGraph 图，`MockChatModel` 让离线也能按脚本做决策，`TracerCallbackHandler` 在框架回调里采集指标。循环、工具调度、消息回填、回调分发都由框架负责；你写的只剩两件事：决策（离线用脚本模拟）和评测。

主代码只有这几行（完整代码见 `code/ch15_eval.py`）：

```python
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from common.lc import MockChatModel, TracerCallbackHandler, final_text

@tool
def get_leave_balance(employee_id: str) -> str:
    """查询员工当年年假余额。参数是工号，如 E1001。"""
    leave = (employee(employee_id) or {}).get("leave", {})
    total, used = leave.get("annual_total", 0), leave.get("annual_used", 0)
    return _json({"ok": True, "total": total, "used": used, "annual_remaining": total - used})

class CaseTracer(TracerCallbackHandler):
    """在公共回调上多记一条时间线，等价于一次运行的 Trace。"""

    def __init__(self) -> None:
        super().__init__()
        self.started = time.perf_counter()
        self.timeline: list[dict] = []

    def on_llm_end(self, response, **kwargs) -> None:
        super().on_llm_end(response, **kwargs)   # 父类负责累加 token
        self.timeline.append({"step": "llm", "ms": ...})

    def on_tool_start(self, serialized, input_str, **kwargs) -> None:
        super().on_tool_start(serialized, input_str, **kwargs)
        self.timeline.append({"step": f"tool:{serialized['name']}", "ms": ...})

def run_case(case: dict, version: str) -> dict:
    model = MockChatModel(script=make_script(case, version, meta))
    agent = create_agent(model=model, tools=TOOLS, system_prompt=SYSTEM_PROMPT)
    tracer = CaseTracer()
    state = agent.invoke({"messages": [HumanMessage(case["input"])]},
                         config={"callbacks": [tracer], "recursion_limit": 10})
    answer, summary = final_text(state), tracer.summary()
    ...
```

`make_script()` 是“模型”的替身：第一轮按问题决定调哪个工具，拿到 `ToolMessage` 后组织回答。接真实模型时不需要它——把 `MockChatModel` 换成 `get_chat_model()`，模型自己完成这两步，Agent 图与评测代码一行不改。

`create_agent` 内部到底做了什么？用伪代码看清：

**原理示意（伪代码）**

```python
messages = [SystemMessage(system_prompt), HumanMessage(question)]
for step in range(recursion_limit):
    ai = model.invoke(messages)                 # 触发 on_llm_end
    if not ai.tool_calls:                       # 没有工具调用 = 最终答案
        return {"messages": messages + [ai]}
    messages.append(ai)
    for call in ai.tool_calls:                  # 触发 on_tool_start / on_tool_end
        output = tool_by_name[call["name"]].invoke(call["args"])
        messages.append(ToolMessage(output, name=call["name"], tool_call_id=call["id"]))
```

`recursion_limit` 就是这个循环的步数上限，设成 10 意味着“最多 10 个图节点”，超了 LangGraph 会抛错而不是无限转。

检索与回答组织仍是自定义代码——框架不替你做业务：

```python
# 检索：baseline 查全库取第一条；improved 加同义词、只查 active 版本
def retrieve(question: str, version: str) -> list[dict]:
    query, pool = tokens(question), INDEX
    if version == "improved":
        for keyword, extra in SYNONYMS.items():
            if keyword in question.lower():
                query |= extra
        pool = [unit for unit in INDEX if unit["status"] == "active"]
    return sorted(pool, key=lambda unit: -sum(
        2.0 if re.fullmatch(r"[a-z0-9.\-]+", token) else 1.0
        for token in query & tokens(unit["section"] + "\n" + "\n".join(unit["lines"]))))[:1]

# 回答：两版话术不同，improved 必须带出处与审批提醒
def compose(intent: str, case: dict, results: list[tuple[str, dict]], version: str) -> str:
    strict, text = version == "improved", case["input"]
    ...
```

一次运行的真实输出（耗时每次不同，token 与成功率稳定）：

```text
=== 1. 三支柱：Trace / Log / Metric（20 条用例，61 个证据单元）===
TRACE improved-G02  14.79ms
  - llm (3.07ms)
  - tool:search_policy (6.73ms)
  - llm (14.79ms)
  llm=2 tool=1 token=362 error=0

[log] {"ts": "2026-11-15T19:09:16+08:00", "case_id": "G02",
 "intent": "leave_policy", "tools": ["search_policy"], "latency_ms": 16.913,
 "tokens": 362, "success": false}

=== 3. 核心指标对比 ===
成功        35.00%      90.00%
意图        70.00%      100.00%
工具集       70.00%      100.00%
关键词命中     35.00%      90.00%
P50(ms)   8.516       11.938
P95(ms)   22.484      16.913
平均token   292.050     280.800
平均LLM调用   2           1.9
总成本(元)    0.020       0.020
单任务成本约 0.001009 元（示例单价 2.0/8.0 元每百万 token）
```

### 3.2 两版的差别

- **baseline**：一套“看到关键词就分类”的规则。没有边界判断（`开除` 会被当成制度问题去检索），没有子意图（“提交年假申请”被当成“问年假政策”），回答不带出处、不提示审批。
- **improved**：先判边界；用“动词 + 宾语”区分查询与写操作；制度类回答必须带 `doc_id`、版本、小节；写操作一律只创建审批单。

结果：baseline 通过 7/20（35%），improved 通过 18/20（90%）。90% 不是满分，剩下 2 条正是这一章最值钱的部分。

### 3.3 bad case 表

```text
G02 5 年以上司龄有几天年假？  B=N I=N  I失败项=include
G03 年假没休完可以结转到什么时候？ B=N I=N  I失败项=include
```

两版都“答了”，也都没“答对”。看真实答案：

```text
baseline  G02 → 根据制度：司龄 年假天数；满 5 年及以上 12 天；不满 1 年 按入职月份折算，最多 5 天。
improved  G02 → 依据《年假与休假制度（2025 版）》（leave-2025，版本 2025.1）第「2.1 年假天数」节：
                年假天数按员工在本公司的连续司龄确定，以自然年为计算周期：；司龄 年假天数。
```

baseline 撞的是**版本问题**：它检索到已归档的 2024 版，答出“12 天”。improved 撞的是**检索权重问题**：同义词扩展把“司龄/天数/结转”都加进查询，2.1 小节的“主题句”得分最高，选行器挑走了表头和标题句，反而漏掉了“满 5 年及以上 → 15 天”那一行。

G03 同样：improved 把“结转”问题检索到了 2.1 节，答案里没有“3 月 31 日”。

## 4. 逐行拆解

### 4.1 为什么“证据单元”要带版本和状态

`build_index()` 把每个 `##` / `###` 小节切成一个单元，并且把 `doc_id`、`version`、`status` 一起存下来。没有这三样，检索只能比“字面像不像”；有了它们，才能做版本过滤和引用。

这里有个容易忽略的取舍：切片太细（一行一单元）会丢上下文，切片太粗（整篇文档）会稀释匹配。我们选“小节”粒度，是因为 HR 制度天然按条款组织，一个小节通常就是一个完整规则。

### 4.2 `must_include` 是把双刃剑

它足够便宜，所以能天天跑；但它只认字面。improved 对 G17“今天天气怎么样”的回答是“这个问题我无法回答，也不在 HR 服务台的服务范围内，已转人工”，命中了 `转人工`，判定成功；但它换一种说法——“这不在我的服务范围，已为您转接 HR 同事”——就会判失败，尽管业务上完全正确。

所以 `must_include` 的正确用法是：**校验硬事实**（数字、单号、条款号、审批人），不要校验措辞。措辞质量交给第 4.4 节的评委，且必须人工抽检。

### 4.3 分位数怎么算

`pct()` 用“排序后按比例取位”的朴素写法。20 个样本时，P95 取第 19 个（索引 18）。样本少时 P95 几乎等于最大值，波动很大——这也是为什么真实系统会看“P95 + 超时率”，而不是只看一个数。

> ⚠️ **生产提醒**：延迟必须在**真实链路**上量。本地离线 Mock 的 P95 是几十毫秒，看起来很美；接上真实模型后，P95 可能是 4～8 秒，其中 70% 花在模型首 token。用本地数字做容量规划，等于拿体温计测血压。

### 4.4 成本口径

成本用“估算 token × 示例单价”算：

```python
cost = prompt_tokens / 1e6 * PRICE_IN + completion_tokens / 1e6 * PRICE_OUT
```

两个必须讲清楚的点：一是 token 现在来自 `usage_metadata`（`MockChatModel` 是估算，`ChatOpenAI` 是厂商实际值），横向比较可以，真实计费看 `usage`；二是 `PRICE_IN/PRICE_OUT` 是示例单价，接真实模型前必须换成当月价格。

有意思的是，这一版 improved 的平均 token（280.8）反而比 baseline（292.1）低 4%。原因是两件事抵掉了“多写出处”的开销：拒答题只调一次模型（baseline 会多走一轮检索），且 improved 只引用 2 行证据（baseline 引用 3 行）。所以“可追溯性一定要多花钱”并不成立——**真正的成本在转人工和维护评测集**：每 20 条里有 3 条边界题被转人工，HR 同事要多处理 3 张工单。面试时这么讲，比“我们加了引用所以贵了”可信得多。

再算一笔业务账：假设服务台每天 2000 次咨询，本地脚本单次约 0.001 元，一天 2 元，看起来可以忽略。但真实模型单价是它的几十倍，单次可能到 1～3 分钱，一天就是 20～60 元，一个月 600～1800 元；再叠上重试、多轮工具调用和回流重跑，预算会再翻一倍。所以“成本”这一栏必须和“成功率”一起看：把一次失败回答的成本乘以返工率，往往比 token 账单本身更贵。

### 4.5 门禁与逐条 diff

门禁只比较整体成功率。这有个盲区：improved 可能“总分上升，但某条重要用例从通过变失败”。所以生产里除了门禁，还要看**逐条 diff**：把 baseline 通过、improved 失败的用例单独列出来，逐条解释。本章的 G02/G03 就属于“两版都失败”，不是回归，但同样是必须记录的 bad case。

## 5. 实验

**实验一：同义词是噪声源。** 把 `SYNONYMS` 整个清空（改成 `{}`），再跑一次。预期：improved 成功率从 90% 升到 95%，G03 翻绿（不再被 2.1 节抢走），但 G02 仍然失败——因为选行器还是挑走了标题句。这说明修 bad case 常常是“修一条、露一条”，必须整体看。

**实验二：给选行器加“数字偏好”。** 在清空同义词的基础上，让 `pick_lines` 在同分时优先含数字的行（例如按 `-len(re.findall(r"\d", line))` 做第二排序键）。预期：G02 也翻绿，improved 到 100%。此时再想一个问题：100% 只代表这 20 条，要不要补几条同义改写防止过拟合？

**实验三：把门禁改成延迟门禁。** 加一条 `assert improved["P95(ms)"] <= 3.0`（真实模型场景），把 `MAX_DROP` 改成 0.0，观察哪些改动会被打回。思考：为什么“成功率不许降、延迟也不许升”会逼着团队做真正的优化，而不是堆 Prompt。

**实验四：新增 5 条边界 case。** 例如“帮我查一下同事的工资”“把李娜的绩效改成 C”。预期：improved 的边界规则只覆盖了 `开除/解雇/辞退/裁员/天气/年会`，这些新题会被误路由，成功率下降——这就是评测集该扩的地方。

**实验五：换一种等价说法。** 把 G17 的期望关键词从 `转人工` 改成 `["转人工", "转接"]` 的同义词组，观察命中率变化。结论：`must_include` 的维护本身就是一项工程。

## 6. 工程化视角

- **接回调生态，而不是自己造 Trace**：`CaseTracer` 继承的是 LangChain 的 `BaseCallbackHandler`，同一套事件可以原样投给 LangSmith（设 `LANGCHAIN_TRACING_V2=true`）或 LangFuse，平台会帮你画 span 树、做样本回放、按版本对比。本章手写的 handler 只是让你看清“回调里到底有什么”。
- **LangServe / LangGraph Platform**：前者把 `agent` 直接暴露成 HTTP 接口，后者提供持久化 checkpointer、任务队列与人工审批；本章的 CLI 评测脚本对应它们的“离线评测集”能力，边界是：真实并发、鉴权、灰度要自己补。
- **日志分级与采样**：成功请求按 1% 采样，失败请求 100% 保留；日志字段固定下来（`case_id/intent/tools/latency_ms/tokens/success`），才能做聚合。
- **评测集治理**：Golden Case 要有人负责，跟着制度版本走；制度改版时，相关用例的期望答案必须一起改，否则评测会“稳定地错”。
- **评测集污染**：不要拿线上正在用的 Prompt 里的示例当考题，也不要把评测集喂给模型做 few-shot，否则指标虚高。
- **门禁接 CI**：把 `python code/ch15_eval.py` 挂到 PR 上，失败就阻止合并；再配一条“每日定时跑 + 结果落到看板”。
- **评委只做参考**：LLM-as-judge 适合做“粗筛”（把 1000 条里可疑的 50 条挑出来），不适合做“终审”。终审永远是人。
- **版本与回放**：每个 bad case 都要能 Replay（回放）——固定输入、固定工具返回值、固定 Prompt 版本，才能复现问题。做不到回放，讨论就会变成“我本地是好的”。

## 7. 常见坑

**坑 1：指标很好，但样本只有一个业务场景。**
现象：成功率 95%，上线后投诉照旧。原因：20 条里 15 条是制度问答，招聘、薪酬覆盖太少。解法：按 `category` 分层统计，每个类别单独设门禁。

**坑 2：`must_include` 写成整句。**
现象：答案语义正确却判失败。原因：把“参考答案”塞进了 `must_include`。解法：只放数字、编号、专有名词这类硬锚点。

**坑 3：用平均值代替分位数。**
现象：平均 0.6 秒，用户仍抱怨卡。原因：长尾被平均掉。解法：同时看 P50/P95/P99 与超时率。

**坑 4：评委分上涨就发布。**
现象：MockJudge 给 improved 4.30 分，人工抽检却发现 2 条错答。原因：评委偏爱“有引用、篇幅长”的答案（见 4.4）。解法：评委结论必须与人工抽检对齐，抽检比例不低于 10%。

**坑 5：Trace 里存了原文。**
现象：一次排查把员工薪资发到了公共群。原因：Trace 直接存了工具入参和返回。解法：入口脱敏、字段白名单、访问审计。

**坑 6：把评测脚本写成“只报喜”。**
现象：bad case 表永远为空。原因：期望值跟着实现改。解法：期望值由业务方确认，实现方不得单方面修改。

## 8. 练习

**练习 1（易）**：把 G02 的 `must_include` 从 `["15"]` 改成 `["15 天"]`，观察是否仍然失败。解释原因。

<details><summary>参考答案</summary>

仍然失败。improved 的答案里根本没有“15 天”，改关键词救不了检索问题。这说明：`must_include` 只能校验“有没有”，不能替代“该不该有”。正确动作是修检索/选行，而不是放宽标注。
</details>

**练习 2（中）**：给 `evaluate()` 增加按 `category` 分组的成功率，并打印成表。

<details><summary>参考答案</summary>

```python
def by_category(cases: list[dict], records: list[dict]) -> dict[str, float]:
    buckets: dict[str, list[bool]] = {}
    for case, record in zip(cases, records):
        buckets.setdefault(case["category"], []).append(record["checks"]["success"])
    return {name: sum(flags) / len(flags) for name, flags in buckets.items()}
```

在 `main()` 里对两个版本各调一次即可。注意小样本类别（如“工单”只有 1 条）的比率没有统计意义，要么合并类别，要么只报“通过/失败”。
</details>

**练习 3（中）**：把门禁改成“成功率不降 且 P95 不超过 3 秒”，并说明为什么本地跑这条门禁没有意义。

<details><summary>参考答案</summary>

```python
ok = drop <= MAX_DROP and reports["improved"]["metrics"]["P95(ms)"] <= 3000
```

本地是毫秒级，3 秒的门禁永远不会触发，它只在接真实模型后才有意义。这说明门禁阈值必须绑定运行环境，不能跨环境复制。
</details>

**练习 4（难）**：为 bad case 写修复方案并重跑。要求：G02 与 G03 都翻绿，且不引入新的失败。

<details><summary>参考答案</summary>

分两步，实测有效。第一步：清空 `SYNONYMS`（同义词扩展是噪声源），improved 从 90% 到 95%，G03 翻绿、G02 仍失败——因为选行器仍挑走标题句。第二步：让 `pick_lines` 在同分时优先含数字的行，例如把排序键改成 `(-命中数, -数字个数)`，G02 也翻绿，improved 到 100%。

但不要就此收工：100% 只代表这 20 条。补 5 条同义改写用例（“年假剩多少”“还能休几天假”）再跑一遍，确认没有过拟合；同时把这两处改动记进 bad case 复盘，说明“同义词扩展对制度表格式文档是有害的”。
</details>

## 9. 小结与下一章

三句话：

1. 可观测性不是“多打日志”，而是 Trace（看单次）、Log（看输入）、Metric（看趋势）三件事各就各位。
2. 评测的核心是口径：成功率必须拆成意图、工具、关键词三层，延迟必须看分位数，成本必须写明单价来源。
3. 门禁的作用不是证明“更好”，而是阻止“更差”；bad case 才是最该被复盘的资产。

现在，能力、可靠性、评测都齐了。下一章我们把这些零件装进一个真正能交付的东西：Vue 3 + FastAPI 的 HR 智能服务台。

---

## 10. 附：LangChain 版关键实现

> 本章实际运行的 demo 使用 **create_agent + TracerCallbackHandler**，完整代码见 `code/ch15_eval.py`。下面只保留骨架，方便你对照前面的原理示意阅读。

```python
from common.lc import TracerCallbackHandler

handler = TracerCallbackHandler()
state = agent.invoke({"messages": [{"role": "user", "content": case["input"]}]},
                     config={"callbacks": [handler]})
summary = handler.summary()   # llm_calls / tool_calls / tokens
```

| 本章概念 | LangChain / LangGraph 对应物 |
| --- | --- |
| 运行 | `create_agent` |
| 观测 | `BaseCallbackHandler` |
| 评测 | Golden Case + 自定义指标 |

> 🧩 **怎么读**：先看正文理解“为什么需要这一层”，再看上面的骨架理解“框架怎么表达这一层”，最后打开 `code/ch15_eval.py` 看完整实现与断言。面试时两条线都要能讲：原理线 + 框架线。
