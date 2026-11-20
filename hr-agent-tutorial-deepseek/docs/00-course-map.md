---
title: "00 | 从 HR 痛点出发：Agent 到底是什么"
slug: "course-map"
order: 0
part: "启程：从 HR 痛点理解 Agent"
minutes: 40
difficulty: "入门"
prerequisites: []
summary: "从 HR 共享服务中心的困境讲清 Agent 五要素，给出全书 18 章地图与运行环境。"
---
> 🧩 **框架说明**：本章 demo 基于 **LangChain 1.x + LangGraph 1.x**，核心 API：`create_agent`、`@tool`、`MockChatModel`。正文中的代码若标注“原理示意”（包括旧版 MockLLM / 手写循环片段），用于解释内部机制，不是最终运行代码；完整可运行代码见 `code/ch00_hello_agent.py`。


## 0. 本章你会得到什么

读完这一章，你应该能：

1. 用一句大白话说清 Agent 和聊天机器人的区别：聊天机器人只会回答，Agent 会查、会算、会按流程办事。
2. 画出 HR 智能服务台的五层架构，知道每一层由谁负责、坏了会怎样。
3. 跑通人生第一个 Agent：90 行代码，查年假余额 → 查制度条款 → 给出带引用的建议。
4. 知道全书 18 章分别在解决哪个工程问题，不再把“学 Agent”理解成“学写 Prompt”。
5. 在自己的电脑上准备好 Python 3.12 环境，后面每一章都能照着跑。

这一章不追求功能完整，先用 LangChain 的 `create_agent` 跑通第一个能“查余额、查制度、给建议”的 Agent；下一章再把框架内部拆开，看清那个循环。

## 1. 场景：200 条重复咨询，把 HR 拖成了客服

林芳是一家 3000 人公司的人力资源总监，管着 8 个人的 HR 共享服务中心（Shared Service Center，简称 SSC，就是集中处理全公司 HR 事务的团队）。她给团队算过一笔账：中心每天收到 200 多条员工咨询，其中 42% 集中在三类问题上——年假还剩几天、这个假怎么请、在职证明怎么开。每一单平均处理 6 分钟，8 个人一天里有将近 3 个小时在做重复劳动。

真正让她下决心的是去年 11 月的一件小事。技术部后端工程师张伟（工号 E1001）周三晚上 9 点发消息问：“我下个月想休 3 天年假，够不够？需要提前几天申请？”消息第二天上午才被看到，HR 专员郑爽凭印象回复“提前 2 个工作日就行”——她记得 2024 版制度是这么写的。可 2025 版早就改成 3 个工作日，结转也从“3 天、次年 1 月 31 日”变成“5 天、次年 3 月 31 日”。张伟按旧口径订了机票，申请被退回，改签损失 400 多元，在员工群里吐槽“HR 自己都说不清制度”。那个月类似投诉有 3 起。

林芳试过两个方案。第一个是加人，但编制批不下来。第二个是买一套“知识库问答”：把制度文档灌进去，员工提问，系统检索出相关段落，再让大模型组织成回答。Demo 很惊艳，制度背得比人还熟。可上线一周就被员工问倒了：

- “我还剩几天年假？”——知识库只知道制度写了 15 天，不知道张伟今年已经休了 2 天。系统只能回答“请登录 HR 系统查询”。
- “帮我提交下周三的请假申请。”——它连 HR 系统的门都进不去，只能说“请前往系统提交”。
- “2024 版和 2025 版到底哪个算数？”——它把两个版本一起召回，回答里同时出现 2 个工作日和 3 个工作日，员工更糊涂了。

问题很清楚：**员工要的不是一段解释，而是一件被办成的事**。要办成事，系统必须能查实时数据（余额）、能查到唯一有效的制度（版本）、能按规则算（还剩几天、够不够）、必要时还能提交一个待办（帮你建请假单）。会说话不够，还得会办事。

## 2. 概念：Agent 是把“会说话”接上“会办事”

