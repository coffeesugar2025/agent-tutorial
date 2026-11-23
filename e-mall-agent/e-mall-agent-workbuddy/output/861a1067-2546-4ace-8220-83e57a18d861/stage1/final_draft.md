# 电商智能体 Agent 面试题 100 问与详解

本面试题集基于一个完整可运行的电商智能体项目：后端采用 Python 3 + FastAPI + LangChain 1.5.2 + LangGraph 1.2.23，前端采用 Vue 3 + TypeScript + Vite + Pinia。项目覆盖 MCP 工具、上下文工程、RAG、多智能体、工作流、人工审批、流式输出、权限审计与可视化。每道题均给出**考点解析**、**项目实现**与**可展开的追问答案**，既可用于面试复习，也可作为项目答辩脚本。

## 第一章 项目全景与技术选型

### Q1. 请整体介绍这个电商智能体项目的技术架构。

**考点：** 候选人是否能把框架能力映射到真实业务系统，而不是只背概念。

**答案：**

项目采用前后端分离架构。前端是 Vue 3 + TypeScript + Vite + Pinia，负责对话、商品、订单、工作流可视化和管理后台五个页面。后端是 FastAPI，按领域分为 `domain`、`security`、`context`、`rag`、`llm`、`mcp`、`agents`、`workflows`、`observability`、`api` 十层模块。

核心链路是：前端 POST `/api/chat/stream` → FastAPI 依赖注入解析 Bearer Token 并绑定请求身份 → Supervisor 图执行 `context`（上下文装箱）→ `route`（意图路由）→ 四个 specialist 之一（`create_agent` + 工具调用）→ `finalize`（汇总答案）→ SSE 逐事件推送前端。订单履约则走独立的 LangGraph 状态图，支持 `interrupt()` 人工审批。

框架版本上锁定 `langchain==1.5.2`、`langgraph==1.2.23`，通过 `langchain-mcp-adapters` 接入 MCP。所有业务工具定义在 `app/mcp/tools.py`，同一个函数既被 FastMCP Server 注册，也被进程内 `StructuredTool` 包装，保证工具行为单一真源。

### Q2. 为什么选择 LangChain 1.5 和 LangGraph 1.x，而不是旧版 LangChain 0.x？

**考点：** 对框架演进的理解与版本迁移意识。

**答案：**

LangChain 1.x 把 Agent 运行时统一到了 `create_agent`，底层基于 LangGraph 编译出的状态图。旧版 `AgentExecutor` 的循环逻辑较黑盒，中间件、状态检查点、人工介入、流式事件都难以统一治理。1.5 提供 `langchain.agents.middleware` 标准钩子，可以把摘要、重试、调用上限、PII 脱敏、工具埋点组合成可复用管道。

LangGraph 1.x 则把工作流显式建模为 `StateGraph`，支持 `Annotated` reducer、`checkpointer`、`interrupt`/`Command(resume=...)` 和 `astream(updates)`。这正好满足订单履约这种需要人工审批、状态恢复和可视化的场景。因此项目用 LangChain 的 Agent 能力处理“导购/订单/售后”这类开放推理，用 LangGraph 处理“履约审批”这类确定性流程。

工程上还做了一个务实选择：依赖版本写入 `requirements.txt` 与 `pyproject.toml`，并在实现前用脚本探测真实 import 路径，避免按旧教程写出无法运行的代码。

### Q3. 项目默认离线模型是如何工作的？如何切换到真实大模型？

**考点：** 可测试性与依赖注入设计。

**答案：**

`app/llm/factory.py` 中的 `get_model()` 根据 `ECOM_LLM_PROVIDER` 决定模型。默认值 `offline` 返回 `RuleBasedChatModel`，它继承 `BaseChatModel`，实现 `_generate`、`bind_tools`、`_llm_type`，因此能被 `create_agent` 当作标准聊天模型使用。

离线模型用规则关键词识别意图，例如“退款/退货/售后”映射到 `initiate_refund` 或 `rag_search`，“我的订单/物流”映射到 `list_orders` 或 `get_order`，“推荐/耳机/价格”映射到 `search_products`。命中工具时产出带 `tool_calls` 的 `AIMessage`，工具结果回灌后再把 JSON 渲染成中文回答。没有命中时返回问候语或“当前角色没有可用工具”的提示。

切换真实模型只需设置 `ECOM_LLM_PROVIDER=openai`、`ECOM_OPENAI_API_KEY=...`，并安装 `langchain-openai`。`get_model()` 会返回 `ChatOpenAI(model=settings.llm_model, temperature=0, streaming=True)`。Agent、中间件、工作流代码完全不用改，因为它们只依赖 `BaseChatModel` 接口。

### Q4. 一次“我的订单”请求从前端到后端经历了哪些步骤？

**考点：** 全链路追踪能力。

**答案：**

1. 前端 `ChatView.vue` 调用 `chatStream()`，`src/api/client.ts` 从 `localStorage` 读取 `ecom_token`，以 Bearer 头 POST 到 `/api/chat/stream`。
2. FastAPI 的 `current_user` 依赖解析 Token，失败则回落为 guest；`set_current_user` 把用户写入 `ContextVar`，请求结束时 `reset_current_user`。
3. `require("chat:use")` 校验权限，guest/customer/service/admin 都有该权限。
4. `stream_agent()` 构建 Supervisor 图：先从 `ConversationStore` 取历史，再构造 `thread_id`。
5. `context` 节点检索 RAG 文档、过滤可用工具，用 `ContextEngine` 打包系统消息并记录 trace。
6. `route` 节点调用 `classify_route()`，识别为 `order`。
7. `order` agent 调用 `list_orders`，工具内部再次校验 `order:read` 与 `customer_id` 归属，返回当前用户订单 JSON。
8. `finalize` 节点取出最后一条非空、无工具调用的 `AIMessage` 作为最终答案。
9. `astream(stream_mode="updates")` 产出节点更新，路由层转换为 `node`、`context`、`route`、`tool`、`token`、`done` 六类 SSE 事件。
10. 前端按 `\n\n` 分帧解析事件，实时显示节点进度、工具芯片和逐段回答。

### Q5. 什么是“工具单一真源”原则？项目如何落地？

**考点：** 避免 MCP 与本地工具行为漂移。

**答案：**

如果为 MCP Server 写一套工具，又为 Agent 本地调用写另一套同名工具，很容易出现参数、鉴权、审计逻辑不一致。项目的做法是：所有业务函数只写在 `app/mcp/tools.py`，共 8 个函数。FastMCP Server 通过 `for _fn in ALL_TOOL_FUNCTIONS: mcp.tool()(_fn)` 注册；进程内 `local_tools()` 用 `StructuredTool.from_function` 包装同一批函数；HTTP 模式则由 `MultiServerMCPClient` 从远端拉取工具。三条路径共享同一实现、同一权限校验、同一审计日志。

收益有三点：测试只需覆盖一份业务函数；`local` 与 `http` 模式切换不会改变业务语义；真实 MCP stdio 协议测试和进程内单元测试可以互相印证。

### Q6. 项目中的单例状态如何管理？测试如何避免互相污染？

**考点：** 全局状态与测试隔离。

**答案：**

项目使用多个模块级单例：`get_repository()`、`get_rag_pipeline()`、`get_tracer()`、`get_audit_logger()`、`get_fulfillment_graph()`、`get_conversation_store()`。它们都是懒加载，第一次调用时创建。

测试隔离靠两个手段。第一，`conftest.py` 在每个测试前调用 `reset_repository()`、`reset_rag_pipeline()`、`get_conversation_store().clear()`、`get_tracer().clear()`、`get_audit_logger().clear()`，恢复种子状态。第二，Supervisor 的 checkpointer 配置使用 `f"{thread_id}-{uuid.uuid4().hex[:8]}"`，每次运行生成唯一 `thread_id`，避免历史检查点串扰；履约工作流则允许显式传入 `thread_id` 以便测试恢复。

面试可强调：这是演示系统的取舍。生产环境应把仓储换成数据库事务，把 checkpointer 换成 Redis/Postgres，把会话历史放到带 TTL 的 Redis，把单例改为请求作用域依赖注入。

### Q7. 核心配置项有哪些？

**考点：** 配置驱动设计。

**答案：**

`app/config.py` 定义 `Settings`，使用 `pydantic-settings`，环境变量前缀为 `ECOM_`，`.env` 文件自动加载。关键配置包括：

- `llm_provider` / `llm_model` / `openai_api_key`：模型切换。
- `mcp_mode` / `mcp_http_url`：本地进程内或 HTTP MCP。
- `context_max_chars=3200`、`context_recent_messages=8`：上下文预算与历史窗口。
- `rag_top_k=3`：检索条数。
- `secret_key`、`token_ttl_seconds=3600`：HMAC Token 签名与有效期。
- `audit_max_entries=500`：审计日志容量。

