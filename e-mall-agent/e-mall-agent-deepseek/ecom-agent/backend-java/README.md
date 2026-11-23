# backend-java · 星图商城电商智能体平台（Java 端）

Spring Boot 3.3 + JDK 17 实现的电商智能体后端，与 `backend-python`（FastAPI）**共享同一份**
`docs/03-API契约.md`、同一套 MySQL / Redis / RabbitMQ / Milvus 结构与同一组环境变量。

- 契约：`docs/03-API契约.md`（唯一事实源），统一前缀 `/api/v1`，信封 `{code,message,data,traceId}`
- 端口：`8080`（Python 端 `8000`，由编排层用 `SERVER_PORT` 区分）
- 多 Agent：SUPERVISOR / SHOPPING / SERVICE / OPS，手写 ReAct 主循环（`agent/AgentRuntime`）
- HITL：`IRREVERSIBLE` 工具先挂起 `approval_task`，审批通过后才执行（退款 / 转人工）
- RAG：MySQL 父块 + Milvus 稠密 + BM25 稀疏 + RRF 融合 + 重排，三级降级
- 可观测：`agent_trace/agent_span/llm_call` + Prometheus 指标 + `X-Trace-Id` 贯穿

---

## 1. 目录与分层

```
src/main/java/com/xingtu/agent/
├── api/            # ★ REST 层（本目录新增）：7 个 Controller + dto/
│   └── dto/        #   契约字段一一对应的 Req/VO（record）
├── mq/             # ★ RabbitMQ 消费者：知识索引/删除、退款、会话摘要、评测批次
├── eval/           # ★ 离线评测：EvalDataset / EvalJudge / EvalRunner
├── agent/          # AgentRuntime、SSE sink、终止策略、注册表
├── hitl/           # ApprovalService（审批闭环）
├── service/        # RefundService（幂等退款）
├── rag/            # 切片、检索、RRF、重排、入库
├── tool/           # 工具注册表与各领域工具、Text2SQL 守卫、沙箱
├── memory/         # 会话窗口、滚动摘要、用户画像
├── llm/            # 模型路由、兜底链、熔断、成本
├── security/       # JWT、认证过滤器、RBAC、限流、注入检测、PII
├── infra/          # JDBC 访问、Redis、Milvus REST、Rabbit 发布、repo/
├── obs/            # 指标、追踪、结构化日志
└── config/         # AppProperties、Web/Rabbit/Executor 等配置
```

`api/`、`mq/`、`eval/` 与 `Dockerfile`、`README.md` 为本次补齐内容；其余为已存在的实现。

## 2. 构建

要求：JDK 17、Maven 3.9+（本机无 Maven 时用 Docker 构建，见第 7 节）。

```bash
cd backend-java
mvn -B clean package -DskipTests
# 产物：target/ecom-agent-java.jar（spring-boot 可执行 fat jar）
```

## 3. 运行

### 3.1 先起中间件

```bash
# 仓库根目录：只起 MySQL / Redis / RabbitMQ / Milvus 等基础设施
cd deploy
docker compose -f docker-compose.infra.yml up -d
```

### 3.2 起服务

```bash
cd backend-java
java -jar target/ecom-agent-java.jar
# 或开发模式
mvn spring-boot:run
```