### 2.1 先看清大模型的能力边界

大语言模型（Large Language Model，简称 LLM，中文常叫“大模型”）可以先粗略理解成一个读过海量文本、特别擅长“接下一句”的程序。你给它一段话，它根据概率一个词一个词地往下写 Token（Token 是模型处理文本的最小单位，中文里 1 个汉字大约等于 1 个 Token），写出通顺、相关、看起来很有道理的内容。

它强在语言：理解你的问题、总结长文档、把口语转成结构化字段、把制度条款改写成员工能懂的话。它弱在三件事：

- **不知道你的实时数据**。张伟还剩几天年假，不在它的训练数据里。
- **不会产生副作用**。它没法真的在 HR 系统里建一条请假单，它只能“说”要做。
- **不稳定**。同一个问题问两次，措辞可能不同；遇到模糊信息，它倾向于编一个看起来合理的答案，这就是“幻觉”。

所以正确的心态不是“让模型什么都会”，而是“让模型负责它擅长的判断和表达，把查数据、算数字、改状态交给代码”。

> 💡 **小白提示**：本书默认用 `MockChatModel` 离线跑。它不是真实大模型，而是一个按剧本逐条返回固定内容的假模型。这样你不用联网、不用 API Key、不花钱，就能把循环、工具、校验、评测这些结构跑通；接真实模型时只改环境变量，代码一行不动。

### 2.2 Agent = 目标 + 循环 + 工具 + 记忆 + 边界

“Agent”（智能体）这个词被用得很泛。本书给它一个能落地、能验收的定义，五个要素缺一不可：

```text
Agent = 目标（Goal）   要解决的具体问题，例如“判断张伟能不能休 3 天年假”
      + 循环（Loop）   想一步 → 做一个动作 → 看结果 → 再想，直到能回答
      + 工具（Tools）  能真正改变状态的函数：查余额、查制度、建工单、发审批
      + 记忆（Memory） 这次对话说过什么、这个员工是谁、公司当前用哪版制度
      + 边界（Boundary）不能做什么、什么情况必须拒答、什么操作必须人工签字
```

拿张伟的问题对照：

- **目标**：不是“聊年假”，而是“判断够不够 + 说清怎么请”。目标越具体，验收越容易。
- **循环**：先查余额，看到 13 天；再查制度，看到“提前 3 个工作日”；最后综合成一句话。一次模型调用做不到，因为它必须先看到工具结果才能决定下一步。
- **工具**：`get_leave_balance` 读 HR 系统，`search_policy` 读制度库。模型只负责“决定调用哪个、传什么参数”，真正执行的是你的 Python 函数。
- **记忆**：至少要知道问话的人是 E1001，而不是让员工每次自报工号；还要知道当前生效的是 2025 版制度。
- **边界**：可以告诉员工怎么请，但不能替他提交；涉及薪资、解雇、合同变更，必须转人工审批。

记住一句话：**模型负责“想”，代码负责“做”和“不许做”**。这句话会贯穿全书。

### 2.3 五层架构：一个 HR 智能服务台长什么样

把上面五要素放进一个真实系统，就是下面五层。后面第 16 章的综合项目，就是把这五层真的写出来。

```text
┌──────────────────────────────────────────────────────────┐
│ 交互层   企业微信 / 网页工作台 / 邮件 / 电话转写           │  员工在哪问
├──────────────────────────────────────────────────────────┤
│ Agent 层 意图识别 · 任务规划 · 工具选择 · 回答生成 · 拒答  │  本章的循环住这里
├──────────────────────────────────────────────────────────┤
│ 工具层   查余额 · 查制度 · 建工单 · 查审批 · 发通知        │  真正“办事”的手脚
├──────────────────────────────────────────────────────────┤
│ 知识层   制度库（带版本）· 组织架构 · 员工数据 · 历史工单   │  回答的依据
├──────────────────────────────────────────────────────────┤
│ 治理层   权限 · 脱敏 · 审计 · 评测 · 人工兜底 · 成本上限    │  出了事谁负责
└──────────────────────────────────────────────────────────┘
```

