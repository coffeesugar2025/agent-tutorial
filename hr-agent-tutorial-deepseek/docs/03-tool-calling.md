---
title: "03 | Tool Calling：把 HR 系统变成模型的手脚"
slug: "tool-calling"
order: 3
part: "单 Agent 核心"
minutes: 60
difficulty: "入门"
prerequisites: ["02"]
summary: "让模型安全地查候选人、约面试：Schema、校验、权限、幂等与并行。"
---
> 🧩 **框架说明**：本章 demo 基于 **LangChain 1.x + LangGraph 1.x**，核心 API：`@tool`、`create_agent`、`StructuredTool`。正文中的代码若标注“原理示意”（包括旧版 MockLLM / 手写循环片段），用于解释内部机制，不是最终运行代码；完整可运行代码见 `code/ch03_tools.py`。


## 0. 本章你会得到什么

学完本章，你能做到：

1. 写出符合 Function Calling 规范的 JSON Schema，并解释字段为什么这样写。
2. 用 Pydantic 在工具执行前校验参数，把失败变成模型能读懂的错。
3. 区分读工具与写工具，给写工具加角色权限、幂等键和二次确认的位置。
4. 用 `ThreadPoolExecutor` 并行只读工具，并说清为什么写工具不能这样干。
5. 把“工具描述”当 Prompt 写，知道描述含糊会把 Agent 带沟里。

## 1. 场景

Acme 科技（虚构）的招聘专员郑爽，周三下午 4 点收到用人经理的消息：“林晓初筛过了，帮我约徐明下周三做专业面，越快越好。”

这件事有六个动作：查林晓档案、确认她还在初筛、查徐明空闲、避开已有会议、创建日程、给双方发邀请。郑爽要在招聘系统、日历、邮件三个界面切换，一场 7 分钟，一周 40 场。

上周出过事故。她给王浩排完面试，页面一直转圈，她又点了一次“发送”。王浩收到两封时间相同的邀请，先回信问“是不是有两个面试”，又打电话确认流程。一场本可以很专业的面试，开场先花了十分钟解释系统故障。

这不是手速问题，而是三个工程问题叠在一起：模型要查到真实数据，要能产生副作用，还要保证重复执行时副作用只发生一次。

Tool Calling（工具调用，也叫 Function Calling）就是为这三件事生的。模型决定“做什么”，代码负责“怎么做、能不能做、做过没有”。本章把招聘场景最常用的三个能力做成工具：`search_candidates`、`get_interviewer_slots`、`schedule_interview`。

> 💡 **小白提示**：模型本身不能读数据库，也不能发邮件。它只能输出一段结构化文本，告诉你的程序“我想调用 `schedule_interview`，参数是这些”。真正的执行发生在你的代码里，这是后面所有权限、审计、幂等设计的根基。

## 2. 概念

### 2.1 工具调用到底发生了什么

把模型想象成电话这头的调度员：他看不到日历，但可以说“请查徐明 11 月 18 日的空闲”；你查完念给他听，他再决定下一步。

一次完整的工具调用有五个角色：

```text
用户：帮林晓约徐明下周三面试
        │
        ▼
   LLM（只做决策，不执行）
        │  tool_calls: [{name, arguments}]
        ▼
 ┌──────────────┐   失败    ┌──────────────────────┐
 │ 参数校验      │─────────▶│ ToolResult(ok=False) │
 │ Pydantic     │          │ code / retryable     │
 └──────┬───────┘          └──────────┬───────────┘
        │ 通过                        │
        ▼                             │
 ┌──────────────┐   拒绝    ┌─────────▼───────────┐
 │ 权限检查      │─────────▶│ FORBIDDEN           │
 │ 角色 + 租户   │          └─────────────────────┘
 └──────┬───────┘
        │ 允许
        ▼
 ┌──────────────┐   命中    ┌─────────────────────┐
 │ 幂等键检查    │─────────▶│ 直接返回上次结果     │
 └──────┬───────┘          └─────────────────────┘
        │ 未命中
        ▼
 ┌──────────────────────────────┐
 │ 执行：读数据库 / 写 HR 系统   │
 └──────────────┬───────────────┘
                ▼
   ToolResult {ok, data, error, retryable}
                │
                ▼
   tool 消息回填 → LLM 组织最终答复
```