默认监听 `http://localhost:8080`。常用环境变量（完整清单见 `.env.example`）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `SERVER_PORT` | `8080` | HTTP 端口 |
| `SPRING_PROFILES_ACTIVE` | `dev` | `dev` 连 localhost，容器内由编排覆盖 |
| `MYSQL_HOST/PORT/DB/USER/PASSWORD` | `mysql/3306/ecom_agent/ecom/ecom123` | 与 Python 端同库 |
| `REDIS_HOST/PORT/PASSWORD` | `redis/6379/空` | 限流、缓存（不可用时降级本地） |
| `RABBITMQ_*`、`MQ_ENABLED` | `rabbitmq/.../true` | `MQ_ENABLED=false` 时消费者不注册 |
| `MILVUS_ENABLED/HOST/PORT` | `true/milvus/19530` | REST 端口默认 `9091`（`MILVUS_PORT` 用于展示，REST 走 `rest-port`） |
| `LLM_PRIMARY`、`MOCK_LLM` | `deepseek`、`false` | 见第 5 节 |
| `LLM_FALLBACK_CHAIN` | `deepseek,qwen,qwen-turbo,openai,ollama,mock` | 逗号分隔，末尾 mock 兜底 |
| `JWT_SECRET`、`JWT_EXPIRE_SECONDS` | `change-me-in-prod`、`86400` | 生产必须改，至少 32 字节 |
| `MAX_STEPS`、`MAX_TOKEN_BUDGET`、`TASK_TIMEOUT_SECONDS` | `12/60000/120` | Agent 终止条件 |
| `RATE_LIMIT_PER_MINUTE` | `30` | 每用户每分钟对话次数 |

启动后自检：

```bash
curl -s http://localhost:8080/health          # 裸 JSON：{"status":"UP|DEGRADED","components":{...}}
curl -s http://localhost:8080/metrics | head  # Prometheus 文本（Actuator）
curl -s http://localhost:8080/api/v1/meta/capabilities   # 需 Bearer JWT
```

**演示账号**（来自 `deploy/mysql/init/02-seed.sql`）：`admin / Passw0rd!`（ADMIN,OPS）、
`alice / Passw0rd!`（USER）、`bob / Passw0rd!`（USER，越权对照）。

```bash
# 登录拿 token
TOKEN=$(curl -s -X POST http://localhost:8080/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"Passw0rd!"}' | jq -r .data.token)

# 建会话
SID=$(curl -s -X POST http://localhost:8080/api/v1/chat/sessions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"拍照手机"}' | jq -r .data.id)

# SSE 流式对话（-N 关闭缓冲，逐条打印 event/data）
curl -N -X POST http://localhost:8080/api/v1/chat/stream \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"sessionId\":$SID,\"message\":\"帮我找 5000 以内的拍照手机\"}"
```

SSE 事件顺序与契约一致：`meta → agent → (delta|tool_call|tool_result|citation)* → usage → done`；
需要人工审批时以 `approval` 结束并带 `done.finishReason=approval_required`；异常以 `error` 结束且不再发 `done`；
空闲每 15s 发送 `: ping` 注释行。

## 4. 测试

```bash
cd backend-java
mvn test                 # 全部测试
mvn -Dtest=ChunkerTest test     # 单个测试
```

测试**不需要** MySQL / Redis / RabbitMQ / Milvus / 外网：

- `src/test/java/com/xingtu/agent/unit/`（9 个纯单元测试）
  `ChunkerTest`、`SparseEncoderTest`、`TerminationPolicyTest`、`InjectionDetectorTest`、
  `PiiMaskerTest`、`Text2SqlGuardTest`、`CircuitBreakerTest`、`CostCalculatorTest`、
  `ReciprocalRankFusionTest`
- `src/test/java/com/xingtu/agent/integration/`（3 个集成测试，均不启动 Spring 容器）
  - `AuthControllerTest` / `ProductApiTest`：`MockMvcBuilders.standaloneSetup(...)` + Mockito 仓储
  - `ApprovalFlowTest`：Mockito 替身驱动 `ApprovalService` 的完整审批闭环
    （通过→执行退款、拒绝→零副作用、越权 40300、重复/过期 40900、参数错误 40001）

> 说明：契约要求「集成测试」，但为满足“能编译、不依赖外部服务”，`@SpringBootTest` 全部避免，
> 统一用 standalone MockMvc / Service + Mockito，覆盖接口编解码、错误码与状态机。

## 5. Mock 模式（离线全链路）

无任何 API Key、无 Milvus、甚至无 MQ 也能跑通「登录 → 流式对话 → 工具调用 → 审批 → 评测」：

```bash
cd backend-java
LLM_PRIMARY=mock \
EMBEDDING_PROVIDER=hash \
MILVUS_ENABLED=false \
MQ_ENABLED=false \
mvn spring-boot:run
```