`get_settings()` 用 `lru_cache(maxsize=1)` 缓存，避免每次调用重新读环境变量。测试若要改配置，需要在导入相关模块前清理缓存或使用 monkeypatch。

### Q8. 这个项目离生产还有哪些差距？

**考点：** 清醒的工程边界意识。

**答案：**

第一，数据在内存中，进程重启即丢失，并发写入靠 `threading.RLock`，不适合多实例部署。第二，`InMemorySaver` 检查点不能跨进程恢复。第三，HMAC Token 是教学实现，没有刷新令牌、吊销列表、密码哈希和企业 IdP。第四，CORS 当前放行所有来源，生产必须收敛。第五，离线模型的意图识别是关键词规则，真实场景需要 LLM 路由加评测集。第六，审计和 trace 只在内存，需接入 ELK/OpenTelemetry。第七，`ToolRetryMiddleware` 与 `ModelCallLimitMiddleware` 只是基础稳定性，还缺限流、熔断、预算控制、幂等键与灰度发布。

回答时建议给出替换点：仓储→SQL/ORM + 事务；Token→OAuth2/JWT；checkpointer→持久化后端；trace→OpenTelemetry；RAG→向量数据库 + 重排模型；模型→带降级链的真实 LLM。

## 第二章 LangChain 核心抽象

### Q9. LangChain 中四类核心消息类型是什么？项目中分别怎么用？

**考点：** Messages 是 Agent 状态的基本单位。

**答案：**

`SystemMessage` 承载角色、规则、用户身份、RAG 知识和工具清单，由 `ContextEngine.build()` 统一生成。`HumanMessage` 是用户输入，`_input_state()` 把 `user_input` 包成它。`AIMessage` 有两种形态：纯文本回答，或 `content=""` 且带 `tool_calls` 的工具调用意图。`ToolMessage` 是工具执行结果，带 `tool_call_id` 与 `name`，回灌给模型后才能生成最终答案。

面试要点：在 LangGraph 里消息常常是状态字段，例如 `SupervisorState["messages"]` 用 `Annotated[list[BaseMessage], operator.add]` 声明为可累加字段。最后取答案时要倒序找“有 content 且没有 tool_calls 的 AIMessage”，避免把中间的工具调用消息误当答案。

### Q10. 什么是 BaseChatModel？项目的离线模型实现了哪些契约？

**考点：** 模型可替换的前提是统一接口。

**答案：**

`BaseChatModel` 是 LangChain 对所有聊天模型的抽象，核心方法是 `_generate`（同步）和 `_agenerate`（异步），外层提供 `invoke`、`ainvoke`、`stream`、`batch` 等统一入口。`RuleBasedChatModel` 继承它，实现 `_llm_type` 返回 `"ecom-rule-based-offline"`，实现 `_generate` 返回 `ChatResult(generations=[ChatGeneration(message=...)])`，并重写 `bind_tools` 保存可调用工具列表。

因为接口一致，`create_agent(model=RuleBasedChatModel(), tools=[...])` 与 `create_agent(model=ChatOpenAI(...), tools=[...])` 的写法完全相同。这就是工厂模式 + 接口抽象的收益。

### Q11. `bind_tools()` 做了什么？

**考点：** 工具如何进入模型上下文。

**答案：**

`bind_tools` 把工具的 schema 绑定到模型，使模型在生成时可以输出符合格式的 `tool_calls`。在 `RuleBasedChatModel` 中，它只是 `model_copy(update={"bound_tools": list(tools)})`，因为规则模型不需要把 JSON Schema 发给远端；真正的 `ChatOpenAI` 会把工具定义转成 function calling 参数。

关键逻辑在 `_generate`：先 `pick_tool(user_text)` 得到工具名，再检查该名字是否在 `bound_tools` 中。只有绑定过的工具才允许调用。这一步相当于在模型侧做了一次“工具白名单”检查，与后面的 RBAC 过滤形成双保险。

### Q12. `AIMessage.tool_calls` 的结构是什么？

**考点：** 工具调用协议细节。

**答案：**

`tool_calls` 是字典列表，典型结构为：

```python
{
    "name": "list_orders",
    "args": {"customer_id": "U001"},
    "id": "call_ab12cd34ef",
    "type": "tool_call",
}
```

`name` 必须匹配已绑定工具名，`args` 必须满足工具参数 schema，`id` 用于和后面的 `ToolMessage.tool_call_id` 对应，`type` 固定为 `tool_call`。项目用 `uuid.uuid4().hex[:10]` 生成 id，保证并发调用不冲突。

面试可补充：真实模型的工具调用常是流式分片到达的，Agent 运行时会负责拼装完整参数后再执行工具。

### Q13. 为什么必须把 ToolMessage 回灌给模型？

**考点：** ReAct 循环闭环。

**答案：**

模型只知道“我准备调用什么工具”，不知道工具真实返回了什么。工具执行后必须以 `ToolMessage(content=..., tool_call_id=..., name=...)` 的形式放回消息列表，下一次模型调用才能基于事实生成答案。项目的 `RuleBasedChatModel._answer_from_tools()` 会遍历所有 `ToolMessage`，按工具名用 `_format_tool_result` 把 JSON 转成中文句子；如果没有回灌，模型只能说“已处理完成”。

在 LangGraph 中，这一步由 `create_agent` 编译出的图自动完成：模型节点产出工具调用 → 工具节点执行 → 结果作为 ToolMessage 追加到状态 → 回到模型节点。

### Q14. 什么是 LCEL？项目中哪里体现了 LCEL 思想？

**考点：** 组合式 Runnable 管道。

**答案：**

LCEL（LangChain Expression Language）用 `|` 把 `Runnable` 组合成管道，例如 `prompt | model | StrOutputParser()`。每个组件都实现统一的 `invoke/ainvoke/stream/batch`，组合后自动支持流式、并行、回调和错误传播。

项目生产链路主要通过 `create_agent` 和 StateGraph 编排，但在测试与知识用例中覆盖了 LCEL 管道、`RunnableLambda`、`RunnableParallel`、`batch` 和回调。比如可以用 `ChatPromptTemplate.from_template("用户说: {q}") | RuleBasedChatModel() | StrOutputParser()` 验证最简管道。面试时可以说：LCEL 适合无状态的线性链路，Agent/Graph 适合有状态、有分支的链路，两者不是替代关系。

### Q15. PromptTemplate 与 ChatPromptTemplate 有什么区别？

**考点：** 提示词结构化。

**答案：**

`PromptTemplate` 产出纯字符串，适合普通文本模型；`ChatPromptTemplate` 产出消息列表，可以区分 system/human/ai 角色，适合聊天模型。项目没有用模板字符串拼接系统提示，而是由 `ContextEngine` 生成 `SystemMessage`，原因是上下文内容来自多个动态区块（角色、身份、RAG、工具清单），且有优先级和预算裁剪逻辑，模板表达力不够。

如果面试官追问“如何防止提示词注入”，可以回答：项目把用户身份、权限规则和工具白名单放在 SystemMessage，并在工具内部做二次鉴权，因此即使输入里写“忽略前面的规则”，也无法绕过权限校验。

### Q16. 输出解析器在项目中扮演什么角色？

**考点：** 非结构化输出转结构化数据。

**答案：**

LangChain 提供 `StrOutputParser`、`JsonOutputParser`、`PydanticOutputParser` 等，把模型文本转成程序可用的结构。项目里的工具返回是已经 `json.dumps` 的字符串，因此解析主要发生在 `RuleBasedChatModel._format_tool_result()`：用 `json.loads` 还原商品列表、库存信息、订单对象，再渲染成中文。

这是一个务实取舍：离线模型不会产生格式错误的 JSON；若换成真实模型，建议用 `response_format` 或 `PydanticOutputParser` 做结构化输出校验，避免模型自由文本导致下游解析失败。

### Q17. `invoke`、`batch`、`stream` 分别适合什么场景？

**考点：** Runnable 统一接口。

**答案：**

`invoke` 是单条同步调用，适合 API 的普通 `/chat`。`batch` 并行处理多条输入，适合离线评测集。`stream` 逐块产出，适合 SSE 实时渲染。项目的 `/chat` 用 `run_agent` 一次性返回，`/chat/stream` 用 `astream` 产出节点事件；在模型层，`RuleBasedChatModel.stream()` 会把最终答案切成 `AIMessageChunk` 序列，便于前端逐字显示。

注意一个易错点：`stream()` 产出的是消息块对象而不是裸字符串，需要用 `chunk.content` 拼接。项目中曾有测试用例错误假设为字符串，修正后才通过。

### Q18. Callbacks 与项目里的 TraceCollector 有什么区别？

**考点：** 可观测性层次。

**答案：**

LangChain Callback 是框架内置的生命周期钩子，例如 `on_llm_start`、`on_llm_end`、`on_tool_start`，通常通过 `config={"callbacks": [...]}` 注入，适合接入 LangSmith 等生态。项目的 `TraceCollector` 是业务级 trace：记录 `ts/trace_id/node/event/payload`，由各节点、`@wrap_tool_call` 中间件和人工审批节点主动写入，供 `/api/traces` 和管理页消费。

