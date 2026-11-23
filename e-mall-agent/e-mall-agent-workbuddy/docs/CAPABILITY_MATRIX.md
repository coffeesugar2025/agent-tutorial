# Agent / RAG / LLM 能力覆盖矩阵

本文档逐项对照岗位能力图谱，标注本项目现状、本次补齐内容与验证方式。

## 状态图例

| 标记 | 含义 |
|---|---|
| ✅ 已实现 | 项目原有代码已覆盖，有自动化用例 |
| 🆕 本次新增 | 本轮补齐的实现，含新模块与测试用例（均已落地并通过测试） |
| 🔌 接口预留 | 提供可替换的抽象与默认内存/SQLite 实现，接真实服务时替换适配器 |
| 📋 方案说明 | 属于训练/推理部署或基础设施范畴，不在应用层代码内实现，给出替换路径 |

验证结果：后端全量 **422 passed + 9 skipped**（第一轮补齐后 248，本轮新增 144，双后端/基础设施再增 30），Java 后端 **32 passed**，前端 **13 passed**、`npm run build` 成功，双后端一致性 **9 passed**。新增能力的 HTTP 调用示例见 `docs/CAPABILITY_QUICKSTART.md`，界面入口为前端"能力实验室"页。本轮新补齐的 33 项能力见第七章；`docs/AGENT_KNOWLEDGE_MAP.md` v3.0 已为每一项补齐原理要点与 Python/Java 真实源码对照（2331 行，含 67 个内部锚点与 35 个可定位源码路径）。

---

## 一、Agent 核心能力

| 能力项 | 状态 | 项目实现位置 | 关键类 / API | 验证 |
|---|---|---|---|---|
| Agent Loop | ✅ | `app/agents/supervisor.py`, `app/agents/specialists.py` | `build_supervisor`, `create_agent`, `StateGraph` | `test_agents.py` |
| Planning / ReAct / Plan-and-Solve | 🆕 | `app/planning/` | `PlanAndSolvePlanner`, `ReActLoop`, `PlanAndSolveExecutor`, `create_planning_graph` | `test_planning.py` |
| Tool / Function Calling | ✅ | `app/agents/tools.py`, `app/mcp/tools.py` | `@tool`, `bind_tools`, `ToolNode` | `test_tools.py`, `test_langchain_knowledge.py` |
| MCP / Skill / Plugin | ✅ + 🔌 | `app/mcp/server.py`, `app/mcp/tools.py` | `FastMCP`, `MultiServerMCPClient`, `ALL_TOOL_FUNCTIONS` | `test_tools.py`（真实 stdio 往返） |
| Workflow / State Machine | ✅ | `app/workflows/fulfillment.py` | `StateGraph`, 条件边, `Annotated` reducer | `test_workflow.py` |
| Multi-Agent 协作 | ✅ | `app/agents/supervisor.py`, `specialists.py` | Supervisor + 4 specialist，`classify_route` | `test_agents.py` |
| Human-in-the-loop | ✅ | `app/workflows/fulfillment.py` | `interrupt()`, `Command(resume=...)` | `test_workflow.py` |
| Memory（会话/用户/长期） | 🆕 | `app/memory/` | `WorkingMemory`, `EpisodicMemory`, `UserMemory`, `MemoryManager` | `test_memory.py` |
| Context Engineering / 压缩 / Token 预算 | ✅ | `app/context/engine.py` | `ContextEngine.build`, 优先级装箱, 滑窗压缩, snapshot | `test_context.py` |
| 错误恢复/重试/幂等/超时/降级/终止 | 🆕 | `app/reliability/`, `app/resume/` | `RetryPolicy`, `TimeoutPolicy`, `FallbackChain`, `IdempotencyGuard`, `StopConditions`, `ResumableRunner` | `test_reliability.py`, `test_sandbox_resume.py` |
| Sandbox / Harness / Code Mode / 长任务恢复 | 🆕 | `app/sandbox/`, `app/resume/` | `CodeSandbox`, `CodeModeRunner`, `Harness`, `CheckpointStore` | `test_sandbox_resume.py` |
| Trace / 日志 / Metrics / 可观测 / 评测 | ✅ + 🆕 | `app/observability/`, `app/eval/` | `get_tracer`, `MetricRegistry`, `MetricsCollector`, `Evaluator`, `ReplayRunner`, `RegressionGate` | `test_eval.py` |

