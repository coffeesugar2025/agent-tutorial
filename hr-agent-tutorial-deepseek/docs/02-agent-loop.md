---
title: "02 | Agent Loop：让模型学会「再来一轮」"
slug: "agent-loop"
order: 2
part: "单 Agent 核心"
minutes: 55
difficulty: "入门"
prerequisites: ["01"]
summary: "用 LangGraph 搭出 Agent 循环：StateGraph、ToolNode、四类终止条件与 Trace。"
---
> 🧩 **框架说明**：本章 demo 基于 **LangChain 1.x + LangGraph 1.x**，核心 API：`StateGraph`、`ToolNode`、`tools_condition`。正文中的代码若标注“原理示意”（包括旧版 MockLLM / 手写循环片段），用于解释内部机制，不是最终运行代码；完整可运行代码见 `code/ch02_agent_loop.py`。


## 0. 本章你会得到什么

读完这一章，你应该能：

1. 用 `StateGraph` 搭出一个显式循环：模型返回工具调用 → `ToolNode` 执行 → 结果回填 → 再问模型，直到拿到答案。
2. 设计四类终止条件：拿到最终答案、达到最大步数、工具连续失败、重复调用同一工具。
3. 说清 messages 里 `assistant(tool_calls)` 和 `tool` 消息的配对关系，知道少一条会怎样。
4. 用 `Tracer` 打印一棵调用树，看见每一轮发生了什么、花了多少 Token。
5. 拿到结构化的 `AgentResult`，而不是一个字符串——这是从脚本走向工程的分水岭。

第 00 章你用 `create_agent` 跑通过一次循环，但那一版把“怎么循环”交给了框架。这一章我们用 `StateGraph` 把循环显式搭出来：模型节点、工具节点、守卫节点、四类终止条件，每一步都能在图里看见。代码约 250 行，重点不是行数，而是你能指着图说出“为什么停在这里”。

## 1. 场景：一句话背后，是三次决策

张伟这次没在群里问，而是打开了公司新上线的 HR 服务台。他输入：“我下个月想休 3 天年假，够不够？需要提前几天申请？”

这句话看起来简单，其实包含三个子问题：

1. 我还剩几天年假？——需要查员工数据，张伟工号 E1001，年假总额 15 天、已休 2 天，剩 13 天。
2. 制度允不允许？——需要查 2025 版年假制度：年假最小请假单位 0.5 天；至少提前 3 个工作日申请；连续休假不超过 3 天由直属主管审批，超过 3 天需部门负责人审批。
3. 综合起来怎么答？——13 天大于 3 天，够休；但要提前 3 个工作日提交；3 天正好在“不超过 3 天”的边界内，所以只需直属主管审批。

上一章的模型能一次调用抽出一张岗位卡片，因为所有信息都在 Prompt 里。这次不行：余额在数据库里，制度在文档库里，模型两样都看不到。它必须先“要”一次数据，看到结果，再决定“要”什么，最后综合。

这正是 Agent Loop 要解决的问题。没有循环，你只能二选一：

- 只查余额：回答“你还有 13 天”，但员工接着问“那怎么请”；
- 只查制度：回答“提前 3 个工作日”，但员工接着问“那我够不够”。

两次追问，就是两次人工介入。HR 共享服务中心最怕的就是这个：一个本来 1 分钟能解决的问题，因为答案不完整，变成了 3 轮对话。

更麻烦的是异常情况。张伟可能手滑输错工号，工具查不到人；制度库里可能暂时没有“年假”相关条款；模型可能绕圈子，反复调用同一个工具。演示版遇到这些会直接崩溃，生产版必须把错误变成“观察结果”，让循环自己恢复，或者在必要时干净地停下。

这一章的目标很明确：让循环**跑得住**。跑得住的意思是——正常情况能收敛，异常情况不崩溃，失控情况能刹车，而且你能从 Trace 里复盘每一次决策。

## 2. 概念：循环、消息、终止与追踪

### 2.1 循环的本质：一个带预算的状态机

大模型本身是无状态的。它不记得上一次调用说了什么，你每次都得把完整历史传进去。所谓“Agent 会思考”，其实是代码在替它维护状态：把历史带上、把工具结果写回、再问一次。

所以 Agent Loop 本质上是一个状态机：

```text
                    ┌──────────────────────────────┐
                    │                              │
                    ▼                              │
          ┌──────────────────┐                     │
   开始 ─▶│  LLM_DECIDE      │  模型看历史，决定：  │
          │  （模型决策）     │  ① 直接回答          │
          └────────┬─────────┘  ② 调用工具          │
                   │                                │
        ┌──────────┴──────────┐                     │
        ▼                     ▼                     │
┌───────────────┐    ┌──────────────────┐           │
│  FINAL_ANSWER │    │  TOOL_EXEC       │           │
│  结束，返回   │    │  执行工具，拿结果 │           │
└───────────────┘    └────────┬─────────┘           │
                              │                     │
                              ▼                     │
                     ┌──────────────────┐           │
                     │  OBSERVE         │───────────┘
                     │  结果写回历史     │  带着新观察再问模型
                     └──────────────────┘
```