两者可以共存。 Callback 更细粒度、偏框架事件；TraceCollector 更贴近业务语义，比如“context_built”“intent”“agent_start”“approval interrupt”。生产环境建议把 TraceCollector 适配成 OpenTelemetry Span，统一链路追踪。

### Q19. SystemMessage 里应该放什么？项目如何构造？

**考点：** 上下文工程设计。

**答案：**

SystemMessage 应放稳定、高优先级、必须遵守的信息：角色Persona、用户身份与权限边界、检索到的知识、可用工具清单。项目 `ContextEngine.build()` 把这些组织成四个 section，每个 section 带 `priority`（数字越小越重要），按优先级装入预算。输出形如：

```text
[角色与硬性规则]
你是电商平台的智能客服编排器...

[用户身份]
当前用户: U001 / 角色: customer...

[检索增强知识]
- [售后政策] 七天无理由退货...

[可用工具清单]
- search_products: 按关键词搜索在售商品...
```

要点是不要把动态历史和用户当前问题混进 SystemMessage，历史由 `compact()` 处理，当前问题单独作为 HumanMessage。

### Q20. `create_agent` 与旧版 `AgentExecutor` 的核心差别是什么？

**考点：** LangChain 1.x Agent 运行时。

**答案：**

`create_agent` 返回一个编译好的 LangGraph 图，节点包括模型推理与工具执行，状态是 `AgentState`。它天然支持 `checkpointer`、`stream_mode`、中间件、结构化输出与人工介入。旧版 `AgentExecutor` 是一个循环执行器，配置分散在 `agent_kwargs`、`callbacks`、`handle_parsing_errors` 等参数中，难以做细粒度可观测和状态治理。

项目用 `create_agent` 创建四个 specialist，并传入 `name`、`system_prompt`、`tools`、`middleware`。面试可补充：从 0.x 迁移时要重写中间件与回调逻辑，工具定义本身基本兼容。

## 第三章 工具与 Function Calling

### Q21. `@tool` 装饰器和 `StructuredTool.from_function` 有什么区别？

**考点：** 工具定义方式。

**答案：**

`@tool` 是声明式写法，从函数签名、类型注解和 docstring 自动生成工具名、参数 schema 和描述，适合快速定义简单工具。`StructuredTool.from_function` 是命令式写法，可以显式指定 `name`、`description`，更适合包装已有函数，尤其是函数名或 docstring 不适合直接暴露给模型的场景。

项目选择后者，因为业务函数已经统一定义在 `mcp/tools.py`，函数名就是稳定的工具契约，docstring 是面向模型的中文描述。`local_tools()` 把它们逐个包装为 LangChain 工具，而不需要修改业务函数本身。

### Q22. 工具描述（docstring）为什么重要？

**考点：** 工具选择质量。

**答案：**

模型根据工具名和描述决定是否调用、传什么参数。描述应该写清楚“做什么、参数是什么、返回什么、什么场景用”。项目的描述如“按关键词搜索在售商品，返回商品 id、名称、价格与库存。query 可为商品名、品类或需求描述”，明确告知输入与输出，能降低误调用率。

面试可补充：真实模型中工具描述是提示词的一部分，过多相似工具会增加选择歧义；应控制工具数量、用 `TOOL_SETS` 做按角色/按专家的工具子集隔离。

### Q23. 工具参数 schema 是怎么来的？

**考点：** Pydantic 与类型注解。

**答案：**

`StructuredTool.from_function` 会读取函数签名与类型注解生成 JSON Schema。例如 `search_products(query: str)` 生成必填字符串参数 `query`；`create_order(customer_id: str, items_json: str)` 生成两个必填字符串。真实模型据此构造 `tool_calls.args`。

项目为了跨 MCP 与本地调用简单，把复杂结构用 JSON 字符串传递，例如 `items_json='[{"product_id":"P001","quantity":1}]'`。生产环境更推荐用 Pydantic 模型作为工具参数，让框架自动生成更严格的 schema 并做校验。

### Q24. 工具返回 JSON 字符串有什么利弊？

**考点：** Agent 与工具的解耦边界。

**答案：**

优点是简单、稳定、跨语言友好：MCP、HTTP、进程内调用都能直接返回字符串；前端 trace 也能原样展示。项目用 `_json(data)` 统一 `json.dumps(..., ensure_ascii=False, default=str)`，保证中文不转义、Pydantic 对象可序列化。

缺点是丢失类型信息，下游必须自己解析；模型需要额外理解 JSON。项目的离线模型用 `_format_tool_result` 按工具名格式化，真实模型则可以直接读 JSON。面试时可以说：如果全面转向结构化输出，可用 `response_format` 或让工具返回 Pydantic 对象，由框架自动序列化。

### Q25. 项目暴露了哪 8 个业务工具？分别需要什么权限？

**考点：** 工具清单与权限映射。

**答案：**

1. `search_products(query)` → `product:read`
2. `get_product(product_id)` → `product:read`
3. `check_inventory(product_id)` → `product:read`
4. `create_order(customer_id, items_json)` → `order:create`
5. `list_orders(customer_id)` → `order:read`
6. `get_order(order_id)` → `order:read`
7. `initiate_refund(order_id, reason)` → `order:refund`
8. `rag_search(query)` → `chat:use`

映射定义在 `TOOL_PERMISSIONS`，`permission_for_tool()` 对未登记工具默认要求 `chat:use`。这体现“默认最小权限”的设计：新工具如果忘记登记，也不会裸奔。

### Q26. 为什么工具内部还要做二次鉴权？

**考点：** 纵深防御。

**答案：**

API 层依赖 `require_permission` 只能保护 HTTP 入口；同一个工具还可能被 MCP Server、Agent、脚本或测试直接调用。项目在每个工具函数开头检查 `has_permission(get_current_user(), ...)`，涉及客户数据的还检查 `can_access_customer()`。拒绝时调用 `_deny()` 写审计并返回 `{"error": ..., "permission_denied": true}`，而不是抛异常中断 Agent 循环。

面试可强调：Agent 系统里“模型被提示词诱导调用越权工具”是真实风险，所以不能只依赖意图层过滤，必须在执行层再校验一次。

### Q27. `filter_tools()` 在哪里调用？解决了什么问题？

**考点：** 工具白名单前置。

**答案：**

`load_agent_tools()` 在两种 MCP 模式加载完工具后统一调用 `filter_tools(tools, user)`，把当前角色无权使用的工具从 Agent 的工具列表中移除。这样模型从一开始就看不到的工具，自然不会尝试调用，减少无效工具调用和 prompt 体积。

它与工具内二次鉴权是互补关系：前置过滤提升效率与安全性，后置校验防止绕过。

### Q28. 工具执行失败时项目如何处理？

**考点：** Agent 容错。

**答案：**

项目区分几种失败：权限不足返回结构化错误 JSON 并记审计；业务错误如商品不存在、库存不足返回 `{"error": "..."}`；参数解析异常在 `create_order` 里用 `try/except` 捕获并返回错误字符串。工具不直接抛异常，避免 Agent 循环崩溃。

在运行时层，还有 `ToolRetryMiddleware(max_retries=1, initial_delay=0.0, on_failure="continue")` 处理瞬时异常：失败后重试一次，仍失败则继续生成回答而不是中止。面试可补充生产改进：区分可重试错误（网络超时）与不可重试错误（权限拒绝），后者不应重试。

### Q29. 商品搜索如何处理中文？为什么不能简单按空格分词？

**考点：** 中文检索工程细节。

**答案：**

中文短语没有空格，按空格切分会得到整个句子，无法匹配“降噪耳机”这类关键词。项目复用 RAG 的 `tokenize()`：拉丁词用正则提取，中文串生成整串、bigram、trigram，例如“退货政策”产生“退货政策/退货/货政/政策/退货政/货政策”。“耳机”这类 bigram 就能命中商品标签与描述。

`search_products()` 对 query 和商品的名称、品类、描述、标签做 token 重叠打分，按长度加权，完整 query 出现在商品名时额外加 8 分，最后按分数降序、id 升序稳定排序返回前 5 条。这个修复来自测试失败，说明测试用例能反向驱动实现质量。

### Q30. 下单流程如何保证库存与订单一致？

**考点：** 业务事务意识。

**答案：**

`create_order(customer_id, items_json)` 先校验权限与客户归属，再解析 JSON 数组。`InMemoryRepository.create_order()` 在 `RLock` 内完成：逐项校验商品存在、数量大于 0、库存足够；全部校验通过后再统一扣减库存；生成 `O1004` 起的递增订单号，金额按 `unit_price * quantity` 四舍五入到两位；成功后写审计日志。