### 补充说明

- **Skill / Plugin**：本项目以 `mcp/tools.py` 作为工具单一真源，FastMCP Server 对外暴露插件化能力；Skill 按 LangChain 中间件 + 提示词模板方式组织。
- **Memory 接入方式**：原有 `ConversationStore` 保留以维持回归基线，新 `MemoryManager` 通过门面接口接入，集成层可平滑替换。
- **可观测性**：原有 `tracer.py` 记录节点/工具事件；本轮新增 Metrics（Counter/Gauge/Histogram + P95/P99）与评测体系（Golden Case / Replay / 回归门禁）。

---

## 二、RAG 与知识工程

### 基础层

| 能力项 | 状态 | 实现位置 | 关键 API | 验证 |
|---|---|---|---|---|
| 文档解析 | 🆕 | `app/rag/ingest.py` | 文本/Markdown/JSON 解析器 | `test_rag_advanced.py` |
| 切片（Chunking） | 🆕 | `app/rag/ingest.py` | `Chunker`（固定+overlap / 章节 / 语义段落） | 同上 |
| Embedding / 向量化 | ✅ | `app/rag/embeddings.py` | `HashEmbeddings`（中文 n-gram） | `test_rag.py` |
| 召回 | ✅ | `app/rag/pipeline.py` | `InMemoryVectorStore.similarity_search` | 同上 |
| Rerank | 🆕 | `app/rag/hybrid.py` | `Reranker`（词面+位置+元数据加权） | `test_rag_advanced.py` |
| Prompt 拼接 | ✅ | `app/context/engine.py` | `ContextEngine.format_rag` | `test_context.py` |

### 进阶层

| 能力项 | 状态 | 实现位置 | 关键 API |
|---|---|---|---|
| 混合检索（全文 + 向量） | 🆕 | `app/rag/hybrid.py` | `BM25Index`, `HybridRetriever` |
| RRF 融合排序 | 🆕 | `app/rag/hybrid.py` | `HybridRetriever` 权重/RRF 配置 |
| 图谱检索融合 | 🆕 | `app/rag/graphrag.py` | `GraphRAGRetriever` |
| 知识更新 / 版本管理 | 🆕 | `app/rag/governance.py` | `VersionedStore` |
| 增量索引 | 🆕 | `app/rag/governance.py` | `VersionedStore.upsert` |
| 撤销 / 回滚 | 🆕 | `app/rag/governance.py` | `revoke`, `rollback` |
| 引用质量评估 | 🆕 | `app/rag/citation.py` | `CitationValidator`, `GroundednessScorer` |

### 高阶层

| 能力项 | 状态 | 实现位置 | 关键 API |
|---|---|---|---|
| Text2SQL | 🆕 | `app/rag/text2sql.py` | `Text2SQL`（SQLite 安全 SELECT） |
| Text2Cypher | 🆕 | `app/rag/text2sql.py` | `Text2Cypher`（Cypher 模板 + 参数） |
| GraphRAG / 知识图谱 | 🆕 | `app/rag/graphrag.py` | `KnowledgeGraph`, `GraphRAGRetriever` |
| Neo4j | 🔌 | 接口预留 | `Text2Cypher` 输出可直接交 Neo4j driver 执行 |
| Ontology / 领域知识治理 | 🔌 + 🆕 | `app/rag/governance.py`, `graphrag.py` | 租户/分类隔离 + 版本治理；本体层可接 RDF/OWL 工具 |
| 幻觉控制 | 🆕 | `app/rag/citation.py` | `GroundednessScorer`, `CitationValidator` |