初学者最容易只盯着 Agent 层，觉得“Prompt 写好了就赢了”。实际项目里，工具层和治理层才决定能不能上线：参数错了会把年假扣成负数，版本混了会答错口径，没有审计则出了纠纷说不清责任。

### 2.4 一次请求到底怎么走

张伟那句话进入系统后，真正的执行过程是这样的：

```text
员工："我下个月想休 3 天年假，够不够？需要提前几天申请？"
        │
        ▼
  ┌────────────────┐  ① 模型说：调用 get_leave_balance(E1001)
  │   Agent Loop   │ ─────────────────────────────┐
  │  最多 4 步      │                              ▼
  │                │                    ┌───────────────────┐
  │                │  ② 观察：剩 13 天   │ get_leave_balance │
  │                │ ◀────────────────── │ 读 employees.json │
  └────────────────┘                    └───────────────────┘
        │  ③ 模型说：调用 search_policy("申请")
        │ ─────────────────────────────┐
        │                              ▼
        │                    ┌───────────────────┐
        │  ④ 观察：3 个工作日 │  search_policy    │
        │ ◀────────────────── │ 只查 active 制度  │
        ▼                    └───────────────────┘
  回答："还剩 13 天，够休 3 天；按 HR-LEAVE-2025 第 2.3 条，提前 3 个工作日申请"
  + 引用（文档编号、版本、条款）+ 待办（去系统提交，主管审批）
```

注意两个细节。第一，模型每次只决定“下一步做什么”，看不到未来；是循环让它一步步逼近答案。第二，回答必须带文档编号、版本和条款位置——这不是锦上添花，而是硬要求：员工拿着回答和主管争论时，你得指出依据在哪。

### 2.5 边界：哪些事必须有人签字

Agent 越能干，越要先划红线。本书反复强调三类边界：

- **读多写少**：查余额、查制度、查工单可以自动化；提交申请、改薪资、发 offer、解除合同必须有审批。
- **无证据就拒答**：检索不到有效条款时，回答“我没查到，帮你转 HR”，而不是编一条。宁可不答，不可答错。
- **个人信息最小化**：回答里只展示必要字段，手机号、身份证号、薪资默认脱敏；每次敏感操作留审计日志。

这就是 Human-in-the-loop（人在环路中，简称 HITL）：关键节点让人确认。它不是能力不足的妥协，而是责任归属的设计。

> ⚠️ **生产提醒**：不要给 Agent “直接执行敏感写操作”的权限，哪怕测试时很顺。正确做法是让 Agent 生成一张待审批单，人点了同意再执行；审批人、时间、依据都要落库。第 12 章会带你把这条链路写出来。

### 2.6 全书地图：18 章分别在解决什么

本书分五部分，共 18 章。你可以把它当成一条从“看懂”到“能交付”的路线，而不是 18 篇互不相干的文章。

| 部分 | 章 | 主题 | 一句话产出 |
| --- | --- | --- | --- |
| 一 启程 | 00 | 课程地图 | 看懂 Agent 是什么、为什么 HR 需要它 |
| 一 启程 | 01 | LLM 与 Prompt | 把 JD 稳定抽成结构化岗位卡片 |
| 二 单 Agent | 02 | Agent Loop | 用 LangGraph 搭出“想 → 做 → 看 → 再想”的循环 |
| 二 单 Agent | 03 | Tool Calling | 工具可注册、可校验、可授权 |
| 二 单 Agent | 04 | Planning | ReAct 与计划执行，失败会重规划 |
| 二 单 Agent | 05 | Workflow | 确定的事交给状态机，不靠模型自觉 |
| 二 单 Agent | 06 | Memory | 记住员工、历史与偏好，且能遗忘 |
| 二 单 Agent | 07 | Context Engineering | 给上下文做预算，超了按优先级裁剪 |
| 三 知识工程 | 08 | RAG 基础 | 从员工手册到带引用的回答 |
| 三 知识工程 | 09 | RAG 进阶 | 混合检索、版本治理、引用质检 |
| 三 知识工程 | 10 | 图谱与 Text2SQL | 查组织、技能与结构化数据 |
| 四 可靠性 | 11 | 可靠性工程 | 超时、重试、幂等、熔断、降级 |
| 四 可靠性 | 12 | HITL 与权限 | 敏感操作有人签字，PII 脱敏 |
| 四 可靠性 | 13 | Multi-Agent | 招聘、面试、合规三个角色协作 |
| 四 可靠性 | 14 | Sandbox 与长任务 | 隔离执行模型代码，断点续跑 |
| 四 可靠性 | 15 | 可观测性与评测 | 用数据证明 Agent 变好了 |
| 五 实战 | 16 | 综合项目 | Vue 3 + FastAPI 的 HR 智能服务台 |
| 五 实战 | 17 | 从教程到 Offer | 作品集、面试与 90 天进阶 |