面试时应指出：内存锁只能保证单进程一致。生产中应使用数据库事务与行锁，例如 `SELECT ... FOR UPDATE` 或乐观锁版本号，并引入幂等键避免网络重试造成重复下单。

## 第四章 中间件与稳定性

### Q31. LangChain 1.5 中间件是什么？有哪些常用钩子？

**考点：** Agent 横切关注点。

**答案：**

中间件是包裹 Agent 执行过程的插件，类似 Web 框架中间件。常用钩子包括 `before_model`（模型调用前改写状态）、`after_model`（模型调用后处理）、`wrap_model_call`（包装模型调用）、`wrap_tool_call`（包装工具调用）。项目 `build_middleware()` 返回六个中间件：摘要、工具重试、模型调用上限、两个 PII 中间件和一个自定义工具埋点。

它的价值是把“上下文压缩、安全脱敏、限流、重试、观测”从业务逻辑中剥离，声明式组合到每个 Agent 上。

### Q32. `SummarizationMiddleware` 的参数如何配置？

**考点：** 长对话压缩。

**答案：**

项目配置为 `SummarizationMiddleware(model=get_model(), trigger=("messages", 14), keep=("messages", 6))`。含义是：当消息数达到 14 条时触发摘要，保留最近 6 条消息，其余由模型压缩成摘要。它解决的是长会话 token 膨胀问题。

注意它与 `ContextEngine.compact()` 是两层机制：前者在 Agent 消息层面按数量触发模型摘要，后者在上下文装箱时按字符预算做滑窗和截断。面试可说明这是“粗粒度 + 细粒度”的双重预算控制。

### Q33. `ToolRetryMiddleware` 如何避免瞬时故障？

**考点：** 重试策略。

**答案：**

项目配置 `max_retries=1, initial_delay=0.0, jitter=False, on_failure="continue"`：工具失败后最多重试 1 次，无退避延迟，最终失败时继续让模型生成回答。知识点测试里用一个“第一次抛异常、第二次成功”的 Flaky 工具验证 `attempts == 2`，证明中间件确实生效。

生产建议：增加指数退避与 jitter，设置最大总耗时，区分异常类型；对写操作（下单、退款）要谨慎重试，必须配合幂等键。

### Q34. `ModelCallLimitMiddleware` 为什么能防止死循环？

**考点：** Agent 运行时护栏。

**答案：**

Agent 可能因为模型反复输出工具调用而陷入循环。`ModelCallLimitMiddleware(run_limit=6, exit_behavior="end")` 限制单次运行最多 6 次模型调用，超过后按 `end` 行为结束运行。项目的 `RuleBasedChatModel` 本身是确定性的，不会无限循环，但接入真实模型后这个护栏很重要。

面试可补充：还应配合 `max_tokens`、超时、工具调用次数预算和成本告警，形成完整成本控制。

### Q35. 项目如何使用 PIIMiddleware？

**考点：** 隐私保护。

**答案：**

项目配置两个中间件：

```python
PIIMiddleware("email", strategy="redact", apply_to_input=True)
PIIMiddleware("phone_number", detector=r"1[3-9]\d{9}", strategy="mask", apply_to_input=True)
```

邮箱用内置检测器并替换为 `[REDACTED_EMAIL]`，手机号用自定义正则并做掩码。`apply_to_input=True` 表示在消息进入模型前脱敏，避免敏感信息被发送到远端模型或写入模型上下文。

知识点测试中，输入“联系我 abc@example.com 谢谢”，最终消息中原文消失且出现脱敏标记。面试可补充：如果业务需要真实手机号，应存于后端并在展示层按需解密，而不是放进 prompt。

### Q36. 自定义 `wrap_tool_call` 埋点如何工作？

**考点：** 中间件扩展。

**答案：**

项目定义异步中间件：

```python
@wrap_tool_call
async def trace_tool_call(request, handler):
    name = (request.tool_call or {}).get("name", "unknown")
    args = (request.tool_call or {}).get("args", {})
    result = await handler(request)
    get_tracer().record(current_trace_id.get(), "agent:tool", name,
                        {"args": args, "result": str(getattr(result, "content", result))[:400]})
    return result
```

它在工具执行前后记录调用名、参数和结果摘要到 trace。因为 Agent 是异步执行的，必须用 `async def` 并 `await handler(request)`；早期同步版本在异步链路中会失效，这是一个真实踩坑点。

### Q37. 中间件顺序会影响行为吗？

**考点：** 组合语义。

**答案：**

会。PII 脱敏应在模型调用前生效，摘要可能影响进入模型的消息历史，工具重试只包围工具调用，调用上限约束整体循环。如果顺序不当，可能出现“先摘要后脱敏导致原文已进入摘要”或“重试发生在鉴权之外”等问题。

项目按摘要 → 重试 → 调用上限 → PII → 工具埋点的顺序配置。面试可表达为：无状态转换类中间件前置，资源/安全类中间件贴近执行点，观测类中间件最外层或最内层取决于想记录原始还是处理后的数据。

### Q38. 为什么 PII 要 `apply_to_input=True`？

**考点：** 数据最小化。

**答案：**

如果只在输出侧脱敏，用户输入的手机号、邮箱已经进入模型上下文，甚至被发送到第三方大模型 API，隐私风险已经发生。`apply_to_input=True` 在数据离开应用边界前就处理，符合“数据最小化”原则。项目默认离线模型不会外发数据，但切换到 OpenAI 时这一设置仍然有效，保证安全策略不随模型切换而退化。

### Q39. 中间件与 TraceCollector 如何配合？

**考点：** 可观测性实现层次。

**答案：**

`trace_tool_call` 中间件把每次工具调用写入 TraceCollector；Supervisor 的节点函数分别写 `context_built`、`intent`、`agent_start`、`tool_result`、`answer`；履约工作流写 `validate.check`、`risk_review.interrupt`、`create_shipment.shipped`。管理页用 `/api/traces?limit=50` 拉取并按 trace_id 过滤，前端展示时间线。

面试可强调：trace 的 payload 要做截断，项目把工具结果截断到 400 字符、工具消息截断到 300/600 字符，避免大对象拖慢前端或泄露过多数据。

### Q40. 如何给不同 Agent 定制中间件？

**考点：** 多智能体差异化治理。

**答案：**

项目当前四个 specialist 共用 `build_middleware()`，因为都需要摘要、重试、限流、脱敏和埋点。若要差异化，可以在 `build_specialists()` 循环里按 `name` 选择不同列表，例如订单 Agent 增加更严格的 `ModelCallLimitMiddleware`，售后 Agent 增加对退款工具的 `HumanInTheLoopMiddleware`，导购 Agent 关闭摘要以保留更多商品细节。

关键是 `create_agent(..., middleware=...)` 接收列表，天然支持按 Agent 注入不同策略，无需修改 Agent 内部代码。

## 第五章 LangGraph 状态图与工作流

### Q41. StateGraph 的三个核心要素是什么？

**考点：** 图编排基础。

**答案：**

StateGraph 由状态定义、节点、边三部分组成。状态通常用 `TypedDict` 描述，声明图中流转的字段；节点是处理函数，接收当前状态并返回部分更新；边决定下一个节点，包括普通边、条件边、START 与 END。

项目的履约图定义了 `FulfillmentState`，包含 `order_id`、`customer_id`、`steps`、`status`、`amount`、`approved`、`message`；Supervisor 定义了 `SupervisorState`，包含 `messages`、`history`、`user_input`、`route`、`trace_id` 等。

### Q42. `Annotated[list[str], operator.add]` 有什么作用？

**考点：** 状态 reducer。

**答案：**

LangGraph 默认用节点返回的字段覆盖状态中的同名字段。对于列表类字段，常常希望“追加”而不是“覆盖”。`Annotated[list[str], operator.add]` 告诉图在合并时对 `steps` 或 `messages` 执行 `operator.add`，即列表拼接。

履约图的 `steps` 用这个 reducer，因此每个节点返回 `{"steps": ["库存已锁定"]}` 后，历史步骤不会丢失。Supervisor 的 `messages` 同理，工具调用与结果会不断追加，形成完整对话轨迹。

### Q43. 条件边如何决定分支？

**考点：** 显式工作流控制。

**答案：**

`builder.add_conditional_edges("validate", lambda s: "check_inventory" if s["status"] == "validated" else END)` 表示根据状态中的 `status` 选择下一节点。履约图有四个条件分支：校验失败直接 END、库存不足走 `rollback`、审批通过走 `create_shipment`、审批拒绝走 `cancel`。

Supervisor 图则用 `add_conditional_edges("route", lambda s: s["route"], {name: name for name in specialists})` 把路由结果映射到四个 Agent 节点。相比让模型自由决定下一步，条件边适合业务规则明确的场景，可测试、可审计。

### Q44. checkpointer 和 thread_id 的作用是什么？

**考点：** 状态持久化与会话隔离。

**答案：**

