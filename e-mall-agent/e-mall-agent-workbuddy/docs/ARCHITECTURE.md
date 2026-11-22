# 技术架构

## 1. 技术选型

| 层 | 技术 | 版本 / 说明 |
|---|---|---|
| 前端 | Vue 3 + TypeScript + Vite + Pinia + vue-router | SSE 流式对话、SVG 工作流可视化 |
| 后端 | Python 3.11+ / FastAPI / uvicorn | REST + SSE，Pydantic v2 校验 |
| Agent 框架 | **langchain 1.5.2** | `create_agent` + middleware（LangChain 1.x 起 agent 运行在 LangGraph 之上） |
| 编排运行时 | langgraph 1.2.x | `StateGraph`、checkpointer、`interrupt()` / `Command(resume=...)` |
| MCP | `langchain-mcp-adapters` + `mcp` FastMCP | stdio / streamable-http；官方适配器转换 MCP 工具 |
| RAG | `langchain-core` `InMemoryVectorStore` + 自建确定性哈希 Embedding | 零 API Key 可运行；向量召回 + 中文 n-gram 词面重排 |
| 可观测性 | 进程内 TraceCollector + AuditLogger + 前端图可视化 | 可替换为 LangSmith / OpenTelemetry |
| 测试 | pytest + pytest-asyncio；Vitest + Vue Test Utils | 39 个后端用例 + 前端用例 |

> 版本说明：2026-11 验证 PyPI 最新 Python 版为 `langchain==1.5.2`、`langgraph==1.2.23`。LangChain 1.x 中 v0 的 `LLMChain` / `create_react_agent` 已迁移到 `langchain-classic` 或由 `create_agent` 取代，本项目只使用 1.5 的现代 API。

## 2. 总体分层

```mermaid
flowchart TB
    FE[Vue3 前端<br/>对话 / 商品 / 订单 / 工作流 / 管理] -->|REST + SSE| API[FastAPI 接入层<br/>认证 · RBAC · 审计 · 限流入口]
    API --> SUP[多智能体编排层<br/>LangGraph Supervisor]
    API --> WF[LangGraph 工作流<br/>订单履约 + 人工审批]
    API --> CTX[上下文工程 ContextEngine]
    API --> RAG[RAG Pipeline]
    SUP --> SA[商品 Agent]
    SUP --> OA[订单 Agent]
    SUP --> SP[售后 Agent]
    SUP --> GA[通用 Agent]
    SA & OA & SP & GA --> MW[LangChain 1.5 Middleware<br/>摘要 · PII · 重试 · 调用上限 · Trace]
    MW --> TOOLS[MCP Tool 层]
    TOOLS --> LOCAL[local 模式：进程内同一批工具函数]
    TOOLS --> MCPS[http 模式：FastMCP Server :8001]
    LOCAL & MCPS --> REPO[(领域仓储 / 订单 · 商品 · 用户)]
    RAG --> VS[(向量库 + 知识文档)]
```

## 3. 核心链路

### 3.1 对话请求（SSE）

1. `POST /api/chat/stream`，FastAPI 依赖解析 Bearer Token，写入 `ContextVar`（请求级身份，工具内部可读取）。
2. Supervisor 图执行：
   - `context` 节点：RAG 检索 + 工具清单 + 用户身份 + 历史滑窗，按优先级装箱，产出可解释快照；
   - `route` 节点：规则路由器将意图映射到 shopping / order / support / general；
   - 对应 specialist（`create_agent` 编译出的子图）执行模型循环与工具调用；
   - `finalize` 节点从消息序列提取最终回答。
3. 前端按 `node → route/context/tool → token → done` 顺序增量渲染，并展示工具调用与上下文快照。

### 3.2 MCP 工具

- 单一真源：`app/mcp/tools.py` 中的 8 个业务函数。
- `local` 模式（默认）：`StructuredTool.from_function` 包装同一批函数，无需额外进程，便于开发/测试。
- `http` 模式：独立 `FastMCP` 进程暴露 `http://127.0.0.1:8001/mcp`，`MultiServerMCPClient` 通过 `langchain-mcp-adapters` 转换为 LangChain 工具并注入 agent；支持 Authorization header 透传。
- 所有工具在**函数内部**再次校验权限与数据归属，避免仅依赖 LLM 自觉调用。

### 3.3 RAG