前两部分打地基：第 00、01 章看见循环、学会和模型对话；第 02 到 07 章把循环、工具、计划、流程、记忆、上下文逐个工程化。第三部分解决“知识从哪来”，第四部分解决“怎么不出事”，第五部分把能力组装成可演示的项目。

## 3. 动手：90 行，看见循环

> 🧩 **读法**：第 3 节的代码用于解释原理；本章实际运行的 demo 已改为 LangChain 版，完整代码见章末“LangChain 版关键实现”与 `code/` 对应脚本。


本章代码在 `code/ch00_hello_agent.py`。在仓库根目录运行：

```powershell
python code/ch00_hello_agent.py
```

它准备一句话和两个工具，让 `MockChatModel` 按剧本发起两次工具调用，把结果回填给模型，最后打印回答与调用树。下面是**原理示意（旧版手写实现）**，用于理解内部机制；实际运行的是章末的 LangChain 版：

```python
"""第 00 章：最小 Agent —— 员工一句话，模型先查余额、再查制度、最后给建议。

运行：python code/ch00_hello_agent.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.data import all_policy_documents, employee
from common.llm import MockLLM, assistant, system, tool_message, tool_schema, user
from common.trace import Tracer
QUESTION = "我下个月想休 3 天年假，够不够？需要提前几天申请？"

def get_leave_balance(employee_id: str) -> dict:
    """工具 1：查假期余额。生产环境里这是一次 HRIS 接口调用。"""
    person = employee(employee_id)
    if person is None:
        raise ValueError(f"工号 {employee_id} 不存在")
    leave = person["leave"]
    return {
        "employee_id": employee_id,
        "name": person["name"],
        "annual_remaining": leave["annual_total"] - leave["annual_used"],
        "sick_remaining": leave["sick_total"] - leave["sick_used"],
    }

def search_policy(keyword: str) -> list[dict]:
    """工具 2：只在“生效中”的制度里找原文，返回带编号和版本的片段。"""
    hits: list[dict] = []
    for doc in all_policy_documents():
        if doc["status"] != "active":
            continue  # 旧版本制度不参与回答，避免口径冲突
        for line in doc["content"].splitlines():
            if keyword in line and len(line.strip()) > 4:
                hits.append({"doc_id": doc["doc_id"], "version": doc["version"], "text": line.strip()})
    return hits[:2]

TOOLS = {"get_leave_balance": get_leave_balance, "search_policy": search_policy}
SCHEMAS = [
    tool_schema("get_leave_balance", "查询员工的年假与病假余额", {"employee_id": {"type": "string"}}, ["employee_id"]),
    tool_schema("search_policy", "检索生效中的 HR 制度原文", {"keyword": {"type": "string"}}, ["keyword"]),
]
# MockLLM 按顺序念台词：第 1 步查余额，第 2 步查制度，第 3 步给回答。
SCRIPT = [
    {"tool_calls": [{"name": "get_leave_balance", "arguments": {"employee_id": "E1001"}}]},
    {"tool_calls": [{"name": "search_policy", "arguments": {"keyword": "申请"}}]},
    {"content": "张伟，你今年还剩 13 天年假，休 3 天够用。按 HR-LEAVE-2025（2025.1）第 2.3 条，"
     "需提前 3 个工作日提交申请；连续休假不超过 3 天由直属主管审批。"},
]

def main() -> None:
    print("=== 1. 员工提问 ===\n" + QUESTION)
    messages = [
        system("你是 HR 服务台助手：回答前必须先用工具核实余额与制度，禁止凭记忆作答；拿不到证据就说不知道。"),
        user(QUESTION),
    ]
    llm, tracer = MockLLM(SCRIPT), Tracer("ch00")
    reply = ""
    for step in range(1, 5):  # 最多 4 步：没有这个上限，模型可能一直查下去
        with tracer.span(f"step-{step}"):
            response = llm.chat(messages, tools=SCHEMAS)
            tracer.record_llm(response)
            messages.append(assistant(response.content, response.tool_calls))
            if not response.tool_calls:
                reply = response.content or ""
                print(f"[step {step}] 模型给出最终回答，循环结束")
                break
            for call in response.tool_calls:
                print(f"[step {step}] 模型要求调用 {call.name}({call.arguments})")
                payload = TOOLS[call.name](**call.arguments)  # 真正干活的是这行 Python
                print(f"         -> {json.dumps(payload, ensure_ascii=False)[:90]}")
                messages.append(tool_message(call, payload))

    print("\n=== 2. 最终回答 ===\n" + reply)
    print("\n=== 3. 调用树 ===")
    tracer.print_tree()

    assert "13 天" in reply and "3 个工作日" in reply, "回答必须同时用到余额和制度两个工具的结果"
    tool_messages = [m for m in messages if m["role"] == "tool"]
    assert len(tool_messages) == 2 and all(m["tool_call_id"] for m in tool_messages), "每个 tool_call 都要有配对"
    assert tracer.metrics["llm_calls"] == 3, "3 步：查余额、查制度、给回答"
    print("\n全部断言通过：循环、工具、消息配对都正常。")

if __name__ == "__main__":
    main()
```