checkpointer 负责在每个超级步骤后保存图状态；`thread_id` 是状态的命名空间。项目两处使用：Supervisor 编译时用 `InMemorySaver()`，每次运行生成唯一 `thread_id`；履约图也用 `InMemorySaver()`，但允许调用方传入 `thread_id`，以便中断后用同一个 id 恢复。

面试要点：`thread_id` 相同意味着继续同一段状态机，`thread_id` 不同意味着新会话。测试中只有相同 id 才能 `Command(resume=...)` 恢复审批。

### Q45. `InMemorySaver` 有什么限制？

**考点：** 生产替换点。

**答案：**

它把检查点存在进程内存，进程重启丢失，无法跨多实例共享，也没有 TTL 和并发写冲突处理。适合本地演示与单元测试。生产应换成 `PostgresSaver`、`RedisSaver` 或自定义 BaseCheckpointSaver，并配合数据库事务和业务幂等键。

### Q46. `astream(stream_mode="updates")` 返回什么？

**考点：** 流式图执行。

**答案：**

它按节点执行顺序产出 `{节点名: 状态更新}` 的字典。项目遍历每个 update，先发 `{"event": "node", "node": 节点名}`，再检查 payload 中是否有 `context_snapshot`、`route`、`messages`、`final_answer`，转换为对应 SSE 事件。最终答案按 12 字符切片产生 `token` 事件，再发 `done`。

注意一个兼容处理：某些 LangGraph 版本的局部 update 里可能拿不到 `final_answer`，因此流结束后再调用 `graph.aget_state(config)` 从最终状态补取答案并写入会话历史。

### Q47. `interrupt()` 如何实现人工审批？

**考点：** Human-in-the-loop。

**答案：**

在 `risk_review` 节点中，如果金额不低于 500 且尚未审批，调用 `interrupt({...})`。LangGraph 会保存当前状态并暂停执行，返回值通过 `__interrupt__` 暴露给调用方。项目 `_serialize()` 检测到中断后把 `status` 改成 `awaiting_approval`，并把中断详情放到 `interrupt` 字段。

这让 API 可以先返回“等待审批”，前端展示批准/拒绝按钮，用户决策后再通过 `Command(resume=...)` 恢复。它比“在节点里轮询数据库”更结构化，因为状态机本身记录了挂起点。

### Q48. `Command(resume=...)` 如何恢复流程？

**考点：** 中断恢复机制。

**答案：**

`resume_fulfillment(thread_id, approved)` 用同一个 `thread_id` 调用 `graph.ainvoke(Command(resume=approved), config)`。LangGraph 从检查点恢复状态，把 `resume` 的值作为 `interrupt()` 的返回值交回 `risk_review` 节点。节点执行 `approved = bool(decision)`，条件边随后选择 `create_shipment` 或 `cancel`。

关键点：恢复时必须用同一个 thread_id；resume 值可以是布尔、字典或对象；审批动作应写审计日志，项目在 API 层记录 `workflow.approve`。

### Q49. 请画出订单履约工作流。

**考点：** 业务流程建模。

**答案：**

```text
START → validate → check_inventory
                    ├─ 库存充足 → reserve_stock → risk_review
                    │                              ├─ 批准 → create_shipment → complete → END
                    │                              └─ 拒绝 → cancel → END
                    └─ 库存不足 → rollback → END
validate 校验失败 → END
```

节点职责：`validate` 确认订单存在并读出金额；`check_inventory` 复核商品；`reserve_stock` 模拟锁库存；`risk_review` 对金额 ≥ 500 的订单触发人工审批；`create_shipment` 把订单状态改为 shipped；`complete` 收尾；`cancel` 和 `rollback` 把状态改为 cancelled。

### Q50. 为什么阈值设为 500？O1001 会触发审批吗？

**考点：** 业务规则与测试数据结合。

**答案：**

`APPROVAL_THRESHOLD = 500.0` 是演示用阈值，便于让种子订单触发人工审批。O1001 包含 P001×1（899）和 P005×1（199），总额 1098.0，大于 500，因此运行 `run_fulfillment("O1001", "U001", "wf-demo-1")` 会返回 `status="awaiting_approval"`，`interrupt.amount=1098.0`。调用 `resume_fulfillment("wf-demo-1", True)` 后继续发货。

面试时可说明：真实系统阈值应来自风控配置，并考虑币种、用户等级、商品类目、历史行为等因素。

### Q51. `_serialize()` 做了什么？

**考点：** 图状态到 API DTO 的转换。

**答案：**

`_serialize(result, thread_id)` 把图执行结果转成前端友好的结构：`thread_id`、`status`、`message`、`steps`。如果结果里有 `__interrupt__`，取第一条的 `value` 作为 `interrupt` 字段，并把 `status` 覆盖为 `awaiting_approval`。这样前端无需理解 LangGraph 内部对象，只根据 `status` 决定展示审批表单还是步骤时间线。

这是典型的防腐层设计：框架概念不直接泄漏到 API 契约。

### Q52. 如何查看一个工作流当前是否处于中断状态？

**考点：** 图状态查询 API。

**答案：**

可以用 `get_fulfillment_graph().get_state({"configurable": {"thread_id": thread_id}})`。返回值包含 `values`（当前状态）、`next`（下一个待执行节点）和 `interrupts`。项目知识点测试中，在 O1001 触发中断后检查 `next == ("risk_review",)` 且 `interrupts` 非空，证明图确实挂在审批节点。

面试可补充：生产环境应把“查询待审批任务”做成独立 API 或任务表，而不是让前端直接读图状态。

## 第六章 多智能体协作

### Q53. Supervisor 模式与 Agent 自由协商模式有什么区别？

**考点：** 多智能体拓扑。

**答案：**

Supervisor 模式由一个中心路由器决定把任务交给哪个专家，专家完成后汇总；优点是控制流清晰、成本可控、易审计。自由协商（如群聊式）更灵活，但容易循环、成本不可预测、调试困难。

项目采用 Supervisor：`classify_route()` 把输入映射到 shopping/order/support/general，四个 specialist 都是叶子节点，统一汇入 `finalize`。图拓扑在 `GRAPH_DESCRIPTIONS` 里可视化展示，前端能看到每个节点。

### Q54. 四个 specialist 分别负责什么？工具如何隔离？

**考点：** 专家分工与最小权限。

**答案：**

- `shopping`：商品导购，工具为 `search_products/get_product/check_inventory/rag_search`。
- `order`：订单专员，工具为 `list_orders/get_order/create_order/check_inventory`。
- `support`：售后专员，工具为 `rag_search/initiate_refund/get_order/list_orders`。
- `general`：通用助理，工具为 `rag_search/search_products`。

`TOOL_SETS` 定义白名单，`build_specialists()` 先按用户 RBAC 过滤全局工具，再按专家白名单取交集。这样售后 Agent 看不到下单工具，导购 Agent 看不到退款工具，既降低误调用，也落实最小权限。

### Q55. `classify_route()` 的路由规则是什么？

**考点：** 意图路由实现。

**答案：**

它先调用 `RuleBasedChatModel.pick_tool(text)` 得到候选工具：商品类工具映射到 `shopping`，订单类工具映射到 `order`；出现“退款/退货/售后/投诉/换货”直接映射 `support`；`rag_search` 再根据是否含“政策/保修/配送/发票/优惠券/运费/规则”等词决定 `support` 或 `general`；其余走 `general`。

这是一个确定性路由器，优点是零延迟、可复现、易测试；缺点是泛化能力有限。代码注释明确写了生产环境可替换为 LLM 路由。

### Q56. 为什么项目先用确定性路由而不是 LLM 路由？

**考点：** 工程务实性。

**答案：**

第一，演示项目要求零 API Key 可运行，离线模型本身就是规则驱动。第二，路由错误会直接把任务交给错误专家并可能触发错误工具，确定性规则更容易回归测试。第三，知识点测试可以断言输入“我的订单”一定路由到 `order`，这对教学和验收更友好。

生产升级路径是：用 LLM 输出枚举路由 + 置信度，低置信度走通用 Agent 或澄清问题，同时用评测集持续衡量路由准确率。

### Q57. Agent 节点如何保证 trace_id 不串？

**考点：** 并发上下文隔离。

**答案：**

`make_agent_node()` 在每个节点开始时用 `current_trace_id.set(state["trace_id"])` 设置 ContextVar，结束时在 `finally` 中 `current_trace_id.reset(marker)`。因为 ContextVar 是异步任务隔离的，多个请求并发执行时各自的 trace_id 不会互相污染。

同理，API 层用 `set_current_user(user)` / `reset_current_user(marker)` 绑定请求身份，工具内部通过 `get_current_user()` 读取。这是异步服务中传递请求上下文的正确方式，不能用全局变量。

### Q58. ConversationStore 与 checkpointer 有什么区别？

**考点：** 短期记忆 vs 状态快照。

**答案：**

