# LangChain 知识点测试用例清单

本清单按 **LangChain 1.5 知识点** 组织，与按业务模块组织的原有测试互补。

- 专项文件：`backend/tests/test_langchain_knowledge.py`（11 个知识点，39 个用例）
- 运行结果：`../.venv/Scripts/python.exe -m pytest tests/test_langchain_knowledge.py -q` → **39 passed**
- 全量回归：`../.venv/Scripts/python.exe -m pytest -q` → **79 passed**（原 40 + 新增 39）
- 所有用例均带中文 docstring，格式为「知识点 → 验证点」，可直接对照源码阅读。

---

## 知识点 1：Messages / BaseChatModel

| 用例 | 验证点 | 关键断言 |
|---|---|---|
| `test_message_roles_and_serialization` | System/Human/AI/Tool 四类消息角色与字段 | 类型顺序、`tool_call_id` |
| `test_base_chat_model_contract` | 离线模型实现 `BaseChatModel` 契约 | `_llm_type`、`invoke()` 返回 `AIMessage` |
| `test_bind_tools_emits_tool_call` | `bind_tools` 后模型产出 `tool_calls` | 工具名 `check_inventory`、参数 `P001` |
| `test_tool_message_renders_into_answer` | 工具结果以 `ToolMessage` 回灌并渲染 | 答案含商品 id 与库存数字 |
| `test_model_stream_interface` | `stream()` 逐块产出消息 | 每块为 `AIMessage`，拼接含正确文案 |

知识点说明：消息是 Agent 的唯一数据载体；工具调用是模型输出 `tool_calls`、执行后以 `ToolMessage(tool_call_id=...)` 回灌的协议。

## 知识点 2：LCEL（Runnable 组合）

| 用例 | 验证点 | 关键断言 |
|---|---|---|
| `test_prompt_model_parser_pipeline` | `Prompt | Model | OutputParser` 管道 | `invoke` 返回字符串且内容正确 |
| `test_runnable_lambda_and_parallel` | `RunnableLambda` / `RunnableParallel` | 并行输出字典 `{"doubled":6,"text":"n=3"}` |
| `test_batch_and_callback_events` | `batch` 批处理与 `BaseCallbackHandler` 回调 | 2 次 `on_llm_start` / `on_llm_end` |

知识点说明：LCEL 用 `|` 组合任意 `Runnable`；`config={"callbacks":[...]}` 为链路注入可观测性。

## 知识点 3：Tools

| 用例 | 验证点 | 关键断言 |
|---|---|---|
| `test_tool_decorator_generates_schema` | `@tool` 从签名生成 schema | `name`、`args`、`invoke` 结果 |
| `test_structured_tool_from_function` | `StructuredTool.from_function` 包装业务函数 | 8 个工具、参数 `query`、描述含中文 |
| `test_tool_ainvoke` | 工具异步调用 | JSON 结果 `available=True, stock=12` |

## 知识点 4：create_agent

| 用例 | 验证点 | 关键断言 |
|---|---|---|
| `test_create_agent_compiles_to_graph` | `create_agent` 编译为状态图 | 节点含 `model`、`tools` |
| `test_agent_runs_tool_and_finalizes` | 模型→工具→最终答案完整回路 | `ToolMessage` 含 `P001` |
| `test_specialists_have_scoped_tools` | 多智能体 specialist 工具隔离 | 4 个角色图均含工具节点 |

## 知识点 5：Middleware

| 用例 | 验证点 | 关键断言 |
|---|---|---|
| `test_builtin_middleware_config` | 摘要/重试/调用上限/PII 参数 | `trigger=("messages",14)`、`max_retries=1`、2 个 PII |
| `test_pii_middleware_redacts_input` | 输入邮箱脱敏 | `[REDACTED_EMAIL]`，原文消失 |
| `test_tool_retry_middleware` | 瞬态失败自动重试 | 工具执行 2 次、最终有 `ToolMessage` |
| `test_model_call_limit_middleware` | 调用上限防止死循环 | 消息数受限、图正常结束 |
| `test_custom_wrap_tool_call_records_trace` | 自定义 `wrap_tool_call` 埋点 | trace 中出现 `agent:tool/search_products` |