运行后你会看到（Trace ID 每次不同）：

```text
=== 1. 员工提问 ===
我下个月想休 3 天年假，够不够？需要提前几天申请？
[step 1] 模型要求调用 get_leave_balance({'employee_id': 'E1001'})
         -> {"employee_id": "E1001", "name": "张伟", "annual_remaining": 13, "sick_remaining": 4}
[step 2] 模型要求调用 search_policy({'keyword': '申请'})
         -> [{"doc_id": "leave-2025", "version": "2025.1", "text": "### 2.3 申请流程"}, {"doc_id": "leave-...
[step 3] 模型给出最终回答，循环结束

=== 2. 最终回答 ===
张伟，你今年还剩 13 天年假，休 3 天够用。按 HR-LEAVE-2025（2025.1）第 2.3 条，需提前 3 个工作日提交申请；连续休假不超过 3 天由直属主管审批。

=== 3. 调用树 ===

TRACE 26ce3da198b1  ch00  2ms
- ch00 (2ms)
  - step-1 (0ms)
    · llm_call
  - step-2 (1ms)
    · llm_call
  - step-3 (1ms)
    · llm_call
  llm=3 tool=0 token=576 error=0

全部断言通过：循环、工具、消息配对都正常。
```

输出里有三个信号值得注意：`13` 是工具算出来的，不是模型编的；`3 个工作日` 带着 `leave-2025` 编号和 `2025.1` 版本；调用树显示正好 3 次模型调用、2 次工具调用。

## 4. 逐行拆解：五个“为什么”

代码只有 90 行，但每一行都在回答一个工程问题。

**第一，为什么系统提示要写“必须先用工具”？** 因为对模型来说，“凭记忆回答”永远比“调工具”省事。你不明确要求，它就会直接说“年假一般 10 到 15 天”。这句话把“先查后答”变成了规则，后面第 15 章还会用评测去验证它是否真的被遵守。