`ConversationStore` 是业务层的对话历史，用 `thread_id` 存 `HumanMessage/AIMessage` 对，最多保留 12 轮（24 条消息），用于下一次请求的 `history` 字段。checkpointer 是 LangGraph 运行时状态，保存图在每个步骤的完整快照，用于中断恢复与状态查询。

两者都叫“记忆”但目的不同：前者是语义层面的聊天上下文，后者是执行层面的状态机快照。生产环境中前者适合 Redis + TTL，后者适合持久化 checkpointer。

### Q59. 为什么 `messages` 要用 reducer 而不是普通列表？

**考点：** 状态合并语义。

**答案：**

如果不用 reducer， Specialist 节点返回完整消息列表会覆盖之前由 `context` 节点生成的 SystemMessage。`Annotated[list[BaseMessage], operator.add]` 让每次返回的消息追加到现有列表，保留上下文、工具调用、工具结果和最终回答的完整序列。

这对调试很有价值：trace 和 `finalize` 都能从完整消息链中找出答案来源。面试可补充：`operator.add` 是浅层合并，如果需要去重或按 id 覆盖，可写自定义 reducer。

### Q60. 如何把 Supervisor 路由升级为 LLM 驱动？

**考点：** 演进设计。

**答案：**

可以新增一个 `llm_route` 节点，用 `ChatPromptTemplate` 让模型从枚举值中选择路由，并用 `PydanticOutputParser` 或 `response_format` 约束输出。置信度低时路由到 `general` 或触发澄清节点。然后把 `classify_route()` 保留为 fallback，形成“LLM 路由 + 规则兜底”。

同时要加路由评测集：收集典型问题与期望路由，回归测试准确率；记录误路由案例用于 prompt 优化。骨架不需要改，只需替换 `route` 节点实现。

## 第七章 MCP 协议

### Q61. MCP 是什么？解决了 Agent 的什么问题？

**考点：** 工具生态标准。

**答案：**

MCP（Model Context Protocol）是连接模型应用与外部工具/数据的开放协议，类似“AI 应用的 USB-C”。它定义 Server 如何暴露工具、资源和提示，Client 如何发现并调用它们。对 Agent 的价值是：工具可以独立部署、独立版本管理、跨语言复用，而不需要为每个框架重写适配层。

项目中 MCP Server 暴露 8 个电商工具，Agent 通过 `langchain-mcp-adapters` 把它们加载成 LangChain 工具。

### Q62. FastMCP Server 如何注册工具？

**考点：** MCP Server 实现。

**答案：**

项目用 `FastMCP("ecommerce-tools", host="127.0.0.1", port=8001, instructions=...)` 创建 Server，然后遍历 `ALL_TOOL_FUNCTIONS`，用 `mcp.tool()(_fn)` 注册。因为业务函数有类型注解和中文 docstring，FastMCP 能自动生成工具 schema 与描述。

运行方式：`python -m app.mcp.server --transport stdio` 或 `--transport streamable-http`。前者适合本地进程通信，后者适合服务化部署。

### Q63. stdio 与 streamable-http 适用什么场景？

**考点：** 传输层取舍。

**答案：**

stdio 通过标准输入输出与父进程通信，部署简单、无网络端口、天然本地隔离，适合 IDE 插件和本机工具。HTTP 适合跨进程、跨机器、多客户端共享工具服务，但需要处理认证、网络超时、服务发现。

项目两种都支持：测试里用 `MultiServerMCPClient` 以 stdio 启动 `python -m app.mcp.server` 并验证真实 ListTools/CallTool 往返；配置 `ECOM_MCP_MODE=http` 时 Agent 通过 `http://127.0.0.1:8001/mcp` 连接。

### Q64. `MultiServerMCPClient` 如何加载工具？

**考点：** MCP Client 集成。

**答案：**

```python
client = MultiServerMCPClient({
    "ecommerce": {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "app.mcp.server"],
    }
})
tools = await client.get_tools()
```

`get_tools()` 会完成工具发现并把 MCP 工具转换成 LangChain `BaseTool`。HTTP 模式下配置改为 `transport: "http"`、`url` 和 `headers`，项目会把当前 Token 放进 `Authorization` 头。

面试可补充：MCP Client 的生命周期需要正确关闭，生产中应使用长连接并在应用 shutdown 时释放。

### Q65. `mcp_mode=local` 与 `http` 的区别？

**考点：** 开发与生产路径统一。

**答案：**

`local` 不需要启动独立服务，直接用 `local_tools()` 把同一批业务函数包装成 LangChain 工具，启动快、便于测试。`http` 通过 `MultiServerMCPClient` 从独立 FastMCP Server 拉取工具，更接近生产拓扑。

两条路径最后都会经过 `filter_tools(tools, user)`，因此权限行为一致。面试时可强调：这让开发测试零依赖，又能验证真实协议路径。

### Q66. 真实 MCP 往返测试验证了什么？

**考点：** 测试金字塔中的协议层验证。

**答案：**

`test_tools.py` 中有一例用 stdio 启动独立 MCP Server，调用 `client.get_tools()` 断言工具数量与名称，再对工具执行 `ainvoke`。它验证的不只是函数逻辑，还包括：Server 能启动、工具能被发现、schema 能被客户端理解、参数能正确传递、结果能返回。这类测试能捕获“本地调用正常但协议路径断裂”的问题。

### Q67. MCP 工具如何知道当前用户是谁？

**考点：** 身份传播。

**答案：**

MCP 协议本身不携带项目业务身份。项目在 HTTP 模式把 Token 放进 header；工具函数内部再通过 `get_current_user()` 读取 API 层写入的 ContextVar。也就是说，鉴权决策仍在业务工具内完成，MCP 只负责传输。

严格来说，如果 MCP Server 独立进程运行且直接被外部客户端调用，API 层的 ContextVar 不会自动跨进程传播。这是项目当前架构的一个边界：生产环境需要在 MCP Server 侧解析 Token 并建立身份上下文，或使用网关统一鉴权。面试中主动指出这一点会显得很清醒。

### Q68. MCP 与 Function Calling 有什么区别？

**考点：** 概念层级。

**答案：**

Function Calling 是模型厂商提供的能力，让模型输出结构化工具调用意图；MCP 是工具发现与调用的协议标准，规定工具如何被描述、暴露和调用。两者不冲突：模型通过 Function Calling 决定调用哪个工具，Agent 运行时通过 MCP Client 真正执行远端工具。

项目里 `create_agent` 负责模型侧工具调用循环，`langchain-mcp-adapters` 负责把 MCP 工具接入这个循环。

## 第八章 RAG 检索增强

### Q69. RAG 的完整流程是什么？

**考点：** 检索增强基础。

**答案：**

RAG 分为索引和查询两阶段。索引阶段：加载文档 → 切分 → 向量化 → 写入向量库。查询阶段：用户问题向量化 → 向量检索 → 重排/过滤 → 拼入上下文 → 模型基于证据回答。

项目 `RAGPipeline` 在初始化时把 8 条种子文档写入 `InMemoryVectorStore`；`retrieve()` 先做向量召回，再用中文 n-gram 词面重叠重排，最后按 `top_k=3` 返回带 `source/category/content/score` 的结果。`ContextEngine.format_docs()` 把它们格式化进 SystemMessage。

### Q70. `HashEmbeddings` 如何实现？

**考点：** 无 Key 向量化。

**答案：**

`HashEmbeddings` 继承 `langchain_core.embeddings.Embeddings`，实现 `embed_documents` 与 `embed_query`。内部 `tokenize(text)` 得到 n-gram，对每个 token 用 `hashlib.blake2b` 得到 8 字节摘要，取前 4 字节转整数模 `dimension=128` 得到下标，用第 5 字节奇偶决定 +1 或 -1，累加后做 L2 归一化。

它确定、零依赖、无需 API Key，适合演示。缺点是语义能力弱，无法理解同义替换。生产应换成 `OpenAIEmbeddings` 或 BGE 模型，接口不变。

### Q71. `tokenize()` 如何处理中文？

**考点：** 中文分词策略。

**答案：**

拉丁字符用 `[a-z0-9_]+` 提取；中文连续串先整体作为一个 token，再生成所有 bigram，若长度大于 2 再生成 trigram。因此“退款政策”会生成整串、二字词和三字词片段。“退货”这类短查询虽然没有单字 token，但 bigram 能直接匹配。

知识点测试中曾错误断言包含单字“退”，修正后确认实现只产整串/bigram/trigram。这提醒面试者：读源码比凭直觉更可靠。

### Q72. `InMemoryVectorStore` 如何工作？

**考点：** 向量库接口。

**答案：**

它是 LangChain 提供的内存向量库，接收 `Embeddings` 实例，调用 `add_texts(texts, metadatas)` 写入，`similarity_search(query, k)` 按余弦相似度返回 `Document` 列表。项目把 `source` 和 `category` 写入 metadata，用于展示来源与分类过滤。

优点是零部署；缺点是重启丢失、数据量受限、无持久化索引。生产中替换为 Qdrant/Milvus/pgvector 时，只需重写 `RAGPipeline` 的 store 部分。