图里没有画出来的，是三个“紧急出口”：步数用完、工具连续失败、重复调用。它们不是正常路径，但必须存在，否则状态机可能永远转下去。

### 2.2 消息序列：assistant 与 tool 必须成对

循环里最容易写错的地方，是消息序列。OpenAI 风格的接口有一条硬规则：模型返回的每一条 `tool_calls`，后面必须跟一条对应的 `tool` 消息，用 `tool_call_id` 对上。少一条，下一次请求会被服务端直接拒绝（HTTP 400）。

正确的一轮长这样：

```text
[1] system     你是 HR 服务台的休假助手……
[2] user       我下个月想休 3 天年假，够不够？需要提前几天申请？
[3] assistant  tool_calls=[{id: "call_a1", name: "get_leave_balance",
                            arguments: {"employee_id": "E1001"}}]
[4] tool        tool_call_id="call_a1"  {"ok": true, "data": {"annual_remaining": 13, ...}}
[5] assistant  tool_calls=[{id: "call_b2", name: "search_policy",
                            arguments: {"keyword": "申请"}}]
[6] tool        tool_call_id="call_b2"  {"ok": true, "data": [{"doc_id": "leave-2025", ...}]}
[7] assistant  content="你今年还剩 13 天年假……提前 3 个工作日申请……"
```

注意第 3 条消息：`assistant` 的 `content` 可以是空的，但 `tool_calls` 必须原样写回。第 4 条消息的 `tool_call_id` 必须等于第 3 条里那个 `call_a1`。这两条消息是一对，拆开就非法。

本章的 `pairing_ok()` 就是检查这件事：遍历历史，遇到 `assistant` 就把它的 `tool_calls` 的 id 记进“待回应”集合，遇到 `tool` 就把对应的 id 移除，最后集合必须为空。这个函数在结尾的断言里对五次运行全部检查了一遍。

> 💡 **小白提示**：可以把 `assistant(tool_calls)` 理解成“模型递过来一张便签，上面写着要调用哪个函数、参数是什么”；`tool` 消息则是“你把执行结果写在同一张便签的背面，递回去”。便签编号对不上，模型就不知道你在回应哪一张。

### 2.3 终止条件：四盏刹车灯

一个没有终止条件的循环，是事故的开始。本章实现了四类终止，正好覆盖四种典型结局：

| 终止原因 | 触发条件 | 返回什么 | 生产含义 |
| --- | --- | --- | --- |
| `final_answer` | 模型不再请求工具，给出文本 | 模型的回答 | 正常收敛 |
| `max_steps` | 达到 `max_steps` 仍在调工具 | 兜底提示 | 任务太复杂或模型打转 |
| `repeated_call` | 同一工具、同一参数第二次出现 | 转人工提示 | 模型卡住了 |
| `tool_errors` | 连续 3 次工具失败 | 转人工提示 | 下游系统故障 |

真实系统还会加“总超时”和“总 Token 预算”，思路一样：给循环设一个明确的成本上限。注意 `repeated_call` 的判断键是“工具名 + 排序后的参数”，只有两者都相同才算重复；同一个工具用不同参数查两次是合理的。

### 2.4 工具注册表：用 dict 把能力挂上去

第 00 章的工具是硬编码的 `if/else`。工具一多，代码就没法看。本章改用 dict 注册：

```python
TOOLS = {
    "get_leave_balance": {
        "fn": get_leave_balance,
        "description": "查询员工的年假/病假余额（只读）",
        "parameters": {"employee_id": {"type": "string", "description": "工号，如 E1001"}},
        "required": ["employee_id"],
    },
    ...
}
```

`run_agent` 只依赖这张表：用 `fn` 执行，用 `description` 和 `parameters` 生成给模型看的工具描述。加一个新工具，只要往 dict 里加一项，循环代码一行不改。这就是“可注册”的好处。

工具描述本身就是 Prompt 的一部分。模型靠它判断“什么时候该调哪个工具”。描述里写清“只读”“单位”“示例值”，比写十行系统提示都管用。

### 2.5 Trace：让每一轮都留下证据

Agent 出问题时，最怕用户说“它就是答错了”，而你完全不知道中间发生了什么。`Tracer` 把一次运行记成一棵树：

- 根节点是整次运行；
- 每个 `step-N` 是一个子节点；
- 每次模型调用是 `llm` 子节点；
- 每次工具执行是 `tool:xxx` 子节点，失败时标红（`x`）；
- 每个节点带耗时、状态、事件。

最后 `print_tree()` 打印出来，`summary()` 还能给出结构化指标：调用次数、工具次数、Token、错误数。第 15 章会把这些指标接到评测和告警上。现在你只需要记住：**没有 Trace 的 Agent，等于没有仪表盘的汽车**。

### 2.6 异常处理：把崩溃变成观察

演示版遇到未知工具或工具抛异常，整个进程就挂了。工程版的做法是：捕获它，转成一条 `tool` 消息回填给模型。