两个细节：校验、权限、幂等都在执行前，任何一步失败都不产生副作用；失败不抛给用户看，而是回填 `ToolResult`，模型看到 `INVALID_ARGS` 可以改参数，看到 `FORBIDDEN` 应该停下来求助。

### 2.2 JSON Schema：给参数画一张表

Function Calling 规范里，每个工具用一段 JSON Schema 描述参数：有哪些字段、什么类型、必填还是可选、取值范围是什么。

```json
{
  "type": "function",
  "function": {
    "name": "search_candidates",
    "description": "按关键词、城市、最低年限搜索候选人。只读；返回脱敏列表。",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "岗位、姓名或技能关键词"},
        "city": {"type": "string", "description": "城市，如 上海"},
        "min_years": {"type": "integer", "minimum": 0, "maximum": 40}
      },
      "required": ["query"]
    }
  }
}
```

模型只看 Schema，看不到 Python 源码，所以 `description` 是 Prompt 的一部分：写“查询候选人”和写清关键词、只读、脱敏，选错参数的概率完全不同。

### 2.3 Pydantic：一份定义，两处生效

手写 Schema 会漂移：文档改了代码没改，校验改了 Schema 没改。我们的做法是用 Pydantic 定义参数，再自动生成 Schema，让“给模型看的”和“运行时校验的”来自同一份定义。

```python
class SearchCandidatesParams(BaseModel):
    query: str = Field(min_length=1, max_length=20, description="岗位、姓名或技能关键词")
    city: str | None = Field(default=None, description="城市，如 上海")
    min_years: int = Field(default=0, ge=0, le=40, description="最低工作年限")
```

`ge=0`、`le=40` 会同时出现在 JSON Schema 和运行时校验里。模型传了 `"五年"`，Pydantic 抛出 `ValidationError`，我们把它翻译成 `INVALID_ARGS`，并标记 `retryable=True`，因为模型改一改参数就能成功。

### 2.4 读工具与写工具，必须分开对待

| 维度 | 读工具（search / slots） | 写工具（schedule） |
| --- | --- | --- |
| 副作用 | 无 | 创建日程、发邮件 |
| 权限 | 招聘、HRBP、审计都可读 | 仅招聘专员 |
| 重试 | 可以放心重试 | 必须带幂等键 |
| 并行 | 可以并行 | 禁止并行 |
| 失败处理 | 降级、换数据源 | 补偿、人工核对 |

这张表是本章最重要的工程约定。很多线上事故不是模型笨，而是把写工具当读工具重试了三次。

### 2.5 幂等：同一个请求，只发生一次

幂等（idempotency）的意思是：同一个操作执行一次和执行多次，最终效果相同。类比报销单号：你重复提交同一张单子，财务认的是单号，不会报两次。

实现幂等通常靠“幂等键”：有自然唯一键就用它，例如“候选人 + 面试官 + 时间段”；没有就由调用方生成 UUID，重试时复用；键和结果要一起持久化，由数据库唯一索引兜底。

本章的 `schedule_interview` 不传 `idempotency_key` 就用自然键。命中幂等表时，它返回**和第一次完全相同**的 `interview_id`，标记 `replayed=True`，但不会再发一封邮件。

### 2.6 并行：只读工具可以一起跑

查候选人和查面试官空闲是两件互不依赖的只读操作，串行要两个网络往返，并行只要一个。`ThreadPoolExecutor` 是最小实现：提交任务，再按提交顺序收集结果。

并行有三个前提：工具只读、互不依赖、下游能接受乱序完成。写工具一旦并行，创建日程和发邀请谁先谁后就说不清，回滚也无从谈起，所以 `call_tools_parallel` 直接拒绝写工具。

### 2.7 工具描述即 Prompt