### Q73. 项目的混合排序如何打分？

**考点：** 召回与排序结合。

**答案：**

先用向量库召回 `max(k*3, len(SEED_DOCS))` 条候选，避免纯哈希向量噪声。然后对每条候选计算：`overlap = sum(len(t) for t in query_tokens & doc_tokens)`，即查询与文档共有 n-gram 的长度总和；如果某个 query token 出现在 `source` 字段，再加 4 分。按分数降序、候选索引升序排序，取前 k 条。

这样既利用向量召回的泛化，又用词面重叠保证“退款多久到账”这类短句能命中售后政策。面试可补充：生产应用 reranker 模型或 BM25 + 向量的混合检索。

### Q74. `category` 过滤和兜底逻辑是什么？

**考点：** 检索健壮性。

**答案：**

`retrieve(query, top_k, category)` 在遍历候选时检查 `meta["category"]` 是否等于指定分类，不匹配则跳过。若过滤后为空且没有指定 category，则用 `SEED_DOCS[:k]` 返回确定性兜底结果，保证上下文不为空、测试可重复。

设计意图是“宁可给通用政策，也不要让模型在完全没有证据时自由发挥”。生产中兜底应改成“无证据时明确回答不知道”，避免低质量检索误导模型。

### Q75. 种子知识库包含哪些分类？

**考点：** 业务知识边界。

**答案：**

8 条文档分四类：`policy`（七天无理由退货、质保规则）、`logistics`（配送时效、发货时间）、`promotion`（优惠券规则）、`payment`（发票规则），另有 `product` 分类的耳机与人体工学椅知识。每条带 `source`，如“售后政策”“配送规则”。

`rag_search` 工具把这些结果返回给 Agent；`support` 和 `general` Agent 都绑定了该工具，所以政策类问题优先走知识库而不是模型臆测。

### Q76. 如何把演示 RAG 升级到生产 RAG？

**考点：** 演进路线。

**答案：**

1. 文档来源换成企业知识库、商品库、订单库，支持增量更新与删除。
2. 切分策略按语义段落与表格结构优化，保留标题路径。
3. Embedding 换成高质量中文模型，向量库换成支持过滤与持久化的服务。
4. 加入 BM25/关键词召回 + reranker，提升短查询准确率。
5. 结果带引用与置信度，低于阈值时拒绝回答或转人工。
6. 建立评测集，跟踪 Recall@k、MRR、忠实度与幻觉率。
7. 权限过滤前置，确保用户检索不到无权文档。

## 第九章 上下文工程

### Q77. 上下文工程与提示词工程有什么区别？

**考点：** 系统化思维。

**答案：**

提示词工程关注“怎么写一句好 prompt”；上下文工程关注“在有限 token 预算内，把哪些信息以什么优先级、什么顺序、什么压缩策略送进模型”。项目 `ContextEngine` 就是后者：它管理四个动态 section、字符预算、历史滑窗、截断标记和可视化快照。

面试可用一句话总结：模型能力确定后，Agent 效果上限很大程度上由上下文质量决定。

### Q78. 项目的四个上下文 section 是什么？

**考点：** 上下文分层。

**答案：**

1. `角色与硬性规则`（priority=1）：Persona 与不可违反的规则。
2. `用户身份`（priority=2）：当前用户 id、role 与访问边界。
3. `检索增强知识`（priority=3）：RAG 结果。
4. `可用工具清单`（priority=4）：经过 RBAC 过滤的工具名与描述。

优先级数字越小越重要。预算不足时，低优先级区块先被截断或丢弃，保证角色规则和身份约束不丢失。

### Q79. 装箱算法如何工作？

**考点：** 预算控制。

**答案：**

`build()` 先算 `reserve = min(max_chars // 3, max(240, len(user_input)+80))`，用于给用户轮和历史留空间；`system_budget = max(320, max_chars - reserve)`。然后按 priority 排序遍历 section：能完整放下就加入 `chosen`；放不下但剩余空间大于 80 且 priority ≥ 3，则截断并加 `…[已截断]`；否则标记 `included=False`。

空内容 section 也会被记录到快照，便于前端显示“为什么没包含”。这是可解释上下文的关键。

### Q80. `compact()` 如何处理历史消息？

**考点：** 滑窗与压缩。

**答案：**

它只处理非 SystemMessage 的历史，且只看最近 `recent_messages=8` 条。从后往前遍历，在字符预算内保留消息；遇到过长消息时，保留头尾各一半并插入 `…[上下文已压缩]…` 标记，然后停止。最后反转回时间顺序，返回保留消息、丢弃数量、是否压缩。

测试用例验证了两点：8 条历史在预算下可能保留 6 条、丢弃 2 条；单条超长历史在 `max_chars` 较小时会触发 `compressed=True`。

### Q81. ContextSnapshot 有哪些字段？如何用于可视化？

**考点：** 可解释性。

**答案：**

字段包括 `sections`（每块名称、字符数、是否包含、优先级、是否截断）、`max_chars`、`total_chars`、`kept_messages`、`dropped_messages`、`compressed`。前端 ChatView 的“上下文工程”面板展示这些字段，用户能看到哪些知识被送入模型、哪些工具可用、历史被丢了几条。

面试可强调：这是审计与调试 Agent 的重要抓手。模型答错时，可以先看上下文快照判断是“没给到证据”还是“模型理解错了”。

### Q82. 为什么要给用户输入预留 reserve？

**考点：** 边界情况。

**答案：**

如果把 3200 字符全部给系统上下文，用户再发一个长问题或历史消息进来，总长度就会超预算。`reserve` 至少 240 字符，并且随用户输入长度增长，保证用户轮永远有空间。这样上下文控制不会因为“用户突然发长文本”而失效。

面试可补充：真实系统需要基于 tokenizer 精确计数，项目用 `estimate_tokens` 的启发式（约 1.5 中文字/token）只是为了零依赖演示。

## 第十章 流式输出、可观测性与人工审批

### Q83. TraceCollector 如何存储与查询事件？

**考点：** 轻量可观测实现。

**答案：**

`TraceCollector` 用列表 + `threading.Lock`，`record()` 写入 `ts/trace_id/node/event/payload`，最多保留 1000 条；`query(limit, trace_id)` 返回倒序的最新事件。`/api/traces` 暴露查询接口并要求 `trace:read` 权限。

生产替换点是 OpenTelemetry + 后端存储，但业务事件命名可以保留：节点切换、上下文构建、意图路由、工具调用、审批中断等。

### Q84. `current_trace_id` 为什么用 ContextVar？

**考点：** 异步上下文传播。

**答案：**

Supervisor 中多个请求可能并发，如果用全局 trace_id 变量，A 请求的工具调用可能被记到 B 请求的 trace 上。ContextVar 为每个异步任务提供独立值，`make_agent_node()` 设置后在 `finally` 中 reset，保证埋点归属正确。它与 `current_user` 使用同一种模式。

### Q85. SSE 事件有哪些类型？各自用途？

**考点：** 流式协议设计。

**答案：**

六种：`node`（节点进度，如 context/route/shopping/finalize）、`context`（上下文快照）、`route`（路由结果）、`tool`（工具名与结果摘要）、`token`（回答分片，每片 12 字符）、`done`（完整答案）。事件格式统一为 `data: {json}\n\n`，前端按双换行分帧。

这种设计让前端既能展示“正在做什么”，也能展示“依据什么回答”，比只流式吐字更透明。

### Q86. 前端如何解析 SSE？

**考点：** 流式客户端实现。

**答案：**

`src/api/client.ts` 的 `chatStream()` 用 `response.body.getReader()` 读取字节流，`TextDecoder` 增量解码，维护 `buffer`，用 `indexOf("\n\n")` 切分完整帧。每帧提取所有以 `data:` 开头的行，拼接后 `JSON.parse`，回调给 `onEvent`。解析失败时忽略，容忍 keep-alive 或非法帧。

面试可补充：生产要处理断线重连、EventSource 的 GET 限制、 backpressure、超时取消与错误事件。

### Q87. 图可视化是如何生成的？

**考点：** 元数据驱动可视化。

**答案：**

后端 `GRAPH_DESCRIPTIONS` 用 JSON 描述两张图的 `title/nodes/edges`，节点带 `kind`（process/decision/agent/human/end），边带可选 label。`/api/graphs` 返回它。前端 `GraphFlow.vue` 根据最长路径深度计算列 x，按层内序号计算 y，用 SVG 画圆角矩形、箭头和边标签，并按 kind 着色。

优点是图结构与渲染解耦；后端改流程节点，前端无需改组件。面试可强调：没有引入重型图库，避免依赖和包体积。

### Q88. 人工审批在前端如何呈现？

**考点：** HITL 用户体验。

**答案：**