- 未知工具：返回 `{"ok": false, "error": "unknown_tool", "available": [...]}`，模型看到可用工具列表，下一轮通常会改用正确的工具。
- 工具异常：返回 `{"ok": false, "error": "ValueError: 工号 E9999 不存在"}`，模型看到具体错误，可能换个参数重试。
- 参数缺失：`fn(**arguments)` 抛 `TypeError`，同样被捕获，变成可读的错误。

这不是“纵容错误”，而是把错误变成模型能处理的输入。当然要有上限：连续失败 3 次就停，否则模型可能一直在错误参数上打转。

> ⚠️ **生产提醒**：捕获所有异常不等于静默吞掉。工具失败必须同时写 Trace、打日志、进指标；连续失败要触发告警。最危险的情况不是循环崩溃，而是循环“看起来正常”、工具却一直返回错误数据，最后模型用错误数据编出一个很像样子的答案。

### 2.7 AgentResult：为什么返回结构而不是字符串

本章的 `run_agent` 返回一个 `AgentResult`，包含：

- `reply`：给用户看的最终回答；
- `steps`：走了几轮；
- `stopped_reason`：为什么停；
- `trace`：完整调用树与指标；
- `messages`：完整消息历史，方便回放和继续对话。

只返回字符串，调用方就没法判断“这是正常答案还是兜底提示”，也没法统计成功率和成本。返回结构体，上层才能做路由：正常回答直接展示，`max_steps` 转人工，`tool_errors` 触发告警。这也是第 16 章前后端对接的基础。

### 2.8 从 90 行到 199 行，多了什么

把第 00 章和本章放在一起对比，差别一目了然：

| 能力 | ch00（90 行） | ch02（199 行） |
| --- | --- | --- |
| 工具注册 | 写死两个函数 | dict + schema 自动生成 |
| 终止条件 | 只有步数 | 四类终止 + 兜底回答 |
| 异常处理 | 直接崩溃 | 未知工具/异常转 observation |
| 重复调用 | 无检测 | 工具名 + 参数去重 |
| 可观测性 | 只有调用树 | Trace + 指标 + 错误 span |
| 返回值 | 字符串 | AgentResult 结构体 |

多出来的 109 行，几乎全是“失败时怎么办”。这就是教学代码和工程代码的距离。

## 3. 动手：199 行，跑五种结局

> 🧩 **读法**：第 3 节的代码用于解释原理；本章实际运行的 demo 已改为 LangChain 版，完整代码见章末“LangChain 版关键实现”与 `code/` 对应脚本。


代码在 `code/ch02_agent_loop.py`，从仓库根目录运行：

```powershell
python code/ch02_agent_loop.py
```

脚本会跑五个场景：正常三步、工具抛异常、未知工具、重复调用、最大步数截断。下面是**原理示意（旧版手写实现）**，用于理解内部机制；实际运行的是章末的 LangChain 版：

