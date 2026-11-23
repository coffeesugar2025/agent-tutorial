# LangChain 1.5 知识点测试矩阵

> 配套文件：`backend/tests/test_langchain_knowledge_points.py`（**43 个专项用例，已实跑通过**）。
> 加上原有 6 个工程测试文件共 54 例，后端全量 **97 例通过**。

这份文档把「LangChain 1.5 的各个知识点」逐条映射到可执行的测试用例。每个用例都直接断言框架行为，不靠业务结果间接推断，方便按知识点学习、回归与面试讲解。

---

## 一、知识点总览

| # | 知识点 | 核心 API | 用例数 | 代表用例 |
|---|---|---|---|---|
| KP1 | Agent 创建与循环 | `create_agent` / `CompiledStateGraph` | 3 | `test_kp1_agent_loop_message_sequence_model_tool_model` |
| KP2 | 模型抽象与函数调用 | `BaseChatModel` / `bind_tools` / `_generate` / `_stream` | 4 | `test_kp2_model_generates_typed_tool_calls` |
| KP3 | 工具定义与参数校验 | `@tool` / `BaseTool` / `args_schema` | 2 | `test_kp3_tool_required_args_are_validated` |
| KP4 | MCP 工具接入 | `langchain.mcp.MCPAdapter` / `MCPConfig` | 4 | `test_kp4_builtin_mcp_adapter_discovers_tools` |
| KP5 | 中间件 | `AgentMiddleware` / `wrap_model_call` / `wrap_tool_call` / 内置 5 件 | 6 | `test_kp5_wrap_tool_call_can_rewrite_args_before_execution` |
| KP6 | 结构化输出 | `response_format` / `ToolStrategy` / `ProviderStrategy` / `AutoStrategy` | 5 | `test_kp6_response_format_requires_model_cooperation` |
| KP7 | 会话记忆 | `checkpointer` / `InMemorySaver` / `thread_id` | 4 | `test_kp7_checkpointer_requires_thread_id` |
| KP8 | 流式输出 | `astream_events(v2)` / `AIMessageChunk` / `stream_mode="updates"` | 4 | `test_kp8_astream_events_emits_typed_lifecycle_events` |
| KP9 | 消息与标准内容块 | `content_blocks` / `ToolMessage` / `artifact` | 3 | `test_kp9_content_blocks_are_provider_agnostic` |
| KP10 | 模型初始化 | `init_chat_model("provider:model")` | 2 | `test_kp10_real_mode_delegates_to_init_chat_model` |
| KP11 | LangGraph 运行时 | `aget_state` / `update_state` / `recursion_limit` | 2 | `test_kp11_recursion_limit_is_honoured` |
| KP12 | 1.5 版本特性 | Decisions API / `ModelRouterMiddleware` / `langchain.mcp` | 4 | `test_kp12_router_middleware_requires_explicit_classifier` |

---

## 二、逐知识点用例与断言要点

### KP1 · `create_agent` 与 Agent 循环

| 用例 | 断言要点 |
|---|---|
| `test_kp1_create_agent_returns_compiled_graph` | 返回 `CompiledStateGraph`；具备 `invoke/ainvoke/stream/astream/astream_events/get_state/aget_state/get_graph` 全套 Runnable 接口 |
| `test_kp1_agent_without_tools_stops_immediately` | `tools=[]` 时直接产出终态 `AIMessage`，无 `tool_calls`、无 `ToolMessage` |
| `test_kp1_agent_loop_message_sequence_model_tool_model` | 真实 MCP 工具下消息序列严格为 `AI(tool_calls) → ToolMessage → AI(final)` |

**知识点**：1.x 不再有 `AgentExecutor` / `initialize_agent` / `agent.run()`；`create_agent` 返回的编译图本身就是执行器，循环由「最新 AIMessage 是否含 tool_calls」驱动。

### KP2 · `BaseChatModel` 契约与 Function Calling

| 用例 | 断言要点 |
|---|---|
| `test_kp2_scripted_model_is_a_base_chat_model` | 子类关系；`_generate` / `_stream` / `_llm_type` / `_identifying_params` 齐全 |
| `test_kp2_bind_tools_returns_new_instance` | `bind_tools` 不可变更新，原实例 `bound_tools` 为空 |
| `test_kp2_model_generates_typed_tool_calls` | `tool_calls` 含 `name / args / id / type` 四要素 |
| `test_kp2_model_stream_emits_incremental_chunks` | `_stream` 产出多个 `AIMessageChunk`，拼接后等于完整文本 |