一段好的工具描述包含五件事：做什么、何时用、边界（是否只读）、返回什么（是否脱敏）、参数单位与格式。真正的边界要靠代码里的权限和校验，而不是靠模型自觉。

### 2.8 工具不止一种封装：MCP、Skill、Plugin

学到这你可能会问：工具多了，能不能跨项目复用？能不能打包分发？这就引出三种常见封装：

| 形态 | 是什么 | 适合 | 不适合 |
| --- | --- | --- | --- |
| Tool | 一个可调用函数（本章） | 单应用内的确定性动作 | 跨应用复用 |
| MCP | 跨应用的工具有协议，Server 暴露 Tool/Resource/Prompt | 多宿主复用、独立部署 | 小项目，增加协议层 |
| Skill | 指令 + 脚本 + 参考资料的“操作手册” | 流程规范、领域知识、按需加载 | 需要强事务的写操作 |
| Plugin | 可安装的能力包，含工具、Skill、权限、配置 | 企业分发、升级、权限管理 | 供应链不可信时 |

一个 HR 项目的典型组合是：**只读查询做成 MCP Server，制度问答做成 Skill + RAG，面试/调薪仍走本应用的 Tool + 审批**。协议不会替你解决权限，反而要求你在 Server 端再做一次校验。

> 📌 **考点**：Function Calling 解决“模型怎么发起调用”，MCP 解决“工具服务怎么被不同宿主发现和复用”。两者不是替代关系。更完整的对比、最小 MCP Server 示例与 RAG 工具选型，见 `docs/appendix/ecosystem.md`。

## 3. 动手

> 🧩 **读法**：第 3 节的代码用于解释原理；本章实际运行的 demo 已改为 LangChain 版，完整代码见章末“LangChain 版关键实现”与 `code/` 对应脚本。


先跑起来，建立体感：

```powershell
python code/ch03_tools.py
```

脚本会依次打印工具清单、模型发起的两个并行调用、一次参数错误、一次权限拒绝，以及一次“同一幂等键调用两次”的结果。

核心结构只有三块。第一块是统一的返回值和注册表：

```python
@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None
    code: str = ""
    retryable: bool = False

    def to_message(self) -> dict:
        if self.ok:
            return {"ok": True, "data": self.data}
        return {"ok": False, "error": self.error, "code": self.code, "retryable": self.retryable}


def tool(name: str, description: str, params: type[BaseModel], *, read_only: bool, roles: tuple[str, ...]):
    def decorator(handler):
        REGISTRY[name] = ToolSpec(name, description, params, handler, read_only, roles)
        return handler
    return decorator
```

第二块是写工具的幂等核心。注意它先查幂等表，再查空档，最后才写日程：

```python
key = params.idempotency_key or f"natural:{params.candidate_id}:{params.interviewer_id}:{params.slot}"
with _LOCK:
    if key in _IDEMPOTENCY:
        return ToolResult(True, {**_IDEMPOTENCY[key], "replayed": True})
    if params.slot not in _slots_for(params.interviewer_id, params.slot[:10]):
        return fail("SLOT_UNAVAILABLE", f"{params.slot} 不是 {interviewer['name']} 的空闲时段")
    if any(row["interviewer_id"] == params.interviewer_id and row["slot"] == params.slot for row in _SCHEDULES):
        return fail("SLOT_TAKEN", "该时段已被占用，请换一个 slot")
    record = {...}  # 省略字段，完整版见文件
    _SCHEDULES.append(record)
    _IDEMPOTENCY[key] = record
    return ToolResult(True, dict(record))
```

第三块是统一执行入口。它把“工具不存在、没权限、参数错、执行异常”四种情况都收敛成 `ToolResult`：

```python
def call_tool(name: str, arguments: dict, ctx: ToolContext) -> ToolResult:
    spec = REGISTRY.get(name)
    if spec is None:
        return fail("UNKNOWN_TOOL", f"没有 {name}；可用：{', '.join(REGISTRY)}")
    if ctx.role not in spec.roles:
        return fail("FORBIDDEN", f"角色 {ctx.role} 无权调用 {name}，需要 {spec.roles}")
    try:
        params = spec.params.model_validate(arguments)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "arguments"
        return fail("INVALID_ARGS", f"{location}: {first['msg']}；请修正参数后重试", retryable=True)
    try:
        return spec.handler(params, ctx)
    except Exception as exc:
        return fail("TOOL_ERROR", f"{type(exc).__name__}: {exc}", retryable=True)
```