```python
"""第 02 章：Agent Loop —— 从 50 行脚本到工程版循环。

和 ch00 相比，这一版把“能跑”变成“跑得住”：工具用 dict 注册、每一步进 Trace，
未知工具 / 工具异常 / 重复调用 / 最大步数都有明确处理，返回结构化的 AgentResult。
运行：python code/ch02_agent_loop.py
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.data import all_policy_documents, employee
from common.llm import BaseLLM, MockLLM, assistant, system, tool_message, tool_schema, user
from common.trace import Tracer
QUESTION = "我下个月想休 3 天年假，够不够？需要提前几天申请？"
SYSTEM_PROMPT = (
    "你是 HR 服务台的休假助手。规则：\n"
    "1. 先用 get_leave_balance 查余额，再用 search_policy 查制度原文。\n"
    "2. 只依据工具返回的内容回答；没有证据就说不知道，禁止编造条款。\n"
    "3. 回答要带制度编号与条款位置；不能替员工提交申请，只说明流程。\n"
    "4. 工具报错时先判断是参数问题还是权限问题，再决定重试还是解释。"
)

def get_leave_balance(employee_id: str) -> dict:
    """读工具：查假期余额。参数错误会抛异常，由循环转成 observation。"""
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
    """读工具：只搜生效中的制度，返回带编号、版本与条款的片段。"""
    hits: list[dict] = []
    for doc in all_policy_documents():
        if doc["status"] != "active":
            continue  # 归档版本不参与检索，否则会答出旧口径
        for line in doc["content"].splitlines():
            if keyword in line and len(line.strip()) > 4:
                hits.append({"doc_id": doc["doc_id"], "version": doc["version"], "text": line.strip()})
    if not hits:
        raise LookupError(f"制度库里没有包含“{keyword}”的条款")
    return hits[:2]

TOOLS: dict[str, dict[str, Any]] = {
    "get_leave_balance": {
        "fn": get_leave_balance, "description": "查询员工的年假/病假余额（只读）",
        "parameters": {"employee_id": {"type": "string", "description": "工号，如 E1001"}}, "required": ["employee_id"],
    },
    "search_policy": {
        "fn": search_policy, "description": "在生效中的 HR 制度里检索原文条款（只读）",
        "parameters": {"keyword": {"type": "string", "description": "关键词，如 申请"}}, "required": ["keyword"],
    },
}

@dataclass
class AgentResult:
    reply: str
    steps: int
    stopped_reason: str  # final_answer / max_steps / repeated_call / tool_errors
    trace: Tracer
    messages: list[dict] = field(default_factory=list)

def pairing_ok(messages: list[dict]) -> bool:
    """每个 assistant.tool_calls 是否都有 tool 消息回应。

    不满足时下一轮请求会被模型服务直接拒绝（400），所以这是硬约束。
    """
    pending: set[str] = set()
    for message in messages:
        if message["role"] == "assistant":
            pending |= {call["id"] for call in message.get("tool_calls") or []}
        elif message["role"] == "tool":
            pending.discard(message["tool_call_id"])
    return not pending

def execute_tool(tools: dict[str, dict[str, Any]], call: Any, tracer: Tracer) -> tuple[dict, bool]:
    """执行一个工具调用。未知工具与异常都变成 observation，而不是让进程崩溃。"""
    spec = tools.get(call.name)
    if spec is None:
        tracer.event("unknown_tool", tool=call.name)
        print(f"         ! 未知工具 {call.name}，已把可用工具告诉模型")
        return {"ok": False, "error": "unknown_tool", "available": sorted(tools)}, False
    started = time.perf_counter()
    with tracer.span(f"tool:{call.name}") as span:
        try:
            payload, ok = {"ok": True, "data": spec["fn"](**call.arguments)}, True
        except Exception as exc:  # 参数错、查无此人、下游超时，全在这里兜住
            payload, ok = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}, False
            span.status, span.attrs["error"] = "error", str(exc)[:80]
    tracer.record_tool(call.name, call.arguments, ok, (time.perf_counter() - started) * 1000, payload)
    print(f"         {'ok ' if ok else 'ERR'} {call.name} -> {json.dumps(payload, ensure_ascii=False)[:80]}")
    return payload, ok

def run_agent(llm: BaseLLM, tools: dict[str, dict[str, Any]], messages: list[dict], max_steps: int = 6) -> AgentResult:
    """跑一次完整的 Agent 循环，直到拿到答案或触发终止条件。"""
    schemas = [tool_schema(n, s["description"], s["parameters"], s.get("required", [])) for n, s in tools.items()]
    history = list(messages)  # 复制一份，不污染调用方传入的列表
    tracer = Tracer("hr-agent-loop")
    seen: Counter[str] = Counter()
    consecutive_errors = 0
    reply, reason, step = "", "max_steps", 0

    while step < max_steps:  # 步数预算：没有它，循环可能跑到天亮，账单也一起涨
        step += 1
        print(f"[step {step}] 请求模型（历史 {len(history)} 条消息）")
        with tracer.span(f"step-{step}"):
            with tracer.span("llm"):
                response = llm.chat(history, tools=schemas, temperature=0.2)
            tracer.record_llm(response)
            # 先把 assistant 消息写回历史，再执行工具：顺序反了，消息序列就非法
            history.append(assistant(response.content, response.tool_calls))
            if not response.tool_calls:
                reply, reason = (response.content or "").strip(), "final_answer"
                print(f"[step {step}] 拿到最终回答，循环结束")
                break
            print(f"[step {step}] 模型要求 {len(response.tool_calls)} 个工具调用")
            for call in response.tool_calls:
                key = f"{call.name}:{json.dumps(call.arguments, sort_keys=True, ensure_ascii=False)}"
                seen[key] += 1
                if seen[key] > 1:  # 同一工具同一参数重复出现，通常说明模型在打转
                    history.append(tool_message(call, {"ok": False, "error": "repeated_call"}))
                    tracer.event("repeated_call", tool=call.name)
                    reply, reason = "检测到重复调用，已停止并转人工。", "repeated_call"
                    print(f"[step {step}] 重复调用 {call.name}，终止")
                    break
                payload, ok = execute_tool(tools, call, tracer)
                history.append(tool_message(call, payload))  # 每个 tool_call 都必须有回应
                consecutive_errors = 0 if ok else consecutive_errors + 1
                if consecutive_errors >= 3:  # 连续失败就别再烧 token 了
                    reply, reason = "工具连续失败，已停止并转人工。", "tool_errors"
            if reason != "max_steps":  # 内层因重复调用/连续失败退出时，外层也要退出
                break

    return AgentResult(reply or "（达到最大步数，未得到最终答案，转人工处理）", step, reason, tracer, history)

def run_case(title: str, script: list[dict], max_steps: int = 6) -> AgentResult:
    print(f"\n=== {title} ===")
    messages = [system(SYSTEM_PROMPT), user(QUESTION)]
    result = run_agent(MockLLM(script), TOOLS, messages, max_steps)
    print(f"[结果] reason={result.stopped_reason} steps={result.steps} reply={result.reply[:50]}")
    return result

def main() -> None:
    normal = run_case("1. 正常流程：查余额 → 查制度 → 回答", [
        {"tool_calls": [{"name": "get_leave_balance", "arguments": {"employee_id": "E1001"}}]},
        {"tool_calls": [{"name": "search_policy", "arguments": {"keyword": "申请"}}]},
        {"content": "张伟，你今年还剩 13 天年假，休 3 天够用。按 HR-LEAVE-2025（2025.1）第 2.3 条，"
         "需提前 3 个工作日提交申请；连续休假不超过 3 天由直属主管审批。"},
    ])
    print("\n=== Trace 调用树（正常流程） ===")
    normal.trace.print_tree()

    recovered = run_case("2. 工具抛异常：错误变成 observation，模型自己改参数", [
        {"tool_calls": [{"name": "get_leave_balance", "arguments": {"employee_id": "E9999"}}]},
        {"tool_calls": [{"name": "get_leave_balance", "arguments": {"employee_id": "E1001"}}]},
        {"content": "工号 E9999 查不到，已按你的工号 E1001 重查：还剩 13 天年假。"},
    ])
    print("\n=== Trace 调用树（失败的工具有 error span） ===")
    recovered.trace.print_tree()

    unknown = run_case("3. 未知工具：循环不崩，把可用工具告诉模型", [
        {"tool_calls": [{"name": "submit_leave_request", "arguments": {"employee_id": "E1001"}}]},
        {"content": "我不能直接替你提交请假单，但可以帮你核对余额和申请时限。"},
    ])
    repeated = run_case("4. 重复调用：同一工具同一参数第二次出现就终止", [
        {"tool_calls": [{"name": "get_leave_balance", "arguments": {"employee_id": "E1001"}}]},
        {"tool_calls": [{"name": "get_leave_balance", "arguments": {"employee_id": "E1001"}}]},
    ])
    maxed = run_case("5. 最大步数：max_steps=2，模型还在查资料就被截断", [
        {"tool_calls": [{"name": "search_policy", "arguments": {"keyword": "年假"}}]},
        {"tool_calls": [{"name": "search_policy", "arguments": {"keyword": "申请"}}]},
    ], max_steps=2)

    tool_messages = [m for m in normal.messages if m["role"] == "tool"]
    assert (normal.stopped_reason == "final_answer" and normal.steps == 3 and len(tool_messages) == 2
            and json.loads(tool_messages[0]["content"])["data"]["annual_remaining"] == 13
            and "3 个工作日" in tool_messages[1]["content"]), "正常流程：3 步收敛，两条 observation 都带回了证据"
    assert recovered.trace.metrics["errors"] == 1 and recovered.stopped_reason == "final_answer"
    assert (repeated.stopped_reason == "repeated_call" and maxed.stopped_reason == "max_steps" and maxed.steps == 2
            and "unknown_tool" in json.dumps(unknown.messages, ensure_ascii=False)), "未知工具与两类终止条件都要生效"
    assert all(pairing_ok(result.messages) for result in (normal, recovered, unknown, repeated, maxed)), "消息配对必须完整"
    print("\n全部断言通过：4 类终止条件、消息配对、异常回填都符合预期。")

if __name__ == "__main__":
    main()
```