**第二，为什么先 `append(assistant(...))` 再执行工具？** 消息历史要还原真实发生过的对话：模型说了“我要调 `get_leave_balance`”，这句话必须先进入历史，后面那条 `tool` 消息才有东西可以回应。顺序反了，就变成“工具结果凭空出现”，下一轮请求会因消息序列非法被拒。第 02 章会把这条约束写成检查函数。

**第三，为什么用 `for step in range(1, 5)` 而不是 `while True`？** 因为模型可能永远觉得“信息还不够”。真实事故里，一个没有步数上限的循环能在几分钟内烧掉几十美元。4 是本章的预算，第 02 章会把它变成参数 `max_steps`，并补齐超时与终止原因。

**第四，为什么 `search_policy` 要过滤 `status != "active"`？** 知识库里同时躺着 2024 版和 2025 版：结转一个写“3 天、1 月 31 日”，一个写“5 天、3 月 31 日”；申请时限一个 2 个工作日、一个 3 个工作日。不过滤，模型会把两个口径混在一起答，第 09 章专门讲版本治理。

**第五，`MockChatModel` 到底是什么？** 它按 `SCRIPT` 顺序返回内容：第一次“调用余额工具”，第二次“调用制度工具”，第三次一段写死的回答。它不读你的问题，也不读工具结果。所以本章验证的是**循环结构**，不是模型能力；真实模型才会根据 observation 组织语言。不说清这一点，你会误以为“Agent 已经会思考了”。

> 📌 **考点**：面试官常问“Agent 和 Workflow 的区别”。一个好的回答是：Agent 由模型在循环里动态决定下一步调用什么工具，适合步骤不确定的任务；Workflow 由代码预先定义状态与转移，适合合规要求高、步骤确定的流程。两者常常混用，第 05 章会给出边界。

## 5. 实验：改三个地方，看循环怎么变

**实验一：把最大步数改成 1。** 把 `range(1, 5)` 改成 `range(1, 2)` 再运行：第 1 步查完余额循环就结束，`reply` 为空，断言直接失败。这就是“步数预算不够”的真实表现——不是模型笨，是你不给第二轮机会。生产环境要返回“处理中，请稍后”或转人工，而不是空回答。

**实验二：把工具换成“查工单”。** 在 `code/data/tickets.json` 里有 10 条工单，字段包括 `id`、`employee_id`、`status`、`sla_hours`。写一个 `get_tickets(employee_id)` 工具，返回该员工的工单列表；把 `SCRIPT` 的第一步换成调用它，观察模型如何在“查余额”和“查工单”之间做选择。提示：工具描述写得越具体，模型选错的概率越低。

**实验三：给 Agent 加一条“无证据必须拒答”的规则。** 把系统提示改成“如果 `search_policy` 返回空列表，必须回答‘没查到有效条款，帮你转 HR’，不得自行解释制度”，再把关键词换成不存在的词（如“育儿假补贴”）。当前代码会返回空列表，模型仍可能编造——这正是第 08、09 章要解决的拒答问题。

## 6. 工程化视角：这 90 行离生产还差什么

循环能跑，但它是个“玩具”。放到生产环境至少要补六件事：

1. **终止条件**：只有步数上限不够，还要有超时、工具连续失败、重复调用检测（第 02、11 章）。
2. **工具治理**：参数校验、错误码、读写分离、幂等、权限（第 03、12 章）。
3. **状态与流程**：入职、审批这类流程不能靠模型自觉，要用状态机（第 05 章）。
4. **知识与引用**：制度检索、版本过滤、引用校验、证据不足拒答（第 08、09 章）。
5. **记忆与上下文**：员工画像、历史摘要、Token 预算（第 06、07 章）。
6. **可观测与评测**：Trace、指标、Golden Case、回归门禁（第 15 章）。