- `LLM_PRIMARY=mock`：`MockChatModel` 按 prompt 中的 `AGENT/STEP/QUESTION/TOOL_RESULT` 规则确定性产出
  工具调用或最终答案，可复现 ReAct、成本（0 分）、追踪与审批中断。
- `EMBEDDING_PROVIDER=hash`：本地哈希向量，检索降级为「进程内向量 + BM25」。
- `MILVUS_ENABLED=false`：Milvus 调用直接走 `MilvusUnavailableException` 降级分支。
- `MQ_ENABLED=false`：消费者与 Rabbit 拓扑不注册；知识索引/删除、评测改为 `agentExecutor`/`evalExecutor`
  进程内异步执行（接口仍立即返回 `QUEUED`）。
- 仍需 MySQL（会话/消息/订单/审批都在库里）。只想起库：`deploy/docker-compose.yml` 的 `mysql` 服务。

跑一次评测（Mock 模式下全部用例可判分）：

```bash
curl -s -X POST http://localhost:8080/api/v1/admin/evals/run \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"suite":"shopping","repeat":3}'
curl -s "http://localhost:8080/api/v1/admin/evals/runs/1" -H "Authorization: Bearer $ADMIN_TOKEN"
```

suite：`shopping` / `service` / `ops` / `safety`；口径见 `eval/EvalRunner`（`passRate`=pass@k，
`passK`=k 次全过）。

## 6. 接口清单（与契约逐项对齐）

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | `/api/v1/auth/login` | 登录，返回 token/expiresIn/user | 公开 |
| GET | `/api/v1/auth/me` | 当前用户 | 登录 |
| POST | `/api/v1/chat/sessions` | 新建会话 | 登录 |
| GET | `/api/v1/chat/sessions` | 会话列表（≤50，按 lastMessageAt 倒序） | 登录 |
| GET | `/api/v1/chat/sessions/{id}` | 会话详情 | 登录（仅本人） |
| DELETE | `/api/v1/chat/sessions/{id}` | 软删除会话 | 登录（仅本人） |
| GET | `/api/v1/chat/sessions/{id}/messages?limit=50` | 历史消息 | 登录（仅本人） |
| POST | `/api/v1/chat/stream` | SSE 流式对话 | 登录 + 限流 |
| POST | `/api/v1/chat/sessions/{id}/interrupt` | 中断本轮 | 登录（仅本人） |
| GET | `/api/v1/chat/approvals?status=PENDING` | 待办审批 | 登录（仅本人） |
| POST | `/api/v1/chat/approvals/{approvalId}` | 审批决策 | 登录（仅本人） |
| GET | `/api/v1/products` | 商品分页检索 | 登录 |
| GET | `/api/v1/products/{sku}` | 商品详情（含 description） | 登录 |
| POST | `/api/v1/products/search` | 语义化商品检索（hybrid） | 登录 |
| GET | `/api/v1/orders` | 我的订单分页 | 登录（仅本人） |
| GET | `/api/v1/orders/{orderNo}` | 订单详情（手机号脱敏） | 登录（仅本人） |
| GET | `/api/v1/orders/{orderNo}/logistics` | 物流轨迹 | 登录（仅本人） |
| POST | `/api/v1/knowledge/documents` | 上传文档（multipart: file/title/docType/visibility） | ADMIN/OPS |
| GET | `/api/v1/knowledge/documents` | 文档列表 | ADMIN/OPS |
| DELETE | `/api/v1/knowledge/documents/{id}` | 软删除 + 异步清向量 | ADMIN/OPS |
| POST | `/api/v1/knowledge/documents/{id}/reindex` | 重建索引 | ADMIN/OPS |
| GET | `/api/v1/knowledge/jobs/{jobId}` | 作业进度 | ADMIN/OPS |
| POST | `/api/v1/knowledge/search` | 检索调试（dense/sparse/rerank 分数） | ADMIN/OPS |
| GET | `/api/v1/admin/overview?days=7` | 运营大盘 | ADMIN |
| GET | `/api/v1/admin/traces` | 链路列表 | ADMIN |
| GET | `/api/v1/admin/traces/{traceId}` | 链路详情（spans + replayable） | ADMIN |
| GET | `/api/v1/admin/costs?days=7` | 成本报表 | ADMIN |
| GET | `/api/v1/admin/models` | 模型健康度/熔断状态 | ADMIN |
| POST | `/api/v1/admin/evals/run` | 启动评测 | ADMIN |
| GET | `/api/v1/admin/evals/runs` | 评测批次列表 | ADMIN |
| GET | `/api/v1/admin/evals/runs/{id}` | 评测批次详情（含 cases） | ADMIN |
| GET | `/health` | 存活探针（裸 JSON，DEGRADED 仍 200） | 公开 |
| GET | `/metrics` | Prometheus 文本 | 公开 |
| GET | `/api/v1/meta/capabilities` | 能力声明 | 登录 |