运行输出（Trace ID 与耗时每次不同）：

```text
=== 1. 正常流程：查余额 → 查制度 → 回答 ===
[step 1] 请求模型（历史 2 条消息）
[step 1] 模型要求 1 个工具调用
         ok  get_leave_balance -> {"ok": true, "data": {"employee_id": "E1001", "name": "张伟", "annual_remaining": 
[step 2] 请求模型（历史 4 条消息）
[step 2] 模型要求 1 个工具调用
         ok  search_policy -> {"ok": true, "data": [{"doc_id": "leave-2025", "version": "2025.1", "text": "###
[step 3] 请求模型（历史 6 条消息）
[step 3] 拿到最终回答，循环结束
[结果] reason=final_answer steps=3 reply=张伟，你今年还剩 13 天年假，休 3 天够用。按 HR-LEAVE-2025（2025.1）第 2

=== Trace 调用树（正常流程） ===

TRACE d5dd55dbc973  hr-agent-loop  3ms
- hr-agent-loop (3ms) 
  - step-1 (0ms) 
    · llm_call 
    · tool_call get_leave_balance
    - llm (0ms) 
    - tool:get_leave_balance (0ms) 
  - step-2 (2ms) 
    · llm_call 
    · tool_call search_policy
    - llm (0ms) 
    - tool:search_policy (2ms) 
  - step-3 (0ms) 
    · llm_call 
    - llm (0ms) 
  llm=3 tool=2 token=834 error=0

=== 2. 工具抛异常：错误变成 observation，模型自己改参数 ===
[step 1] 请求模型（历史 2 条消息）
[step 1] 模型要求 1 个工具调用
         ERR get_leave_balance -> {"ok": false, "error": "ValueError: 工号 E9999 不存在"}
[step 2] 请求模型（历史 4 条消息）
[step 2] 模型要求 1 个工具调用
         ok  get_leave_balance -> {"ok": true, "data": {"employee_id": "E1001", "name": "张伟", "annual_remaining": 
[step 3] 请求模型（历史 6 条消息）
[step 3] 拿到最终回答，循环结束
[结果] reason=final_answer steps=3 reply=工号 E9999 查不到，已按你的工号 E1001 重查：还剩 13 天年假。

=== Trace 调用树（失败的工具有 error span） ===

TRACE 4a9dd46fba53  hr-agent-loop  0ms
- hr-agent-loop (0ms) 
  - step-1 (0ms) 
    · llm_call 
    · tool_call get_leave_balance
    - llm (0ms) 
    x tool:get_leave_balance (0ms) {'error': '工号 E9999 不存在'}
  - step-2 (0ms) 
    · llm_call 
    · tool_call get_leave_balance
    - llm (0ms) 
    - tool:get_leave_balance (0ms) 
  - step-3 (0ms) 
    · llm_call 
    - llm (0ms) 
  llm=3 tool=2 token=751 error=1

=== 3. 未知工具：循环不崩，把可用工具告诉模型 ===
[step 1] 请求模型（历史 2 条消息）
[step 1] 模型要求 1 个工具调用
         ! 未知工具 submit_leave_request，已把可用工具告诉模型
[step 2] 请求模型（历史 4 条消息）
[step 2] 拿到最终回答，循环结束
[结果] reason=final_answer steps=2 reply=我不能直接替你提交请假单，但可以帮你核对余额和申请时限。

=== 4. 重复调用：同一工具同一参数第二次出现就终止 ===
[step 1] 请求模型（历史 2 条消息）
[step 1] 模型要求 1 个工具调用
         ok  get_leave_balance -> {"ok": true, "data": {"employee_id": "E1001", "name": "张伟", "annual_remaining": 
[step 2] 请求模型（历史 4 条消息）
[step 2] 模型要求 1 个工具调用
[step 2] 重复调用 get_leave_balance，终止
[结果] reason=repeated_call steps=2 reply=检测到重复调用，已停止并转人工。

=== 5. 最大步数：max_steps=2，模型还在查资料就被截断 ===
[step 1] 请求模型（历史 2 条消息）
[step 1] 模型要求 1 个工具调用
         ok  search_policy -> {"ok": true, "data": [{"doc_id": "leave-2025", "version": "2025.1", "text": "# 年
[step 2] 请求模型（历史 4 条消息）
[step 2] 模型要求 1 个工具调用
         ok  search_policy -> {"ok": true, "data": [{"doc_id": "leave-2025", "version": "2025.1", "text": "###
[结果] reason=max_steps steps=2 reply=（达到最大步数，未得到最终答案，转人工处理）

全部断言通过：4 类终止条件、消息配对、异常回填都符合预期。
```