**知识点**：离线脚本化模型仍由 LangChain 正常调用 `bind_tools`，因此「免 API Key 演示」不是跳过 Agent 的假实现。

### KP3 · `@tool` / `BaseTool` / 参数 schema

| 用例 | 断言要点 |
|---|---|
| `test_kp3_tool_decorator_exposes_schema_and_is_callable` | `name` / `description` / `args_schema.model_fields` / `invoke()` |
| `test_kp3_tool_required_args_are_validated` | 缺必填参数由 Pydantic schema 拦截 |

### KP4 · `langchain.mcp.MCPAdapter`

| 用例 | 断言要点 |
|---|---|
| `test_kp4_builtin_mcp_adapter_discovers_tools` | `list_tools()` 动态发现 10 个工具；`describe()` 字段完整 |
| `test_kp4_mcpconfig_uses_standard_mcpservers_shape` | 标准 `MCPConfig`：`mcpServers → {server}`；stdio 用 `command/args/env`，http 用 `url`；**无需 `transport` 键**（自动推断） |
| `test_kp4_mcp_tools_are_read_only` | 调用算价 / 查单 / 售后判定前后订单数据快照不变 |
| `test_kp4_mcp_failure_degrades_to_local_tools` | MCP 连接异常时自动降级为 4 个本地 `@tool` |

**知识点**：1.4 起 MCP 内置于 `langchain.mcp`（基于 FastMCP），仍是 beta；旧 `MultiServerMCPClient` 通过 `MCP_CLIENT=adapters` 兼容。Adapter 是异步上下文管理器，必须活到工具调用结束，故由 FastAPI `lifespan` 持有。

### KP5 · `AgentMiddleware`（1.x 一等扩展点）

| 用例 | 断言要点 |
|---|---|
| `test_kp5_custom_middleware_implements_paired_sync_async_hooks` | 同步/异步钩子成对实现，保证 `invoke` 与 `ainvoke` 行为一致 |
| `test_kp5_tool_call_request_override_is_immutable` | `request.override(tool_call=...)` 返回新请求，原请求不被修改 |
| `test_kp5_wrap_tool_call_can_rewrite_args_before_execution` | 自定义中间件在 `handler` 前改写入参，`ToolMessage` 收到改写结果 |
| `test_kp5_builtin_middleware_catalog_and_composition` | `default_middleware()` 5 层顺序；内置件签名含 `run_limit` / `max_retries` / `exit_behavior` |
| `test_kp5_prompt_guard_short_circuits_before_model_call` | 注入提问直接返回 `ModelResponse` 短路，零工具调用 |
| `test_kp5_tool_audit_records_and_redacts_pii` | 审计字段齐全、强制注入 `user_id`、脱敏生效 |

**知识点**：组合顺序「列表越靠前越外层」；钩子菜单为 `before_agent / before_model / wrap_model_call / wrap_tool_call / after_model / after_agent`。

### KP6 · `response_format` 结构化输出

| 用例 | 断言要点 |
|---|---|
| `test_kp6_tool_strategy_binds_pydantic_schema` | `ToolStrategy.schema is PurchaseIntent`，`handle_errors` 默认开启 |
| `test_kp6_three_structured_output_strategies_are_available` | 三种策略导出；`AgentState` 含 `structured_response` 键 |
| `test_kp6_response_format_requires_model_cooperation` | 装配可行但**刻意不 `ainvoke`**，避免脚本模型触发重试循环 |
| `test_kp6_pydantic_schema_validates_intent_contract` | 非法 `intent` / 越界 `confidence` 抛 `ValidationError` |
| `test_kp6_rule_based_intent_matches_structured_contract` | mock 模式规则兜底返回同契约的 `PurchaseIntent` |

**知识点**：传 schema 类时自动选策略；模型支持原生结构化输出走 `ProviderStrategy`，否则回退 `ToolStrategy`（把 schema 注册成工具）。结果经校验后写入 `result["structured_response"]`。

### KP7 · `checkpointer` / 多轮记忆

| 用例 | 断言要点 |
|---|---|
| `test_kp7_checkpointer_accumulates_messages_per_thread` | 同 `thread_id` 连续两轮，`aget_state` 消息数递增；checkpointer 为 `InMemorySaver` |
| `test_kp7_thread_ids_are_isolated` | 不同 `thread_id` 各自独立 |
| `test_kp7_runtime_config_carries_thread_and_recursion_limit` | 运行时 config 含 `configurable / metadata / recursion_limit` |
| `test_kp7_checkpointer_requires_thread_id` | **不带 `thread_id` 时 LangGraph 抛 `ValueError`** |