### 常见工具

| 工具 | 状态 | 说明 |
|---|---|---|
| FAISS / Chroma | 🔌 | `InMemoryVectorStore` 接口兼容 LangChain `VectorStore`，可直接替换 |
| Milvus / Qdrant / Pinecone | 🔌 | 同上，`HashEmbeddings` 可替换为真实 Embedding 服务 |
| Elasticsearch | 🔌 | `BM25Index` 提供同语义的本地实现，可替换为 ES |
| LlamaIndex | 📋 | 与 LangChain 定位重叠；本项目统一用 LangChain/LangGraph，数据接入层可并存 |

---

## 三、LLM 与模型工程

### 模型 / API

| 模型 | 状态 | 说明 |
|---|---|---|
| OpenAI | ✅ | `get_model()` 中 `ECOM_LLM_PROVIDER=openai` |
| Claude / Gemini / DeepSeek / Qwen / Llama / GLM / 文心 / 通义 | 🔌 | 均提供 OpenAI 兼容端点，通过 `ChatOpenAI(base_url=...)` 或对应 `langchain-*` 包接入；`BaseChatModel` 契约不变 |

### 应用能力

| 能力项 | 状态 | 实现位置 | 说明 |
|---|---|---|---|
| Prompt Engineering | ✅ | `app/context/engine.py`, `app/agents/specialists.py` | 角色/工具/知识/历史分层装配 |
| 结构化输出 / JSON Mode | ✅ + 🆕 | `app/llm/factory.py`, `app/planning/` | `response_format`, `PydanticOutputParser` |
| 参数调优 | ✅ | `app/llm/factory.py` | temperature / model / streaming |
| 模型路由 | ✅ + 🆕 | `app/agents/specialists.py`, `app/reliability/` | `ModelFallbackMiddleware`, `FallbackChain` |
| 成本 / 延迟优化 | 🆕 | `app/observability/metrics.py` | Token 总量、P50/P95/P99、成功率 |
| 结果校验 | 🆕 | `app/rag/citation.py`, `app/reliability/` | Groundedness、引用校验、降级值 |

### 模型工程（训练 / 推理部署）

| 能力项 | 状态 | 说明 |
|---|---|---|
| SFT / LoRA / QLoRA / DPO / RLHF | 📋 | 属于离线训练管线，不在 Agent 应用代码内。产出模型后通过 `BaseChatModel` 接入即可 |
| 量化 / 剪枝 / 蒸馏 | 📋 | 模型压缩，部署阶段处理 |
| vLLM / Ollama / SGLang / Xinference | 🔌 | 推理服务，提供 OpenAI 兼容 API；改 `base_url` 即可切换 |

### 评测指标

| 指标 | 状态 | 实现位置 |
|---|---|---|
| 任务成功率 | 🆕 | `app/eval/` `EvalReport.pass_rate` |
| 工具调用准确率 | 🆕 | `app/eval/` `tool_called` scorer |
| 幻觉率 | 🆕 | `app/rag/citation.py` Groundedness |
| Token 成本 | 🆕 | `app/observability/metrics.py` token 计数 |
| 推理耗时 / P95 / P99 | 🆕 | `app/observability/metrics.py` Histogram |
| 回答准确性 | 🆕 | `app/eval/` exact/contains/json_path scorer |
| 端到端完成质量 | 🆕 | `app/eval/` 自定义 scorer + 回归门禁 |

---

## 四、四类工程能力对照

| 工程能力 | 覆盖情况 | 主要落点 |
|---|---|---|
| Agent 工程化（Loop/Workflow/Tool/Memory/Context/恢复） | 全覆盖 | `planning/`, `reliability/`, `resume/`, `memory/`, `context/` |
| RAG 与知识治理（切片/召回/重排/版本/更新/引用/幻觉） | 全覆盖 | `rag/` 六个新模块 |
| 生产级可靠性（异常/超时/重试/幂等/降级/权限/审计/隔离/Trace/监控/成本） | 应用层全覆盖 | `reliability/`, `security/`, `observability/metrics.py`；数据库/IdP 替换见 `PRODUCTION_READINESS.md` |
| 评测与迭代（Golden Case/回归/Bad Case/Replay） | 全覆盖 | `app/eval/` |