还有一个容易忽略的点：`MockChatModel` 让结果完全确定，对教学和测试是优点，对真实业务是缺点。真实模型有随机性，同一句话可能两次给出不同工具调用，生产系统必须假设它会犯错，用校验、重试、评测兜底。

## 7. 常见坑

**现象：终端里中文全是乱码。**
原因：Windows PowerShell 默认代码页是 GBK，而管道输出被当成 UTF-8 解码。
解法：先执行 `chcp 65001`，或设置 `$env:PYTHONIOENCODING="utf-8"` 再运行。

**现象：以为 `MockChatModel` 是真模型，改了问题它却答得一模一样。**
原因：`MockChatModel` 是确定性脚本，按顺序念台词，不读输入。
解法：把它当“可编程的假模型”用于测试循环；想体验真实推理，按附录切到真实模型。

**现象：循环偶尔卡住，或者跑很久不结束。**
原因：只写了 `while True`，没有步数上限，也没有超时。
解法：任何循环都必须有 `max_steps` 和总体超时；本章用 `range(1, 5)` 做了最朴素的示范。

**现象：Token 消耗远超预期。**
原因：把整篇制度、整份员工档案塞进 Prompt；工具返回也原样回填。
解法：工具只返回必要字段和片段（本章 `hits[:2]`），长文本先摘要；第 07 章会讲上下文预算。

**现象：回答里没有引用，出了纠纷说不清。**
原因：系统提示没要求，工具返回也没带文档编号。
解法：制度类工具必须返回 `doc_id`、`version`、条款位置；回答模板强制带引用，第 09 章还会做引用校验。

## 8. 练习

**练习 1（热身）**：不看代码，用自己的话写出张伟这个问题经过的 3 个步骤，并说明每一步的输入和输出。

**练习 2**：把 `get_leave_balance` 的返回值加一个 `annual_total` 字段，并在最终回答里体现“总共 15 天、已休 2 天、剩 13 天”。改完运行，确认断言仍然通过。

**练习 3**：把最大步数改成 2，观察输出与断言，然后设计一个“步数用完”时的兜底回答（例如“我查到余额了，但还没核对制度，先帮你转 HR”）。

**练习 4（进阶）**：给 Agent 加第三个工具 `get_pending_tickets(employee_id)`，读取 `code/data/tickets.json`，返回该员工未完成的工单。要求：工具描述里写清“只读”，并在系统提示里规定“涉及证明、报销的问题先查工单”。

**练习 5（思考）**：如果员工问“我要请 10 天年假，能不能批”，而制度规定“连续超过 5 个工作日需交接”，Agent 应该直接回答“可以”吗？请写出你的判断依据和需要补充的工具。

<details><summary>参考答案</summary>

**练习 1**：第一步，模型看到问题和工具列表，决定调用 `get_leave_balance(E1001)`；输入是工号，输出是 `annual_remaining=13`。第二步，模型决定调用 `search_policy("申请")`；输入是关键词，输出是 `leave-2025` 的条款片段。第三步，模型综合两个 observation，生成带引用的回答。三次模型调用、两次工具执行，共 3 步。

**练习 2**：在返回字典里加 `"annual_total": leave["annual_total"]`、`"annual_used": leave["annual_used"]`，并把 `SCRIPT` 最后一段改成“你今年年假共 15 天，已休 2 天，还剩 13 天……”。断言里的 `13 天` 与 `3 个工作日` 仍应出现。

**练习 3**：把 `range(1, 5)` 改成 `range(1, 3)`，第 2 步查完制度后循环结束，`reply` 为空，第三条断言失败。兜底做法是在循环结束后判断 `reply` 是否为空，为空则返回“已查到部分信息，但未完成核对，已为你转 HR”，并把 `messages` 一起交给人工。

**练习 4**：仿照 `get_leave_balance`，用 `common.data.tickets()` 取数，过滤 `employee_id` 且 `status != "resolved"`；在 `SCHEMAS` 补一条“查询员工未完成工单（只读）”；系统提示加“证明、报销类问题先查工单，再查制度”。