**知识点**：1.x 没有独立 `Memory` 对象，跨调用持久化由 LangGraph checkpointer 承担；生产替换为 Postgres/Redis 实现即可，接口不变。

### KP8 · 流式输出

| 用例 | 断言要点 |
|---|---|
| `test_kp8_astream_events_emits_typed_lifecycle_events` | 事件名含 `on_chat_model_stream` / `on_chain_end`；`data.chunk` 为 `AIMessageChunk` |
| `test_kp8_core_17_tool_call_delta_contract` | `AIMessageChunk.tool_call_chunks` 存在，core ≥ 1.7 |
| `test_kp8_runtime_maps_stream_to_sse_events` | 运行层输出 `meta / token* / done`，`done.tool_calls` 统计正确 |
| `test_kp8_langgraph_astream_updates_mode` | `stream_mode="updates"` 产出逐节点 dict 更新 |

**知识点**：core 1.7 起工具参数按 `tool-call-delta` 增量推送（旧版重复全量参数），客户端需同步升级到 `@langchain/react ≥1.2.6` / `langchain-core ≥1.6.13`。

### KP9 · 标准内容块与消息类型

| 用例 | 断言要点 |
|---|---|
| `test_kp9_content_blocks_are_provider_agnostic` | `message.content_blocks` 为 `[{"type":"text","text":...}]` |
| `test_kp9_text_helper_handles_str_and_content_blocks` | 兼容 `str` 与 `list[dict]` 两种 `content` 形态 |
| `test_kp9_tool_message_contract` | `ToolMessage` 的 `type/name/tool_call_id/artifact/status` 字段 |

### KP10 · `init_chat_model`

| 用例 | 断言要点 |
|---|---|
| `test_kp10_model_string_identifier_contract` | `provider:model` 格式；mock 模式返回 `ScriptedChatModel` |
| `test_kp10_real_mode_delegates_to_init_chat_model` | 用 spy 验证 real 模式委托 `init_chat_model`，并透传 `api_key` / `base_url` / `temperature`（**无需真实 Key**） |

### KP11 · LangGraph 运行时契约

| 用例 | 断言要点 |
|---|---|
| `test_kp11_compiled_graph_exposes_state_and_graph_api` | `get_state` / `update_state` / `get_state_history` 可调用，`get_graph().nodes` 非空 |
| `test_kp11_recursion_limit_is_honoured` | `config.recursion_limit` 生效 |

### KP12 · LangChain 1.5 版本特性

| 用例 | 断言要点 |
|---|---|
| `test_kp12_version_baseline_python311_core18` | `langchain 1.5.x` / `core ≥1.8` / Python ≥3.11 |
| `test_kp12_decisions_api_is_available` | `langchain_core.decisions.BaseDecisionModel` 存在 |
| `test_kp12_router_middleware_requires_explicit_classifier` | 1.5 的 `ModelRouterMiddleware` / `AutoModeMiddleware` 必须显式 `classifier=`；1.4.6+ 的 HITL 支持 `interrupt_mode`；1.5 的 `SummarizationMiddleware` 支持 `summarizer=` |
| `test_kp12_mcp_lives_in_langchain_namespace` | `langchain.mcp.MCPAdapter` 具备 `list_tools` 与 `__aenter__` |

---

## 三、怎么跑

```bash
cd backend

# 只跑知识点专项（43 例）
python3 -m pytest tests/test_langchain_knowledge_points.py -v

# 按知识点筛（-k 匹配函数名前缀）
python3 -m pytest tests/test_langchain_knowledge_points.py -k kp4 -v      # 只看 MCP
python3 -m pytest tests/test_langchain_knowledge_points.py -k "kp5 or kp6" -v
python3 -m pytest tests/test_langchain_knowledge_points.py -k "checkpointer or thread" -v

# 全量（97 例）
python3 -m pytest -q
```

> 用例默认走 `AGENT_MODE=mock`，不需要任何 API Key；`kp1` / `kp4` / `kp5` 中的几个用例会真实拉起 MCP stdio 子进程。

---

## 四、四个实测踩到的坑（已固化成用例）

这些不是文档抄来的注意事项，是本次实现中真实触发、并被写成回归用例的边界：

1. **挂了 checkpointer 必须传 `thread_id`**
   直接 `agent.ainvoke({"messages": ...})` 会抛
   `ValueError: Checkpointer requires one or more of the following 'configurable' keys: thread_id, ...`。
   → `test_kp7_checkpointer_requires_thread_id`；运行层 `runtime._config_for()` 统一注入。