## 4. 逐行拆解：七个关键决策

**第一，为什么 `history = list(messages)` 要复制？** 如果直接改传进来的列表，调用方之后拿到的就是被 Agent “污染”过的历史。复制一份，调用方的输入保持不变，Agent 的中间状态只活在 `AgentResult.messages` 里。后面做会话持久化、回放、A/B 测试时，这个习惯能省很多事。

**第二，为什么先 append assistant 再执行工具？** 消息序列必须还原真实发生的事：模型先“说”要调用 `get_leave_balance`，代码才去执行。如果先执行再补 assistant，中间一旦异常，历史里就会出现“有 tool 结果但没有对应 assistant”的非法序列。

**第三，为什么每个 `tool_call` 都要回一条 `tool` 消息，哪怕是未知工具和重复调用？** 因为配对是硬约束。未知工具时，我们回 `{"ok": false, "error": "unknown_tool"}`；重复调用时，我们回 `{"ok": false, "error": "repeated_call"}`，然后才退出。缺一条，`pairing_ok()` 就会返回 `False`——这在生产里意味着下一次请求直接 400。

**第四，重复调用的 key 为什么要把参数排序？** `json.dumps(..., sort_keys=True)` 保证 `{"employee_id": "E1001"}` 和 `{"employee_id":"E1001"}` 生成同一个键。如果不排序，参数的书写顺序不同就会绕过检测。反过来，同一个工具用不同参数调用是正常的（先查余额再查制度），不能被误杀。

**第五，为什么 `reason` 初始化为 `"max_steps"`，而不是空字符串？** 因为循环正常退出（`step` 到达上限）时，不需要额外赋值，默认就是“步数用完”。只有拿到答案、重复调用、连续失败时才改写它。这样代码少一个分支，语义也更清楚：没改写，就是被截断。

**第六，为什么连续失败阈值是 3？** 这是经验值：一次失败可能是参数手滑，两次可能是模型没理解错误信息，三次基本可以判断“这条路走不通”。阈值太小会误杀（模型本来能自我修复），太大则浪费 Token。生产里这个值应该可配置，并按工具类型区分——读工具可以多试，写工具一次失败就该停。