**练习 5**：不能直接回答“可以”。制度规定连续休假超过 5 个工作日需完成工作交接，10 天显然超过；还需知道交接人是否已指定、部门负责人是否审批。正确做法是先查制度确认规则，再回答“需要交接并走部门负责人审批”，把“提交申请”留给员工或审批流，而不是替员工承诺结果。

</details>

## 9. 小结与下一章

这一章我们做了三件事：用真实到有点疼的 HR 场景说明“会说话”和“会办事”的差距；把 Agent 拆成目标、循环、工具、记忆、边界五要素并放进五层架构；用 90 行代码让你亲眼看见“模型决策 → 工具执行 → 结果回填 → 再决策”的循环。

请记住三句话：模型负责想，代码负责做和不许做；任何循环都必须有预算；没有引用的 HR 回答，等于没有回答。

下一章我们补最基础的基本功：Token、messages、temperature，以及怎么让模型把一份 JD 稳定地变成一条能入库的数据。

## 附录：环境准备（5 分钟）

**第一步，确认 Python 版本。** 本书要求 Python 3.12：

```powershell
python --version
# 期望输出：Python 3.12.x
```

如果电脑上有多个版本，Windows 可以用 `py -3.12 --version` 指定。macOS / Linux 用 `python3.12 --version`。

**第二步，安装依赖。** 本书只用标准库加 `pydantic`，综合项目会额外用到 FastAPI 与 Vue 3：

```powershell
python -m pip install -r code/requirements.txt
```

**第三步，运行本章代码。** 在仓库根目录执行：

```powershell
python code/ch00_hello_agent.py
```

看到“全部断言通过”就说明环境没问题。脚本已把 `code/` 加进搜索路径，在任何目录下都能运行。

**第四步（可选），切换真实模型。** 本书默认离线。想接真实模型时，设置四个环境变量即可，代码不用改：

```powershell
$env:HR_LLM_MODE="openai"
$env:HR_LLM_API_KEY="你的 Key"          # 不要写进代码，也不要提交到仓库
$env:HR_LLM_BASE_URL="https://api.deepseek.com/v1"
$env:HR_LLM_MODEL="deepseek-chat"
```

`common/lc.py` 的 `get_chat_model()` 会据此选择 `MockChatModel` 或 `ChatOpenAI（OpenAI 兼容）`（任何 OpenAI 兼容接口都行）。真实模型会产生费用、结果不再确定；本书断言按 Mock 的确定性输出写，切换后部分断言不成立是正常的。

> ⚠️ **生产提醒**：API Key 只放环境变量或密钥管理服务，不要写进代码、日志、前端。教程仓库里出现 Key，等同于把公司账号密码公开。

---

## 10. 附：LangChain 版关键实现

> 本章实际运行的 demo 使用 **create_agent + @tool**，完整代码见 `code/ch00_hello_agent.py`。下面只保留骨架，方便你对照前面的原理示意阅读。

```python
from langchain.agents import create_agent
from langchain_core.tools import tool
from common.lc import MockChatModel

@tool
def get_leave_balance(employee_id: str) -> str:
    """查询员工年假/病假余额。"""
    ...

agent = create_agent(
    model=MockChatModel(script=[...]),
    tools=[get_leave_balance, search_policy],
    system_prompt=SYSTEM_PROMPT,
)
state = agent.invoke({"messages": [{"role": "user", "content": "我还有几天年假？"}]})
print(state["messages"][-1].content)
```

| 本章概念 | LangChain / LangGraph 对应物 |
| --- | --- |
| Agent 循环 | `create_agent` |
| 工具 | `@tool` |
| 离线模型 | `MockChatModel(BaseChatModel)` |

> 🧩 **怎么读**：先看正文理解“为什么需要这一层”，再看上面的骨架理解“框架怎么表达这一层”，最后打开 `code/ch00_hello_agent.py` 看完整实现与断言。面试时两条线都要能讲：原理线 + 框架线。