内部事件（RabbitMQ，exchange `ecom.agent`）：`knowledge.index`、`knowledge.delete`、
`session.summarize`、`refund.execute`、`eval.batch`；消费者失败重试 3 次后落
`async_task.status='DEAD'`（死信交换机 `ecom.agent.dlx` 仍由拓扑保留）。

## 7. Docker

```bash
cd backend-java
docker build -t xingtu/ecom-backend-java:dev .
docker run --rm -p 8080:8080 \
  -e MYSQL_HOST=host.docker.internal -e REDIS_HOST=host.docker.internal \
  -e RABBITMQ_HOST=host.docker.internal -e LLM_PRIMARY=mock \
  xingtu/ecom-backend-java:dev
```

或直接由全栈编排构建（`deploy/docker-compose.yml` 的 `backend-java` 服务，context=`../backend-java`）。
镜像为多阶段构建（Maven 打包 + JRE 运行）、非 root 用户、内置 `curl` 供 healthcheck 使用。

## 8. 与 Python 端的差异

1. **技术栈**：Spring Boot 3.3 / JDK 17 / 手写 JDBC（无 ORM、无 JPA、无 MyBatis）。
   模型调用统一走 **LangChain4j**：`OpenAiChatModel`（`langchain4j-open-ai` + `langchain4j-http-client-jdk`）
   负责 DeepSeek / 通义千问 / OpenAI / Ollama 的 HTTP 传输与响应解析，`MockChatModel` 实现
   `ChatLanguageModel` 并提供离线确定性输出。Python 端为 FastAPI + LangChain 1.5。
2. **文档上传**：两端均支持 `.md` / `.txt` / `.docx` / `.pdf`。Java 端 docx 用 JDK 自带 ZIP + XML 去标签，
   pdf 用 Apache PDFBox 2.0.31（与 Python 端 pypdf 对应）；加密 PDF 返回 40001。
3. **`/health`**：按契约返回裸 JSON（`status` + `components`），不包 `ApiResponse`；`status` 只会是
   `UP`/`DEGRADED`，组件值为 `UP`/`DOWN`/`DISABLED`（`MQ_ENABLED=false`、`MILVUS_ENABLED=false` 时为
   `DISABLED` 且不影响整体 `UP`）。
4. **`/metrics`**：直接复用 Actuator 的 Prometheus 端点（`management.endpoints.web.path-mapping.prometheus=metrics`），
   未自建文本渲染；指标前缀 `ecom_agent_` 由 `MetricsCollector` 保证。
5. **`/api/v1/meta/capabilities`**：`backend="java"`；`mcp`/`skills` 为 `false`（Java 端未实现），
   `codeMode`/`text2sql` 取决于工具注册表里是否存在 `run_python`/`text2sql`，`hybridRag=true`。
6. **评测**：`EvalRunner` 直接调用模型（不走完整 Agent 工具环），`EvalJudge` 用关键词覆盖度 + 禁止词启发式，
   不调用 LLM-as-judge；因此分数用于回归趋势，不等价于人工质量评估。Mock 模式下 prompt 会注入
   `STEP/TOOL_RESULT` 让规则模型直接产出「第二轮最终答案」，保证离线可判分。