---

## 五、本次新增模块索引

```
backend/app/
├── planning/        # Planning / ReAct / Plan-and-Solve
├── reliability/     # 重试 / 超时 / 降级 / 幂等 / 终止条件
├── memory/          # 会话 / 情景 / 用户长期记忆
├── rag/
│   ├── ingest.py        # 解析与切片
│   ├── hybrid.py        # BM25 + 向量 + RRF + Rerank
│   ├── governance.py    # 版本 / 增量 / 撤销 / 隔离
│   ├── citation.py      # 引用质量 / 幻觉控制
│   ├── text2sql.py      # Text2SQL / Text2Cypher
│   └── graphrag.py      # 知识图谱 / 图检索
├── sandbox/         # AST 校验 / 受限执行 / Code Mode / Harness
├── resume/          # Checkpoint / 长任务恢复
├── eval/            # Golden Case / Evaluator / Replay / 回归门禁
└── observability/
    └── metrics.py   # Counter / Gauge / Histogram / 回调埋点
```

新增测试：`test_planning.py`、`test_reliability.py`、`test_memory.py`、`test_rag_advanced.py`、`test_sandbox_resume.py`、`test_eval.py`。

---

## 六、不在应用层实现的部分及替换路径

以下能力属于训练或基础设施，本项目以**可替换接口 + 默认本地实现**方式覆盖，不把训练脚本/外部服务塞进应用代码：

1. **模型训练（SFT/LoRA/DPO/RLHF）**：在独立训练管线完成，产出 HF 模型 → vLLM/Ollama 部署 → OpenAI 兼容端点 → 修改 `ECOM_LLM_PROVIDER` 与 `base_url`。
2. **专业向量库（Milvus/Qdrant/Pinecone）**：实现 LangChain `VectorStore` 接口后替换 `InMemoryVectorStore`；Embedding 同理。
3. **Neo4j / Ontology**：`Text2Cypher` 已产出可执行 Cypher；接 Neo4j driver 后把 `KnowledgeGraph` 换为真实图库即可。
4. **生产数据库 / IdP / 分布式缓存 / mTLS**：详见 `docs/PRODUCTION_READINESS.md` 的 P0 改造清单（18 项）。

---

## 七、本轮补齐的 33 项能力（v2.0）

对照 `docs/AGENT_KNOWLEDGE_MAP.md` 的缺口审计，本轮新增以下模块，均通过 REST 端点暴露并完成自动化测试。

### 7.1 P0 安全与对齐

| 能力 | 模块 | 关键 API |
| --- | --- | --- |
| Prompt 注入防御（直接/间接） | `app/security/injection.py` | `InjectionScanner.scan`、`isolate_untrusted`、`least_privilege_system_prompt` |
| 越狱检测 / 输出审核 | `app/security/moderation.py` | `JailbreakDetector.detect`、`OutputModerator.check`、`guard_tool_call` |
| MCP 工具投毒 / 变更审计 | `app/security/tool_guard.py` | `ToolGuard.validate_manifest/enforce_tools/diff`、`sign_manifest` |
| 红队测试 | `tests/test_redteam.py` | 注入/越狱/投毒/越权/提示泄露攻击用例（37 例） |

### 7.2 Agent 工程与 LLM 工程