运行输出里最关键的四行是：

```text
模型一次返回 2 个 tool_calls：search_candidates, get_interviewer_slots
并行耗时 0.05s 左右（串行约 0.10s）
第二次: replayed=True interview_id=IV0001
实际日程 1 条，邀请 2 封
```

`2 封`不是重复发给了候选人，而是一场面试给候选人和面试官各发一封。重复调用没有增加日程和邀请，这就是幂等要保证的事。

## 4. 逐行拆解

**第一，为什么要有注册表和装饰器。** 工具一多，`if/elif` 会变成两百行分支，权限、读写标记、Schema 散落各处。装饰器把函数、描述、参数模型、读写属性、角色绑成 `ToolSpec` 存进 `REGISTRY`，后续步骤只读这份元数据。

**第二，Schema 是生成的，不是手抄的。** `tool_schemas()` 调用 `model_json_schema()`，再包成 OpenAI 格式。Pydantic 的 `Field` 描述、`pattern`、`ge/le` 会自动进入 Schema，模型看到的约束和代码执行的约束不会打架。

**第三，权限检查放在参数校验之前。** 顺序是“工具存在 → 角色允许 → 参数合法”。反过来，实习生传个畸形参数就能拿到详细字段错误，等于免费得到内部 Schema。真实系统还要带租户和审批单号。

**第四，错误码要能指导下一步。** `INVALID_ARGS` 可重试，模型可以改参数；`FORBIDDEN`、`SLOT_TAKEN` 不可重试，模型应该换方案或找人；`TOOL_ERROR` 可重试，但要配合退避和最大次数。只回一句“失败了”，模型只能瞎猜，最后陷入重复调用。

**第五，幂等的锁保护的是“检查 + 写入”这一整段。** 只在写日程时加锁，两个并发请求可能同时通过“幂等表里没有”，各写一条。`_LOCK` 把查重、查空档、写日程、记键包成临界区。生产不要用进程内的 `threading.Lock`，要用数据库唯一索引或 Redis 的 `SET NX`，因为服务通常有多个副本。

> ⚠️ **生产提醒**：幂等表必须落库，并给 `(tenant_id, idempotency_key)` 建唯一索引。只在内存里记一份，进程重启或换一台机器就失效；只靠先查后写，也挡不住并发。唯一索引是最后一道防线。

**第六，并行执行要保留结果顺序。** `pool.submit` 之后按原顺序 `result()`，`results[0]` 一定对应 `search_candidates`。如果按完成顺序收集，工具结果就会和 `tool_call_id` 对错，模型会看到“面试官空闲”被塞进候选人查询里。

## 5. 实验

**实验一：换一个角色。** 把 `intern` 改成 `recruiter`，再调用 `schedule_interview`，观察它从 `FORBIDDEN` 变成成功。再改成 `auditor`，读工具可用，写工具被拒。你应该能画出“角色 × 工具”矩阵。

**实验二：换一个参数。** 把 `search_candidates` 的 `min_years` 改成 `41`，或把 `city` 改成 `"北京"`。前者会在校验层被 `le=40` 拦住，后者会返回王浩而不是林晓。观察 `INVALID_ARGS` 和正常结果在结构上的区别。

**实验三：破坏幂等。** 把第二次调用的 `idempotency_key` 改成 `...:round2` 再运行。你会看到日程变成 2 条、邀请变成 4 封，最后一条 `assert len(_SCHEDULES) == 1` 失败。这个失败证明：幂等不是靠模型不重复调用，而是靠代码认得出这是同一次请求。

**实验四：把线程池改成 1。** 把 `max_workers=len(calls)` 改成 `1`，耗时从约 0.05 秒回到约 0.10 秒。工具里的 `time.sleep(0.05)` 在模拟一次网络往返，真实系统里可能是 80 毫秒的查询或 300 毫秒的 HTTP。