- 文档：售后、配送、优惠、发票、商品知识（8 条种子）。
- Embedding：`HashEmbeddings` 对中文 1/2/3-gram 与英文词做稳定哈希，L2 归一化；确定性、无网络依赖。
- 召回：向量相似度召回候选 → 中文 n-gram 词面重叠 + 来源命中加权重排 → Top-K。
- 注入：由 ContextEngine 以 `[检索增强知识]` 区块进入 SystemMessage，同时作为 `rag_search` 工具供 agent 按需调用。

### 3.4 上下文工程

`ContextEngine` 按优先级（角色规则 > 用户身份 > 检索知识 > 工具清单）装箱，预留用户轮与历史轮预算；历史采用滑窗 + 超长轮截断标记；LangChain 侧另配 `SummarizationMiddleware`（`trigger=("messages",14)`）做二级压缩。每次构建输出 `ContextSnapshot`，前端可直接展示各区块字符数、是否纳入/截断。

### 3.5 稳定性设计

| 关注点 | 实现 |
|---|---|
| 认证 | HMAC 签名 Token（`ECOM_SECRET_KEY`），`decode_token` 校验签名、过期与角色白名单；生产可换 OAuth2/JWT |
| 授权 | RBAC 权限矩阵（guest/customer/service/admin）+ `require_permission` 依赖 + 工具级 `filter_tools` + 函数级数据归属校验 |
| 数据隔离 | `ContextVar` 传递当前用户；customer 仅能读自己的订单，service/admin 可跨客户；越权写审计日志 |
| 人工审批 | LangGraph `interrupt()` 在履约工作流中对 ≥¥500 订单暂停，`Command(resume=bool)` 恢复 |
| 重试/降级 | `ToolRetryMiddleware` 工具重试；`SummarizationMiddleware` 上下文压缩；`ModelCallLimitMiddleware` 防死循环；离线模型保证无 Key 可用 |
| PII | `PIIMiddleware` 对邮箱脱敏、手机号掩码（输入侧） |
| 审计 | 登录、下单、退款、越权、审批均落 AuditLogger，可按 actor/decision 查询 |
| 追踪 | TraceCollector 记录节点流转、工具调用、最终答案长度；`/api/graphs` 提供图元数据供前端渲染 |
| 错误处理 | `PermissionError` → 403；业务校验 `ValueError` → 400；工具异常以 JSON error 回传模型而非崩溃 |

## 4. 目录结构

```
backend/
  app/
    main.py                 FastAPI 入口
    config.py               ECOM_* 配置
    domain/                 实体与内存仓储（可替换 SQL）
    security/               rbac.py（权限/Token/ContextVar）、audit.py
    context/engine.py       上下文工程
    rag/                    embeddings.py、pipeline.py
    llm/factory.py          离线工具调用模型 + OpenAI 切换
    mcp/                    tools.py（工具真源）、server.py（FastMCP）
    agents/                 tools.py、specialists.py、supervisor.py
    workflows/fulfillment.py 订单履约图
    observability/tracer.py Trace + 图描述
    api/                    routes.py、schemas.py
  tests/                    39 个 pytest 用例
frontend/
  src/{api,stores,router,types,views,components}
docs/                       产品/架构/API/测试文档
```

## 5. 生产化替换点

1. 内存仓储 → PostgreSQL/SQLAlchemy；向量库 → pgvector / Milvus。
2. `InMemorySaver` → `PostgresSaver`；ConversationStore → Redis。
3. `HashEmbeddings` → BGE / OpenAI Embeddings；离线模型 → `ECOM_LLM_PROVIDER=openai`。
4. HMAC Token → 企业 IdP（OAuth2/OIDC），并在 MCP HTTP server 前置同一套校验中间件。
5. TraceCollector / AuditLogger → LangSmith + OpenTelemetry + 集中日志。
6. API 网关增加速率限制、幂等键（下单）、请求体大小限制。

## 6. 关键设计取舍

- **多智能体而非单体巨型 Prompt**：路由确定、工具子集隔离、权限边界清晰，便于定位问题。
- **规则路由 + 规则离线模型**：保证零 Key 可运行与测试确定性；真实 LLM 只需切换环境变量，agent/middleware/workflow 代码不变。
- **工具函数单一真源**：MCP 与本地适配共用，避免两套实现漂移。
- **工具内二次鉴权**：即使模型被提示注入诱导调用越权工具，也会返回 `permission_denied` 并落审计。