7. **MQ 重试**：消费者在进程内重试 3 次后写 `async_task(DEAD)` 并 ack（不再抛回队列），
   与 Python 端的 DLX 重投语义略有差异；死信交换机/队列仍已声明。
8. **`eval.batch` 消费者**：Java 端新增 `mq/EvalBatchConsumer`（契约事件表要求，Python 侧由任务队列承担）。
9. **`knowledge.delete` 消费者**：与 `knowledge.index` 同属 `KnowledgeIndexConsumer` 的两个 `@RabbitListener` 方法。
10. **登录**：Java 用 `BCryptPasswordEncoder` 校验 `sys_user.password_hash`（seed 为 `$2a$12$...`），
    JWT claims 与契约一致（`sub/username/roles/exp`）。

## 9. 已知未验证点（本机无 Maven / 无外网 / 无 Docker，未编译、未运行）

以下点按风险排序，建议首次拿到构建环境时优先验证：

1. **整体编译**：全部新增文件均未经过 `mvn compile`；风险点集中在 record 的 `@JsonInclude`
   （`ProductVO.description`）、`@RabbitListener(queues = 常量)`、`SseEmitter` 异步返回。
2. **Actuator `/metrics` 映射**：`management.endpoints.web.base-path=/` 且
   `path-mapping.prometheus=metrics`，若与其它端点冲突需确认最终路径仍为 `/metrics`。
3. **SSE 生命周期**：`SseEmitter` 的超时/心跳/`complete()` 时序、客户端断开后事件丢弃，
   以及 Tomcat 异步请求释放，需要在真实容器里压测确认。
4. **RabbitMQ 消费者注册**：`@ConditionalOnProperty(app.mq.enabled)` 与 `RabbitConfig` 条件一致；
   `MQ_ENABLED=false` 时不应残留 listener 容器，建议启动日志确认。
5. **BCrypt 兼容性**：seed 的 `$2a$12$` 哈希与 Spring `BCryptPasswordEncoder` 的匹配，
   以及 `alice / Passw0rd!` 能否登录成功（若失败优先核对 seed 是否被重新生成）。
6. **JSON 契约细节**：`BigDecimal` 输出（`4999.00` 是否保留两位）、时间格式
   `yyyy-MM-dd'T'HH:mm:ssXXX`（依赖 JVM 时区为 `Asia/Shanghai`）、`description` 在列表中是否被省略。
7. **SQL 兼容性**：`StatsRepository` 的 `DATE_FORMAT('%Y-%m-%d')`、`LlmCallRepository` 聚合、
   `MATCH ... AGAINST` 在不带 ngram 索引的库上的降级行为。
8. **知识上传**：docx 抽取对真实 Word 文件的效果（只处理 `word/document.xml`，不处理表格/页眉）；
   `IngestService` 原文落盘在 `java.io.tmpdir`，容器重启后 reindex 会失败。
9. **评测口径**：关键词判定阈值（`0.6`）与 mock 注入 `STEP/TOOL_RESULT` 的策略需要按真实模型再校准。
10. **MQ 开启但 Broker 不可用**：发布失败会由 `RabbitPublisher` 落 `async_task(QUEUED)` 兜底，
    但当前没有补偿任务自动重放，知识索引/评测会停在 QUEUED（接口本身仍返回成功）。
11. **Dockerfile**：`eclipse-temurin:17-jre-jammy` 内 `useradd`/`curl` 安装、healthcheck 的
    `curl` 可用性、`JAVA_TOOL_OPTIONS` 覆盖是否与 compose 一致，均未实际构建验证。
12. **未做**：未新增/修改任何既有 `.java` 文件；新增 `infra/repo/StatsRepository`（overview.trend 需要按天
    会话聚合）、`mq/MqSupport`（消费者重试/DEAD 落库公共逻辑）、`mq/EvalBatchConsumer`（`eval.batch`）三个
    计划外文件，如需严格保持文件清单可合并/删除。