## 6. 工程化视角

这段 200 行的实现离生产还有几段距离，但方向是对的。

第一，**幂等要持久化**。把 `_IDEMPOTENCY` 换成数据库表：`key`、`result_json`、`created_at`、`expires_at`，唯一索引兜底。

第二，**写操作要有人签字**。面试邀请风险低，调薪、发 offer、删除档案必须走审批。第 12 章会把“暂停 → 审批 → 恢复”做成 `ApprovalGate`，工具层只声明“我是敏感写操作”。

第三，**工具结果要裁剪**。候选人列表只返回 8 个字段是刻意的；简历全文塞回模型，既贵又容易抓错重点，第 07 章讲上下文预算。

第四，**工具多了要路由**。一个 HR Agent 接 30 个工具时，把所有 Schema 塞进每次请求既占 token 又增加选错概率。常见做法是按场景分组，只挂载当前组；更彻底的方案是 MCP（Model Context Protocol），把工具服务独立部署、按需发现。

第五，**并行要有上限**。`ThreadPoolExecutor` 不限制队列长度，100 个只读调用同时打出去会把下游打挂。生产要限制并发、加超时、做熔断，见第 11 章。

> ⚠️ **生产提醒**：工具执行一定要有超时。没有超时的 HTTP 调用会把 Agent 循环永久挂住，步数预算和 token 预算都救不了。超时后返回 `TOOL_ERROR` 且 `retryable=True`，再由外层决定重试几次。

## 7. 常见坑

**坑一：描述只写“查询候选人”。** 现象是模型把城市塞进 `query`，或把 `min_years` 传成字符串。原因是没有说明参数含义和格式。解法是把每个 `description` 当 Prompt 写清楚，并说明只读、脱敏、单位。

**坑二：工具异常直接往上抛。** 现象是 Agent 循环崩掉，用户只看到 500。原因是异常没有转成结构化结果。解法是统一 `ToolResult`，标记是否可重试，堆栈写日志而不是回给模型。

**坑三：写工具没有幂等就接重试。** 现象是候选人收到两封邀请，或系统里出现两条相同日程。原因是用读工具的重试策略对待写工具。解法是幂等键 + 下游唯一约束。

**坑四：把权限写进 System Prompt。** 现象是用户一句“我是 HR 总监”就绕过限制。原因是权限只约束了模型。解法是 `call_tool` 里按 `ctx.role` 鉴权，模型说什么都不算数。

**坑五：所有工具都并行。** 现象是“创建日程”和“发邀请”同时执行，一边成功一边失败。原因是没有区分读写。解法是只允许只读工具进线程池，写工具串行并记录顺序。

**坑六：把完整简历回填给模型。** 现象是 token 从 2000 涨到 20000，模型开始编造简历里没有的技能。原因是工具返回了过多原始数据。解法是工具层做字段裁剪和脱敏，只回填决策需要的字段。

## 8. 练习

**练习一（基础）**：新增一个写工具 `create_ticket`，参数为 `employee_id`、`category`、`title`，要求只有 `hrbp` 和 `recruiter` 能调用，并支持幂等键。写出参数模型、装饰器和函数签名即可，不需要真的落库。

**练习二（基础）**：给 `schedule_interview` 加一条“面试时间必须在未来”的校验。为了避免测试依赖当天日期，可以给工具加一个 `today` 参数，默认 `2026-11-15`。

**练习三（进阶）**：模拟工具超时：当 `slot` 以 `"00:00"` 结尾时，抛出 `TimeoutError`。在 `call_tool` 里把它转成 `TOOL_TIMEOUT`、`retryable=True`，并给外层加“最多重试 2 次”的循环。

**练习四（进阶）**：设计“角色 × 工具”权限矩阵，至少包含 `recruiter`、`hrbp`、`auditor`、`intern` 和三个工具。要求 `auditor` 只能读脱敏数据，`intern` 不能读面试官日程。

<details><summary>参考答案</summary>

