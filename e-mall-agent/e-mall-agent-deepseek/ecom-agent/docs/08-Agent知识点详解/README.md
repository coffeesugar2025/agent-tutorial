# Agent 知识点详解（Python / Java 双实现对照）

> 本目录是 `Agent知识点大纲.md` 的**落地版**：大纲给"要学什么"，这里给"在真实代码里长什么样"。
>
> 每条知识点统一四段式：
>
> | 段落 | 内容 |
> |---|---|
> | **要点** | 判据、边界、什么时候用/不用 |
> | **Python** | 取自 `backend-python/` 的真实实现（含文件路径） |
> | **Java** | 取自 `backend-java/` 的等价实现 |
> | **坑 / 差异** | 两端不一致之处、易错点、取舍理由 |
>
> 代码块为**节选**（省略了日志、异常包装等样板），标注的文件路径可直接跳转查看完整实现。

---

## 分册索引

| 分册 | 对应大纲 | 内容 |
|---|---|---|
| [01-总纲与模型层](01-总纲与模型层.md) | 第 0、1 章 | 决策边界、多模型接入、路由级联、熔断、结构化输出、成本 |
| [02-单体Agent与编排](02-单体Agent与编排.md) | 第 2、3 章 | Agent Loop、工具设计、终止条件、上下文、记忆、路由、HITL、SSE、MCP/Skill |
| [03-RAG与知识治理](03-RAG与知识治理.md) | 第 4 章 | 解析切片、向量化、稀疏、混合检索、重排、降级、治理、评估、Text2SQL |
| [04-可靠性与安全](04-可靠性与安全.md) | 第 5、6 章 | 重试超时幂等、限流、权限、审计、可观测、可重放、注入防御、PII、MQ |
| [05-评测与模型工程](05-评测与模型工程.md) | 第 7、8、9 章 | 评测分层、pass^k、judge、指标、Prompt 版本、训练侧、工程基建 |

---

## 双端模块对照总表

| 能力 | Python | Java |
|---|---|---|
| HTTP 入口 | `app/main.py`（FastAPI） | `AgentApplication.java`（Spring Boot） |
| Agent 运行时 | `app/agents/runtime.py:AgentRuntime` | `agent/AgentRuntime.java` |
| 终止策略 | `app/agents/termination.py:evaluate` | `agent/TerminationPolicy.java:check` |
| 意图路由 | `app/agents/supervisor.py:route` | `agent/SupervisorAgent.java` |
| 子 Agent 提示词 | `app/agents/prompts.py` | `agent/PromptBuilder.java` |
| 工具注册 | `app/tools/registry.py` | `tool/ToolRegistry.java` |
| 工具执行管线 | `app/tools/base.py:ToolExecutor` | `tool/ToolRegistry.execute` + `AgentRuntime` |
| 模型工厂 | `app/llm/providers.py:build_chat_model` | `llm/OpenAiCompatibleProvider.java` |
| 路由 / 级联 | `app/llm/router.py` | `llm/ModelRouter.java` |
| 熔断 / 降级 | `app/llm/fallback.py:CircuitBreaker` | `llm/CircuitBreaker.java` + `FallbackChain` |
| 成本核算 | `app/llm/cost.py` | `llm/CostCalculator.java` |
| 混合检索 | `app/rag/retriever.py:hybrid_search` | `rag/HybridRetriever.java` |
| 切片 | `app/rag/chunker.py` | `rag/Chunker.java` |
| 稀疏编码 | `app/rag/sparse.py` | `rag/SparseEncoder.java` + `Bm25Lite` |
| 向量存储 | `app/rag/store.py`（pymilvus / 内存） | `rag/MilvusVectorStore.java`（REST）+ `InMemoryVectorStore` |
| 记忆 | `app/memory/{session,longterm,profile}.py` | `memory/{SessionMemory,LongTermMemory,UserProfileService}.java` |
| 审批 | `app/hitl/approval.py` | `hitl/ApprovalService.java` |
| 安全 | `app/security/*.py` | `security/*.java` |
| 可观测 | `app/obs/{trace,metrics,logging}.py` | `obs/{Tracer,MetricsCollector,StructuredLogger}.java` |
| 评测 | `app/eval/runner.py` | `eval/EvalRunner.java` |
| MQ | `app/infra/rabbit.py` + `app/mq/consumers.py` | `mq/*Consumer.java` + `MqSupport` |

---

## 怎么读

1. **想理解设计** → 读每条的「要点」+「坑 / 差异」；
2. **想改代码** → 直接看「Python / Java」代码块与文件路径；
3. **想对照两端** → 看每册末尾的「双端差异汇总」。

> 提醒：Java 端**未经编译验证**（交付环境无 Maven/外网），示例代码结构与语义可信，但个别第三方 API 签名可能需要按实际 SDK 微调。详见根 `README.md` 第 9 节。