| 能力 | 模块 | 关键 API |
| --- | --- | --- |
| 反思自纠错 | `app/reflection/` | `ReflexionLoop.run`、`SelfConsistency`、`majority_vote` |
| 5 类编排模式 | `app/orchestration/` | `build_pattern`（Prompt Chaining/Routing/Parallelization/Orchestrator-Workers/Evaluator-Optimizer） |
| A2A 通信骨架 | `app/a2a/` | `AgentCard`、`AgentCardRegistry`、`LocalTaskDelegator`、任务状态机 |
| Tool RAG | `app/agents/tool_retriever.py` | `ToolRetriever.search`、`filtered_search`（叠加 RBAC） |
| 推理模型 / Test-time Compute | `app/llm/reasoning.py` | `ReasoningConfig`、`build_reasoning_model_kwargs` |
| 精确 Token 预算 | `app/llm/tokenizer.py` | `EnhancedTokenCounter.count/budget_split`（可选 tiktoken） |
| 结构化输出强约束 | `app/llm/structured.py` | `extract_json`、`validate_structured`、`constrained_model_kwargs` |
| 模型选型 Benchmark | `app/llm/benchmark.py` | `ModelProfile`、`select_model`（质量/成本/延迟三维） |
| Prompt 版本管理 | `app/prompts/` | `PromptRegistry.register/render/set_active`、`init_from_personas` |

### 7.3 RAG 与可靠性

| 能力 | 模块 | 关键 API |
| --- | --- | --- |
| 查询改写 | `app/rag/query.py` | `MultiQueryGenerator`、`HyDEGenerator`、`StepBackRewriter`、`QueryDecomposer` |
| RAGAS 四指标 | `app/rag/ragas_metrics.py` | `evaluate_rag`（Faithfulness/Relevancy/Precision/Recall） |
| 高级 RAG 范式 | `app/rag/advanced.py` | `CorrectiveRAG`、`SelfRAG`、`AgenticRAG` |
| 权限感知检索 | `app/rag/acl.py` | `ACLPolicy`、`ACLFilteredRetriever`、`row_level_filter` |
| 语义缓存 | `app/rag/semantic_cache.py` | `SemanticCache.get/put`（相似度 + TTL + 容量淘汰） |
| 知识抽取 | `app/rag/extraction.py` | `EntityExtractor`、`RelationExtractor`、`EventExtractor` |
| 限流/熔断/背压 | `app/reliability/{ratelimit,circuitbreaker,backpressure}.py` | `TokenBucket`、`CircuitBreaker`、`BoundedQueue` |
| 灰度 / A-B 开关 | `app/reliability/flags.py` | `FeatureFlag`、`FlagRegistry`（哈希分桶 + 白名单） |
| 密钥环轮换 | `app/reliability/secrets.py` | `SecretRing.sign/verify/rotate`（kid 无感轮换） |
| 数据保留策略 | `app/reliability/retention.py` | `RetentionPolicy`、`RetentionManager.purge_expired/delete_user_data` |
| SLO 告警 / 探活 | `app/observability/alerting.py` | `AlertManager.evaluate`、`HealthProbe`、`SLO` |
| 环境配置隔离 | `app/config_profiles.py` | `Environment`、`ProfileConfig.validate_or_raise` |

### 7.4 评测体系

| 能力 | 模块 | 关键 API |
| --- | --- | --- |
| LLM-as-Judge | `app/eval/judge.py` | `LLMJudgeScorer`、`judge_consistency`（Pearson + 一致率） |
| 轨迹评测 | `app/eval/trajectory.py` | `TrajectoryScorer`（LCS 序列相似度）、`with_trajectory` |
| 错误归因 / 反馈闭环 | `app/eval/attribution.py` | `classify_error`（6 类）、`FeedbackLoop`（标注→入集→门禁） |
| 在线实验 / 显著性 | `app/eval/experiment.py` | `Experiment.assign`、`significance_test`（Welch t 检验） |

### 7.5 API 暴露与验证

- 新路由 `app/api/frontier.py`：`/api/frontier/*` 共 25 个端点，全部带 `require(...)` 权限校验，挂载于 `app/main.py`。
- 请求模型：`app/api/schemas.py` 新增 24 个 Pydantic 模型。
- 冒烟测试 `tests/test_frontier_api.py`：34 例，覆盖全部端点的调用、参数校验与权限拦截。
- 顺带修复：`capabilities.py` 缺失 `EvalReport` 导入的 NameError；Harness deadline 测试的 Windows 时钟 flaky（注入可控时钟）。