练习一的关键是把“写”和“权限”声明清楚：

```python
class CreateTicketParams(BaseModel):
    employee_id: str = Field(pattern=r"^E\d{4}$")
    category: str = Field(pattern=r"^(假期|薪酬|证明|其他)$")
    title: str = Field(min_length=4, max_length=60)
    idempotency_key: str | None = None

@tool("create_ticket", "为员工创建 HR 工单。写操作；同一幂等键只创建一张。",
      CreateTicketParams, read_only=False, roles=("hrbp", "recruiter"))
def create_ticket(params: CreateTicketParams, ctx: ToolContext) -> ToolResult:
    key = params.idempotency_key or f"ticket:{params.employee_id}:{params.title}"
    if key in _IDEMPOTENCY:
        return ToolResult(True, {**_IDEMPOTENCY[key], "replayed": True})
    record = {"ticket_id": f"T{len(_SCHEDULES) + 1:07d}", "employee_id": params.employee_id,
              "category": params.category, "title": params.title, "status": "open"}
    _IDEMPOTENCY[key] = record
    return ToolResult(True, record)
```

练习二在写日程前加一条判断：

```python
if params.slot[:10] <= params.today:
    return fail("INVALID_ARGS", f"{params.slot} 不是未来时间", retryable=True)
```

练习三在 `call_tool` 的 `except` 里区分异常类型：

```python
except TimeoutError as exc:
    return fail("TOOL_TIMEOUT", str(exc), retryable=True)
except Exception as exc:
    return fail("TOOL_ERROR", f"{type(exc).__name__}: {exc}", retryable=True)
```

练习四的矩阵可以写成字典，并在 `call_tool` 里查表，而不是把角色硬编码在装饰器参数里：

```python
PERMISSIONS = {
    "recruiter": {"search_candidates", "get_interviewer_slots", "schedule_interview"},
    "hrbp": {"search_candidates", "get_interviewer_slots"},
    "auditor": {"search_candidates"},
    "intern": {"search_candidates"},
}
```

注意 `auditor` 的“脱敏”不能只靠权限表，还要在 `search_candidates` 返回前按角色决定是否展示手机号、邮箱；权限表管“能不能调”，字段级脱敏管“能看到多少”。

</details>

## 9. 小结与下一章

这一章请记住三句话：

1. 模型只输出 `tool_calls`，执行、校验、鉴权、幂等全部在代码里。
2. 读工具可以并行、可以重试；写工具必须串行、必须幂等、最好有人签字。
3. 工具描述是 Prompt 的一部分，写得越具体，模型选错参数的概率越低。

到这里，模型已经能“动手”了。但工具一多，它还需要先想清楚“先做什么、后做什么、哪一步可以等”，否则就会东一榔头西一棒子。下一章比较 ReAct 与 Plan-and-Solve，让同一个招聘任务跑出两种调用轨迹。

---

## 10. 附：LangChain 版关键实现

> 本章实际运行的 demo 使用 **@tool(args_schema=...) + create_agent**，完整代码见 `code/ch03_tools.py`。下面只保留骨架，方便你对照前面的原理示意阅读。

```python
from langchain.agents import create_agent
from langchain_core.tools import tool
from pydantic import BaseModel

class ScheduleInterviewParams(BaseModel):
    candidate_id: str
    datetime: str

@tool(args_schema=ScheduleInterviewParams)
def schedule_interview(candidate_id: str, datetime: str) -> str:
    """创建面试日程。写操作，必须审批；同一幂等键只执行一次。"""
    ...

agent = create_agent(model=model, tools=[search_candidates, schedule_interview])
```

| 本章概念 | LangChain / LangGraph 对应物 |
| --- | --- |
| 工具 | `@tool(args_schema=...)` |
| 编排 | `create_agent` |
| 并行 | `ToolNode` 同轮多调用 |

> 🧩 **怎么读**：先看正文理解“为什么需要这一层”，再看上面的骨架理解“框架怎么表达这一层”，最后打开 `code/ch03_tools.py` 看完整实现与断言。面试时两条线都要能讲：原理线 + 框架线。