**第七，为什么返回 `AgentResult` 而不是 `reply`？** 上层需要知道“为什么停”。正常回答可以直接展示；`max_steps` 要转人工；`tool_errors` 要触发告警；`repeated_call` 要记录 bad case。只给字符串，这些判断都做不了。`trace` 还能让客服在用户投诉时快速定位是哪一步出了问题。

> 📌 **考点**：面试常问“Agent 循环怎么防止死循环”。标准答案包含四层：最大步数、总超时、重复调用检测、连续失败熔断；再加一层“总 Token 预算”就是完整答案。只答“设置 max_steps”会被认为工程经验不足。

## 5. 实验：把刹车踩到底

**实验一：把 `max_steps` 改成 2。** 正常流程会在第 2 步查完制度后被截断，`reason` 变成 `max_steps`，`reply` 是兜底提示。观察 Trace：`step-2` 之后没有 `step-3`，`llm=2`。这时如果你把兜底提示换成“我查到余额了，但还没核对完制度，先帮你转 HR”，员工体验会好很多。

**实验二：把重复调用检测改成“同一工具调用超过 2 次”。** 把 `if seen[key] > 1` 改成 `if seen[key] > 2`，再跑场景 4。你会发现模型多绕了一圈才被终止，Token 也更多。思考：如果模型每次参数都差一点（比如工号 E1001、E1001 、E-1001），这个检测还管用吗？答案是不管用，需要更聪明的“语义重复”检测，或者直接靠步数上限兜底。

**实验三：给工具加一个“慢查询”。** 在 `get_leave_balance` 里加 `time.sleep(0.2)`（不要超过 0.5 秒），观察 Trace 里 `tool:get_leave_balance` 的耗时变化。生产环境里，工具超时必须由代码控制（第 11 章会讲 `ThreadPoolExecutor` 加超时），不能指望模型“等一等”。

**实验四：把工具结果改成 JSON 字符串再解析。** 现在 `execute_tool` 返回 dict，`tool_message` 会序列化。试着让工具直接返回字符串，观察模型侧和断言侧的变化。这个练习是为了让你理解：协议层统一用字符串，业务层再解析，边界更清晰。

**实验五：加第三个工具。** 仿照 `TOOLS` 的写法加一个 `get_pending_tickets(employee_id)`，读取 `code/data/tickets.json`。注意同步更新系统提示（告诉模型什么时候用它）和 Mock 剧本。体会一下“加工具只改注册表”的爽感。

## 6. 工程化视角：循环跑通之后，还缺什么

本章的循环已经能跑住，但离生产还有距离。按优先级列一下：

1. **消息历史会无限增长**：每轮都追加 assistant 和 tool，十轮之后上下文可能爆掉。第 07 章会讲预算、裁剪和摘要。
2. **工具调用是串行的**：模型一次返回 3 个工具调用，我们一个个执行。只读工具可以并行，第 03 章会用线程池。
3. **没有超时和重试**：工具卡住，循环就卡住。第 11 章补超时、退避、熔断。
4. **没有持久化**：进程一挂，跑到一半的任务就丢了。第 05、14 章讲 checkpoint 和恢复。
5. **没有人工中断**：敏感操作需要暂停等审批，第 12 章讲 HITL。
6. **没有评测**：你不知道这版循环的成功率是多少，第 15 章补 Golden Case 和指标。

> ⚠️ **生产提醒**：`max_steps` 不是拍脑袋定的。先统计正常任务需要几步（本章是 3 步），再把上限设成 P95 的 1.5 到 2 倍。设得太小会误杀复杂任务，设得太大等于没有刹车。每次触发 `max_steps` 都要记录 bad case，用来判断是“任务确实复杂”还是“模型在打转”。

## 7. 常见坑

**现象：下一轮请求报 400，提示 tool_call_id 不匹配。**
原因：某个 `assistant.tool_calls` 没有对应的 `tool` 消息，或者 id 被覆盖。
解法：永远用 `call.id` 原样回填，不要自己生成；每个 call 都必须回一条，包括失败和重复调用。

**现象：工具抛异常，整个 Agent 进程挂了。**
原因：没有 try/except，异常直接冒泡。
解法：在 `execute_tool` 里捕获所有异常，转成 `{"ok": false, "error": ...}` 回填；同时用 Trace 记 error span。

**现象：模型反复调用同一个工具，Token 一直涨。**
原因：没有重复调用检测，或者检测键没包含参数。
解法：用“工具名 + 排序后的参数”做键；连续重复就终止并记录 bad case。

**现象：模型说“我查到了”，但答案里没有数字。**
原因：工具结果没有被正确回填，或者模型忽略 observation。
解法：检查 `tool` 消息是否真的进了 `history`；在系统提示里要求“引用工具返回的具体数值”；用断言守住关键字段。

**现象：Trace 里工具耗时很长，但没有报错。**
原因：工具本身慢（下游接口超时），循环在干等。
解法：给工具设超时，超时按可重试错误处理；第 11 章会给出完整方案。