## 知识点 6：LangGraph 状态图

| 用例 | 验证点 | 关键断言 |
|---|---|---|
| `test_state_reducer_accumulates` | `Annotated[list, operator.add]` reducer | 两次 invoke 得到 `["x","x"]` |
| `test_thread_isolation` | `InMemorySaver` + `thread_id` 隔离 | 不同线程状态独立 |
| `test_conditional_edges` | `add_conditional_edges` 条件路由 | go-left / go-right 分支结果 |
| `test_astream_updates` | `astream(stream_mode="updates")` | 逐节点增量 `a` → `b` |
| `test_supervisor_graph_routes_to_specialist` | Supervisor 图拓扑与意图分类 | 7 个关键节点齐备、`我的订单→order` |

## 知识点 7：Human-in-the-loop

| 用例 | 验证点 | 关键断言 |
|---|---|---|
| `test_interrupt_then_resume` | `interrupt()` 挂起 + `Command(resume=True)` | 状态 `awaiting_approval`、`next=("risk_review",)`、恢复后 `completed` |
| `test_reject_branch` | 拒绝分支 | 订单状态 `cancelled` |
| `test_command_import_contract` | `Command.resume` 字段 | `Command(resume=True).resume is True` |

## 知识点 8：MCP

| 用例 | 验证点 | 关键断言 |
|---|---|---|
| `test_fastmcp_registers_tools` | FastMCP Server 工具注册 | `list_tools()` 返回 8 个工具 |
| `test_mcp_stdio_roundtrip` | `MultiServerMCPClient` stdio 往返 | ListTools + CallTool 返回 `P001` |
| `test_rbac_filters_exposed_tools` | 工具暴露前按角色过滤 | guest 无 `create_order`/`initiate_refund` |

## 知识点 9：RAG

| 用例 | 验证点 | 关键断言 |
|---|---|---|
| `test_embeddings_interface` | 自定义 `Embeddings` 实现 | 维度 64、L2 归一化、文档/查询一致 |
| `test_chinese_ngram_tokenizer` | 中文 bigram/trigram + 拉丁词 | `退货`/`退货政`/`refund` |
| `test_in_memory_vector_store` | `InMemoryVectorStore` 写入与检索 | 返回 `Document` 且 metadata 正确 |
| `test_hybrid_retrieval_and_category_filter` | 向量召回 + 词面重排 + category 过滤 | 仅返回 payment 域、答案含发票 |

## 知识点 10：上下文工程

| 用例 | 验证点 | 关键断言 |
|---|---|---|
| `test_priority_packing_and_snapshot` | 优先级装箱与可解释快照 | 4 区块按优先级 1-4、总字符数受限 |
| `test_sliding_window_and_compression` | 历史滑窗与超长压缩 | 丢弃旧轮、压缩标记 |

## 知识点 11：稳定性（权限/审计）

| 用例 | 验证点 | 关键断言 |
|---|---|---|
| `test_token_signature_and_expiry` | HMAC Token 签名与过期 | 错误密钥/过期返回 None |
| `test_tool_level_scope_enforcement` | 工具内二次鉴权 | 越权 `permission_denied` + 审计 deny |
| `test_reset_repository_is_deterministic` | 用例间状态隔离 | 重置后 P001 库存恢复 12 |

---

## 运行方式

```bash
cd backend
../.venv/Scripts/python.exe -m pytest tests/test_langchain_knowledge.py -q   # 专项 39 例
../.venv/Scripts/python.exe -m pytest -q                                    # 全量 79 例
```

按单个知识点运行（pytest -k 按类名筛选）：

```bash
../.venv/Scripts/python.exe -m pytest tests/test_langchain_knowledge.py -q -k Middleware
../.venv/Scripts/python.exe -m pytest tests/test_langchain_knowledge.py -q -k LangGraph
../.venv/Scripts/python.exe -m pytest tests/test_langchain_knowledge.py -q -k MCP
```
