# ecom-java-backend（Java 版电商智能体后端）

与现有 Python(FastAPI/LangChain) 后端**共用同一套 `/api` 契约**的第二套实现，前端切换 baseURL 即可互换。仅在 `java-backend/` 目录内实现，不修改 Python 后端与前端。

## 技术栈

| 组件 | 版本 / 选型 |
|---|---|
| JDK | 17（`maven.compiler.release=17`） |
| Spring Boot | 3.3.5（`spring-boot-starter-parent`） |
| LangChain4j | **1.24.0**（BOM 锁定，见下方核实结果） |
| MySQL 8 | `spring-boot-starter-data-jpa` + `mysql-connector-j`；未配置时 H2 内存回退 |
| Redis | `spring-boot-starter-data-redis`，会话记忆持久化（可选，失败回退内存） |
| RabbitMQ | `spring-boot-starter-amqp`，领域事件（可选，回退内存队列） |
| Milvus | `langchain4j-milvus`  embedding store（可选，回退关键词检索） |
| 大模型 | DeepSeek / 通义千问，均走 OpenAI 兼容协议（`OpenAiChatModel` 不同 base-url） |
| API 文档 | springdoc-openapi 2.6.0 |
| 鉴权 | 手写 HMAC-SHA256 + Base64Url Token（无 Spring Security 全家桶） |

## 构建与运行

本机无需预装 Maven，仓库已带 Maven Wrapper（首次运行自动下载 Maven 3.9.9 与依赖）：

```bash
cd java-backend
./mvnw -B test                 # 32 个测试
./mvnw -B -DskipTests package  # 生成 target/ecom-java-backend-0.1.0.jar
./mvnw spring-boot:run         # 默认 http://localhost:8080
```

Windows CMD 使用 `mvnw.cmd`。Docker：`docker build -t ecom-java-backend . && docker run -p 8080:8080 ecom-java-backend`。

**零依赖启动**：不设置任何环境变量时，自动使用 H2 内存库、进程内记忆、内存事件队列、关键词 RAG、离线规则模型（含真实工具调用），全部接口可跑通。

## LangChain4j 1.24.0 坐标核实（已联网核实）

| 核实项 | 结果 |
|---|---|
| `dev.langchain4j:langchain4j-bom:1.24.0` | ✅ 存在于 Maven Central（2026-11-19 发布） |
| `dev.langchain4j:langchain4j:1.24.0` | ✅ 稳定版，核心 `@Tool` / `ChatMemory` / RAG API |
| `dev.langchain4j:langchain4j-open-ai:1.24.0` | ✅ 稳定版，提供 `OpenAiChatModel` / `OpenAiEmbeddingModel` |
| `dev.langchain4j:langchain4j-store-milvus:1.24.0` | ❌ **不存在**（官方无此 artifact） |
| `dev.langchain4j:langchain4j-milvus:1.24.0-beta34` | ✅ 替代 artifact，由 1.24.0 BOM 自动解析；`MilvusEmbeddingStore.builder().host().port().collectionName().dimension().token()` |
| Spring Boot 3 starter | `langchain4j-spring-boot-starter` / `langchain4j-open-ai-spring-boot-starter`（均在 BOM 中为 `1.24.0-beta34`）；本项目使用核心 API 手动装配，不依赖 starter，以规避版本差异 |

关键 API 均按官方源码/文档核对后使用最小稳定子集：`AiServices`（作为替换点注释保留）、低层 `ChatModel.chat(ChatRequest)` + `ToolSpecifications.toolSpecificationsFrom(Object)` + `ToolExecutionResultMessage.from(...)`、`MessageWindowChatMemory` + `ChatMemoryStore`、`EmbeddingStoreIngestor` + `EmbeddingSearchRequest`。

## API 列表（与 Python 后端对齐）

| 方法 | 路径 | 响应要点 |
|---|---|---|
| POST | `/api/auth/login` | `{token, user:{id,name,role}, user_id, role, permissions}`（后三个兼容现有前端） |
| GET | `/api/auth/me` | `{id,name,role,permissions}` |
| GET | `/api/health` | `{status, service}` |
| GET | `/api/infra/health` | `{components:{mysql,redis,rabbitmq,milvus,llm}}`，每项含 `configured/active/backend/detail` |
| GET | `/api/products?category=&q=&query=` | `Product[]`（`tags` 为数组） |
| GET | `/api/products/{id}` | `Product` |
| GET | `/api/orders?customerId=` | `Order[]`（按角色隔离） |
| POST | `/api/orders` | `Order`，支持 `Idempotency-Key` 头 |
| GET | `/api/orders/{id}` | `Order` |
| POST | `/api/orders/{id}/refund` | `{orderId,status,approvalRequired?,threadId?}` |
| POST | `/api/chat` | `{answer, toolCalls, traceId, trace_id, route, context}` |
| GET / POST | `/api/chat/stream` | SSE：`node/route/context/tool/token/done` 事件 |
| POST | `/api/frontier/security/scan` | `{detected,score,matched,risk_level,action}` |
| POST | `/api/frontier/rag/rewrite` | `{mode,queries,hits}` |
| GET | `/api/graphs`, `/api/traces`, `/api/audit` | 前端可视化兼容端点 |
| GET | `/api/context/preview`, `/api/rag/search`, `/api/capabilities/metrics` | 上下文/RAG/指标 |
| POST | `/api/workflows/fulfillment/run`, `/resume` | 履约推进与 HITL 审批 |