**现象：同一句话，两次运行的工具调用不一样。**
原因：真实模型有随机性，temperature 不为 0。
解法：抽取类任务把 temperature 调到 0；对一致性要求高的场景，加 schema 约束和结果校验，不要指望模型每次一样。

## 8. 练习

**练习 1（热身）**：不看代码，画出正常流程的消息序列，标出每轮的 `assistant.tool_calls` 和对应的 `tool` 消息。

**练习 2**：把 `max_steps` 改成 2，运行并记录 `stopped_reason`、`steps`、`reply`。然后写一个更友好的兜底回答，要求包含“已查到什么、还差什么、下一步怎么办”。

**练习 3**：给 `run_agent` 加一个 `timeout_seconds` 参数，在每轮开始时检查是否超时，超时就以 `stopped_reason="timeout"` 返回。提示：用 `time.monotonic()` 记录开始时间，不要用 `time.time()`。

**练习 4**：把重复调用检测改成“同一工具调用超过 2 次才终止”，跑场景 4，对比 Token 和步数。再思考：如果模型每次参数都略有不同，怎么检测“语义上的重复”？

**练习 5（进阶）**：给 `AgentResult` 增加 `token_usage` 字段，从 `trace.metrics` 里汇总 `prompt_tokens` 和 `completion_tokens`；再加一个 `cost_cny` 方法，按输入 2 元/百万、输出 8 元/百万计算成本。

<details><summary>参考答案</summary>

**练习 1**：`system` → `user` → `assistant(tool_calls=[get_leave_balance])` → `tool(tool_call_id=call_1)` → `assistant(tool_calls=[search_policy])` → `tool(tool_call_id=call_2)` → `assistant(content=最终回答)`。两次工具调用分别在第 1、2 轮，第 3 轮模型不再请求工具。

**练习 2**：`max_steps=2` 时正常流程的 `stopped_reason="max_steps"`、`steps=2`、`reply` 是“（达到最大步数，未得到最终答案，转人工处理）”。更友好的写法：“我已经查到你的年假余额（13 天），但还没核对完申请时限。为避免说错，我先帮你转 HR，预计 2 小时内回复。”——把已知、未知、下一步说清楚。

**练习 3**：在 `run_agent` 开头加 `deadline = time.monotonic() + timeout_seconds`，在 `while` 顶部判断 `if time.monotonic() > deadline: reply, reason = "处理超时，已转人工。", "timeout"; break`。注意要在 `while` 条件里也保留 `step < max_steps`，两个预算同时生效。

**练习 4**：把 `if seen[key] > 1` 改成 `> 2` 后，场景 4 会执行两次余额查询，第 3 次才终止，`steps=3`、Token 增加。语义重复检测可以比较“工具名 + 参数归一化后的关键字段”，例如工号统一大写、去空格；更复杂的做法是让模型在调用前先复述计划，减少无效重试，但成本更高。

**练习 5**：`AgentResult` 加字段 `token_usage: dict[str, int]`，在 `run_agent` 返回前用 `tracer.metrics` 填充；`cost_cny` 写成 `self.token_usage["prompt_tokens"] / 1e6 * 2 + self.token_usage["completion_tokens"] / 1e6 * 8`。注意 `trace.metrics` 已经在 `record_llm` 里累计了每次调用的 usage。

</details>

## 9. 小结与下一章

这一章我们把 90 行的演示循环，演进成了 199 行的工程循环：工具用 dict 注册，消息严格配对，四类终止条件各司其职，异常变成 observation，Trace 记录每一步。正常流程 3 步收敛，异常流程 2 到 3 步内干净退出——这才叫“跑得住”。

请记住三句话：每个 `tool_call` 都必须有回应；每个循环都必须有刹车；每次运行都必须留下 Trace。

循环能跑了，但工具还是我们自己写死的两个函数：参数没校验、没有权限、没有幂等，写操作更是不敢碰。下一章我们把工具变成真正的“能力”：用 JSON Schema 描述参数，用 Pydantic 校验，用权限和幂等保护写操作——让模型的手脚既灵活又安全。

---

## 10. 附：LangChain 版关键实现

> 本章实际运行的 demo 使用 **StateGraph + ToolNode + tools_condition**，完整代码见 `code/ch02_agent_loop.py`。下面只保留骨架，方便你对照前面的原理示意阅读。

```python
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

graph = StateGraph(AgentState)
graph.add_node("model", model_node)
graph.add_node("tools", ToolNode(TOOLS))
graph.add_edge(START, "model")
graph.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
graph.add_edge("tools", "model")
app = graph.compile()
state = app.invoke({"messages": [HumanMessage("我还有几天年假？")]})
```

| 本章概念 | LangChain / LangGraph 对应物 |
| --- | --- |
| 循环 | `StateGraph` |
| 工具节点 | `ToolNode` |
| 条件边 | `tools_condition` |

> 🧩 **怎么读**：先看正文理解“为什么需要这一层”，再看上面的骨架理解“框架怎么表达这一层”，最后打开 `code/ch02_agent_loop.py` 看完整实现与断言。面试时两条线都要能讲：原理线 + 框架线。