2. **`response_format` 需要模型配合，否则会无限重试**
   用不产出结构化输出的脚本模型 + `ToolStrategy` 执行 `ainvoke`，会触发
   `GraphRecursionError: Recursion limit ... reached without hitting a stop condition`。
   → 工程上 mock 模式用 `rule_based_intent` 兜底，只有 `real` 模式才挂载 intent agent；
   `test_kp6_response_format_requires_model_cooperation` 只验装配、不执行。

3. **MCP stdio 子进程会丢虚拟环境依赖**
   MCPAdapter 拉起的子进程环境变量被裁剪，user site-packages 不在 `sys.path` 里，
   表现为 `ModuleNotFoundError: No module named 'fastmcp'` → 连接关闭。
   → `config._stdio_env()` 显式注入 `PYTHONPATH`（含 `site.getusersitepackages()`），
   并用 `sys.executable` 作为 `command`；`test_kp4_mcpconfig_uses_standard_mcpservers_shape` 断言 `env` 存在。

4. **core 1.7 的 `tool-call-delta` 是破坏性变更**
   服务端升级到 core ≥1.7 后，事件流中工具参数改为增量分片，旧客户端会把参数拼错。
   → `test_kp8_core_17_tool_call_delta_contract` 锁定版本与字段；架构文档第九节列出客户端升级要求。

---

## 五、与原有 6 个工程测试文件的关系

| 原有文件 | 侧重 | 与专项用例的关系 |
|---|---|---|
| `test_catalog.py` | 纯业务规则 | 与框架无关，保证「工具返回的事实」正确 |
| `test_mcp_server.py` | MCP Server 契约 | 与 `kp4` 互补：一个测服务端注册，一个测客户端发现 |
| `test_middleware.py` | 中间件工具函数 | 与 `kp5` 互补：一个测函数级脱敏/Schema，一个测钩子在 Agent 循环里的真实行为 |
| `test_api.py` | HTTP / SSE 端到端 | 与 `kp8` 互补：一个测接口协议，一个测框架事件流 |
| `test_streaming.py` | 运行层翻译 | 与 `kp9` 互补：卡片提取 vs 消息内容块 |
| `test_agent_e2e.py` | 全链路业务场景 | 与 `kp1~kp12` 互补：业务验收 vs 知识点断言 |

> 一句话分工：**原有 54 例回答「这个功能对不对」，新增 43 例回答「LangChain 这个知识点是不是这样工作的」。**

---

## 六、Excel 版测试用例集（输入 / 输出）

`docs/LangChain1.5_电商智能体_测试用例.xlsx` 把上面的知识点用例整理成
可直接执行、评审、交付的表格，**每行都有明确的「输入 → 预期输出 → 实测输出」**。
生成脚本：`scripts/build_testcase_xlsx.py`（改数据后重跑即可）。

| 工作表 | 行数 | 对应本文件 | 关键列 |
|---|---|---|---|
| 使用说明 | — | 版本基线 / 执行命令 | 统计公式、字段字典、边界说明 |
| 知识点用例 | 43 | 第二节 12 个知识点 | H 输入（函数/配置/消息）→ I 预期输出 → J 实测输出 → L 执行命令 |
| Agent场景用例 | 20 | `test_agent_e2e.py` / `test_api.py` | 自然语言输入 → 回答 / 工具 / 卡片 / SSE 事件序列 |
| 工具边界用例 | 14 | `test_catalog.py` | 工具入参 → 返回 dict（门槛 / 封顶 / 超卖 / 越权 / 缺货） |
| API接口用例 | 12 | `test_api.py` | 请求体 → 状态码 + 响应体 / 事件序列 |
| 知识点覆盖矩阵 | 12 | 第一节总览 | `COUNTIF` 统计每个知识点的双层覆盖 |

**覆盖结果**：12/12 知识点在「知识点专项用例」与「场景/工具/接口用例」两个维度
均有对应用例；合计 89 行，状态列全部「通过」，通过率 100%。
统计与判定共 59 个 Excel 公式（`COUNTA` / `COUNTIF` / `SUM` / `IF` / `IFERROR`），
已写入缓存值，Excel / WPS 打开即显示，修改 K 列状态后自动刷新。

用例 ID 前缀：`KP-` 知识点专项、`SC-` Agent 场景、`TC-` 工具边界、`API-` 接口；
B 列为主知识点（kp1~kp12），关联知识点写在 M 备注列。