Swagger UI：`http://localhost:8080/swagger-ui.html`。错误统一为 `{detail: string}`。

## Agent 能力映射

| 知识点 | 实现位置 |
|---|---|
| Tool / Function Calling | `agent/Tools.java`（5 个 `@Tool`：商品搜索/库存/下单/订单/退款） |
| Agent Loop | `agent/ReActRunner.java`（工具→回填→再推理，最大轮次保护；注释给出 `AiServices` 替换点） |
| Multi-Agent | `agent/Supervisor.java` 路由 + `agent/Specialists.java` 三个 specialist |
| Workflow / State Machine | `service/WorkflowService.java`（created→paid→shipped→delivered，refund_requested） |
| HITL | 退款超阈值返回 `pending_approval` + `threadId`，`/api/workflows/fulfillment/resume` 审批 |
| Memory | Redis `MessageWindowChatMemory`（`config/RedisChatMemoryStore.java`），失败回退内存 |
| Context Engineering | `agent/ContextBuilder.java`（系统提示模板 + 字符预算裁剪 + 快照） |
| RAG | `rag/DocumentIngestor.java` + `rag/RetrievalService.java` + `rag/MilvusConfig.java`（Milvus 或关键词回退，答案带引用来源） |
| Reliability | `reliability/RetryHelper.java`（指数退避）、`IdempotencyGuard.java`、LLM 不可用时 `OfflineToolFallback` 降级 |
| Observability | `observability/TraceContext.java`（MDC traceId）+ `Metrics.java`（计数） |
| Security | `security/InjectionScanner.java`、`RbacGuard.java`（三级角色 + 工具白名单）、`TokenService.java`、审计日志 |

## 主要环境变量

全部在 `application.yml` 中以 `${ENV:default}` 形式读取：

- `SERVER_PORT`（8080）、`APP_NAME`
- `MYSQL_URL` / `MYSQL_USER` / `MYSQL_PASSWORD`（空则 H2）、`JPA_DDL_AUTO`、`SQL_INIT_MODE`
- `REDIS_HOST` / `REDIS_PORT`、`REDIS_MEMORY_ENABLED`
- `RABBITMQ_HOST` / `RABBITMQ_PORT`、`EVENT_PUBLISH_ENABLED`
- `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL`
- `QWEN_API_KEY` / `QWEN_BASE_URL` / `QWEN_MODEL`、`LLM_PROVIDER`（auto/deepseek/qwen/offline）
- `MILVUS_ENABLED` / `MILVUS_HOST` / `MILVUS_PORT` / `MILVUS_COLLECTION` / `MILVUS_TOKEN`
- `JWT_SECRET`、`TOKEN_TTL_SECONDS`、`AGENT_MAX_ROUNDS`、`REFUND_THRESHOLD`、`RAG_TOP_K`、`MEMORY_MAX_MESSAGES`

种子账号（与 Python 后端一致）：`U001/U002`（customer）、`S001`（service）、`A001`（admin），密码均为 `123456`。种子商品 `P001`~`P008`，订单 `O1001`~`O1003`。

## 测试与验证

- 已使用 Maven Wrapper 实际执行 `./mvnw -B test`：**32 个测试全部通过**（29 个 JUnit5 单元测试 + 1 个 `@SpringBootTest` 集成类中的 3 个用例）。
- 已实际执行 `./mvnw -B -DskipTests compile`：**编译通过**（JDK 25 上以 `--release 17` 编译）。
- 测试覆盖：Token 签发/验签/篡改/过期、注入扫描、RBAC 与工具白名单、状态机、重试与幂等、上下文裁剪、契约序列化、ReAct 工具循环、全链路登录→商品→对话。

## 已知限制

1. Java 侧仅实现核心契约与部分前沿端点；Python 的 `/api/capabilities/*` 高级能力（规划、沙箱、A2A、RAGAS 等）未对齐，见技术架构文档。
2. Milvus 模块为 BOM 中的 beta 版本 `1.24.0-beta34`（官方 1.24.0 无该 stable 模块）；未配置时自动回退关键词检索。
3. 离线规则模型能完成工具调用与模板化回答，但不具备真实语义理解；需配置 DeepSeek/千问 Key。
4. SSE  token 事件为按字符切片推送（ChatModel 为非流式），接入流式模型后可替换为 `StreamingChatModel`。
5. 审计与指标为进程内实现，重启后重置；生产环境应替换为持久化存储。