---

## 8. 双后端与生产基础设施（v3.0 新增）

### 8.1 共用前端 / 双后端

| 能力 | 落地位置 | 说明 |
| --- | --- | --- |
| 共用 Vue3 前端 | `frontend/src/api/client.ts` | 运行时 config.js > Vite env > localStorage > 默认 `:8000` 的 baseURL 解析链 |
| 引擎切换 UI | `frontend/src/views/AdminView.vue`、`App.vue` | 系统管理页切换 Python/Java，顶部 chip 常驻显示，切换清 token |
| Python 后端 | `backend/app/` | 默认实现，能力最完整（392+ 应用层用例） |
| Java 后端 | `java-backend/` | Spring Boot 3 + JDK17 + LangChain4j 1.24.0，独立实现统一 `/api` 契约 |
| 双后端一致性测试 | `backend/tests/test_cross_backend.py` | 9 例，两后端不在线时自动 skip |
| 统一契约 | `docs/API.md`、`docs/TECHNICAL_ARCHITECTURE.md` | 登录/健康/商品/订单/对话/SSE 响应结构对齐 |

### 8.2 生产基础设施适配器（Python）

| 能力 | 模块 | 回退行为 |
| --- | --- | --- |
| MySQL 仓储 | `app/infra/mysql_repo.py` | 未配置 URL → `not_configured`，接口仍可调用 |
| Redis 缓存 | `app/infra/redis_cache.py` | 进程内 dict + TTL |
| RabbitMQ 事件 | `app/infra/rabbitmq.py` | 内存队列（可 drain 断言） |
| Milvus 向量库 | `app/infra/milvus_store.py` | `InMemoryVectorStore + HashEmbeddings` |
| 多模型网关 | `app/infra/llm_gateway.py` | DeepSeek/千问无 Key 或缺 SDK → `RuleBasedChatModel` |
| 健康聚合 | `app/infra/health.py` + `app/api/infra.py` | `/api/infra/health` 如实标注 configured/active/backend/detail |

新增 5 个 `/api/infra/*` 端点，30 个本地确定性测试；全量后端 **422 passed + 9 skipped**。

### 8.3 部署

- `docker-compose.yml`：frontend(nginx) + backend-python + backend-java + mysql + redis + rabbitmq + milvus + etcd + minio。
- `backend/Dockerfile`、`frontend/Dockerfile`、`java-backend/Dockerfile`；nginx 用 `UPSTREAM_BACKEND` envsubst 切上游。
- `docker/mysql/init/*.sql` 种子数据；`scripts/{deploy,stop,logs,smoke,reset-data}.sh` 运维脚本。
- 校验：`docker-compose --env-file .env.example config` 通过（本机 Docker 守护进程未启动，未做镜像构建实测）。

### 8.4 最终验证与实测修正

- Python 后端：422 passed + 9 skipped（新增 infra 30 例；`test_cross_backend.py` 未双开时跳过）。
- Java 后端：JDK 17 + Maven 3.9.9 实测 32 passed / BUILD SUCCESS；主源码零编译错误。
- 双后端一致性：两服务同时运行时 `test_cross_backend.py` **9 passed**（登录/商品/订单/推荐/越权/退款/健康契约）。
- 前端：13 passed（4 文件）+ `npm run build` 成功。
- Compose：`docker-compose --env-file .env.example config` 通过；本机 Docker 守护进程未启动，未做镜像构建实测。
- 实测修正：Java 种子对齐共享契约、登录按显示名查找、新增 `getOrder` 作用域工具与 `OfflineToolFallback`；Python 登录增补 `user` 对象；修复 LangChain4j 1.24.0 的 `ChatMemoryStore` 包名与 `provider()` 返回类型变更；前端 Dockerfile 不再覆盖 `config.js` 的错误键名。