`WorkflowView.vue` 调用 `runFulfillment()`，若返回 `status=awaiting_approval`，展示 `interrupt` 详情（金额、原因、订单号）和“批准/拒绝”按钮，按钮调用 `resumeFulfillment(threadId, approved)`。恢复后展示新的 `steps` 时间线与最终状态。

关键点是把“等待人工决策”作为正常状态而不是错误状态，用户能清楚知道流程停在哪里、为什么停、谁能继续。

## 第十一章 权限、安全与稳定性

### Q89. 项目的 RBAC 模型是什么？

**考点：** 权限矩阵。

**答案：**

四种角色：`guest` 只有 `product:read/chat:use`；`customer` 增加 `order:read/order:create/order:refund`；`service` 增加 `order:manage/audit:read/trace:read`；`admin` 拥有全部 9 种权限，包括 `user:manage`。

权限判定有两层：功能权限用 `has_permission(user, permission)`；数据权限用 `can_access_customer(user, customer_id)`，customer 只能访问自己，service/admin 可跨客户。API 层用 `require()` 依赖工厂，工具层用 `require_permission()` 与 `require_customer_scope()`。

### Q90. HMAC Token 如何签发与校验？

**考点：** 无状态认证。

**答案：**

`issue_token()` 把 `{sub, name, role, exp}` JSON 序列化后做 URL-safe Base64，得到 body；再用 `secret_key` 对 body 做 HMAC-SHA256 并 Base64 得到 signature，最终拼接为 `body.signature`。`decode_token()` 拆开后先用 `hmac.compare_digest` 防时序攻击地校验签名，再检查 `exp` 是否过期、`role` 是否合法。

面试要点：这是教学实现，没有用户态吊销、刷新令牌、密码哈希与 CSRF 防护。生产应换 OAuth2/JWT 服务并校验 issuer/audience。

### Q91. 请求身份如何传递到工具层？

**考点：** ContextVar 实践。

**答案：**

API 依赖 `current_user()` 解析 Token 后调用 `set_current_user(user)` 得到 marker，`yield` 给路由处理函数，结束后 `reset_current_user(marker)`。SSE 生成器内部也重新设置与清理，因为流式响应可能跨任务执行。工具函数用 `get_current_user()` 取当前身份，未设置时返回匿名的 guest。

这避免了把 user 参数一路透传到每个函数和工具调用，同时保持异步安全。

### Q92. 为什么说权限校验是“双层”的？

**考点：** 纵深防御。

**答案：**

第一层在入口：FastAPI `require("order:refund")` 校验角色权限，`require_customer_scope()` 校验数据归属。第二层在工具：`initiate_refund()` 自己再校验 `order:refund` 和订单归属。即使工具被 MCP、脚本或 Agent 直接调用，也不会越权。

此外还有第三层：按角色过滤工具清单 `filter_tools()`，让模型根本看不到无权工具。三层递进，安全性和可观测性都更好。

### Q93. 审计日志记录哪些内容？

**考点：** 合规与追溯。

**答案：**

`AuditLogger.record(actor, action, resource, decision, detail)` 记录时间戳、操作者、动作、资源、决策（allow/deny）和详情。项目在登录成功/失败、API 下单、退款、工作流审批，以及工具层的权限拒绝与成功调用处写审计。`/api/audit` 需要 `audit:read`，管理页展示表格并支持按 decision 过滤。

面试可补充：生产审计应追加写不可篡改存储，记录请求 id、IP、UA，并满足留存期限要求。

### Q94. PII 脱敏与审计如何兼顾？

**考点：** 隐私合规。

**答案：**

PII 中间件在输入进入模型前脱敏，避免敏感数据传输与落库到模型上下文；审计日志只记录用户 id、动作、资源与摘要，不记录完整输入正文。工具结果在 trace 中截断到 400 字符，进一步降低泄露面。

如果要打印更详细的日志，应使用脱敏后的文本，并对日志系统设置访问控制。面试可强调“数据是敏感资产，能不记录就不记录”。

### Q95. 项目在幂等、限流和并发上有哪些现状与改进点？

**考点：** 稳定性体系。

**答案：**

现状：仓储用 `RLock` 保护内存状态；`create_order` 在锁内检查并扣减库存；`ModelCallLimitMiddleware` 限制模型调用次数；`ToolRetryMiddleware` 处理瞬时错误；Token 有过期时间。

改进点：下单/退款引入幂等键避免重试重复执行；API 网关加 QPS 与并发限制；真实模型加超时与熔断；数据库用事务和行锁；工作流审批加乐观锁防止重复审批；关键操作加补偿任务与死信队列。面试时可说“项目展示了正确抽象，生产要补基础设施”。

## 第十二章 测试、前端与面试表达

### Q96. 项目测试如何分层？最终结果如何？

**考点：** 质量保障。

**答案：**

后端 pytest 共 79 例，分 8 个文件：原业务模块 40 例，覆盖 RBAC、上下文、RAG、工具、Agent、工作流、API；新增 `test_langchain_knowledge.py` 39 例，按知识点覆盖 Messages、LCEL、Tools、create_agent、Middleware、LangGraph、HITL、MCP、RAG、上下文工程、稳定性。前端 Vitest 4 例，覆盖 API/SSE 解析与 GraphFlow 组件。

验证结果：后端 `pytest -q` 79 passed，前端 `npm test -- --run` 4 passed，`npm run build`（vue-tsc + Vite）成功。另外实起 uvicorn 验证了 REST 与 SSE，12 帧事件、最终答案包含真实商品 P001 与库存。

### Q97. 按知识点组织测试有什么好处？

**考点：** 测试可读性。

**答案：**

按模块组织回答“哪个文件被测了”，按知识点组织回答“哪个 LangChain 概念被测了”。`test_langchain_knowledge.py` 用类分组，每个用例的中文 docstring 写清“知识点 → 验证点”，例如 `test_chinese_ngram_tokenizer`、`test_pii_redaction`、`test_interrupt_state`、`test_checkpointer_thread_isolation`。

这样面试或答辩时可以直接说“我覆盖了 11 类 LangChain 知识点”，并用 `-k Middleware` 之类命令筛选运行。Excel 用例表又把这些知识点映射到输入与预期输出，形成三级资产：代码用例 → 中文清单 → Excel 用例表。

### Q98. Excel 测试用例工作簿包含哪些内容？

**考点：** 测试交付物设计。

**答案：**

`docs/LangChain_Agent测试用例.xlsx` 有 4 个工作表：`用例总览` 用公式统计总用例 85、自动化 72、手工 13、高优先级 43、知识点 14、自动化率 84.7%；`测试用例明细` 有 14 列，含前置条件、输入、执行步骤、预期输出、实际输出、验证要点、优先级、自动化状态与对应自动化用例；`知识点覆盖矩阵` 映射 14 个知识点与核心 API；`测试账号与数据` 列出账号、商品、订单与知识库分类。

所有输入与预期输出取自项目实测值，公式重算零错误。面试可说明：这体现了“测试用例不是空话，能逐条溯源到代码与断言”。

### Q99. 前端如何实现对话页与工作流可视化？

**考点：** 前后端协同。

**答案：**

前端用 Pinia 管理 token 与用户，Vue Router 定义 `/chat`、`/products`、`/orders`、`/workflow`、`/admin` 五个路由。`ChatView.vue` 维护消息数组，发送时调用 `chatStream()`，根据事件类型更新回答文本、路由徽章、工具 chips、节点进度和上下文面板。商品页“向助手咨询”通过 `/chat?q=...` 预填问题，实现页面间联动。

`GraphFlow.vue` 接收后端 `/api/graphs` 的元数据，自绘 SVG 分层图：按最长路径计算列，按层内顺序计算行，圆角矩形节点按 kind 着色，箭头带 marker 和边标签。这一设计的优势是后端流程变更能自动反映到前端，无需改图组件。

### Q100. 如果面试时被要求介绍这个项目，应该如何组织答案？

**考点：** 项目表达与亮点提炼。

**答案：**

建议按“四句话 + 三个亮点 + 两个边界”的结构。

四句话：这是一个 LangChain 1.5 + LangGraph 的电商智能体；后端 10 个模块、前端 5 个页面；支持导购/订单/售后/通用四类专家和订单履约人工审批；零 Key 可运行且有 79+4 个自动化用例。

三个亮点：第一，MCP 工具单一真源，真实 stdio 协议往返测试；第二，上下文工程可解释，前端能看到每个 section 的装箱结果；第三，权限做三层防御，工具内部二次鉴权并写审计。

两个边界：默认离线模型与内存仓储只适合演示，生产要换真实 LLM、数据库、持久化 checkpointer 与企业 IdP；当前未做浏览器视觉走查和大规模压测。

最后准备几个高频追问：`create_agent` 与 `AgentExecutor` 区别、`interrupt` 恢复原理、RAG 混合排序、PII 中间件顺序、Thread_id 隔离、MCP 与 Function Calling 关系。能结合源码讲清这些，项目可信度会明显提升。
