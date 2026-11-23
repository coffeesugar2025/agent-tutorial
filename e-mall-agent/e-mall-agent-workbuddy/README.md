# 电商智能体（Vue3 共用前端 + Python / Java 双后端）

一个可运行的全栈电商智能体示例：**一套 Vue3 前端**，可切换**两套后端**——

- **后端 A · Python**：Python 3.12 / FastAPI / **LangChain 1.5.2** / LangGraph 1.2 / MCP（默认实现，能力最完整）
- **后端 B · Java**：JDK 17 / Spring Boot 3 / **LangChain4j 1.24.0**

共享基础设施：**Milvus**（RAG 向量库）、**MySQL 8**（业务数据）、**Redis 7**（会话/缓存）、**RabbitMQ**（领域事件）；大模型支持 **DeepSeek / 通义千问** 等多提供方，默认离线规则模型保证零 Key 可运行。

覆盖 MCP 工具、上下文工程、RAG、多智能体、工作流、HITL、可视化、安全对齐、评测体系与生产可靠性。

---

## 1. 一键启动（Docker Compose，推荐）

```bash
cp .env.example .env       # 按需填写 API Key；不填也能跑（自动回退离线/内存实现）
./scripts/deploy.sh        # build + up -d
./scripts/smoke.sh         # 全链路健康冒烟
```

| 入口 | 地址 |
|---|---|
| 前端 | http://localhost |
| Python 后端 | http://localhost:8000/docs |
| Java 后端 | http://localhost:8080 |
| RabbitMQ 管理台 | http://localhost:15672 |

切换 nginx 上游：在 `.env` 设置 `UPSTREAM_BACKEND=backend-java:8080` 后 `docker compose up -d frontend`；或在前端系统管理页直接用引擎切换按钮（浏览器侧 baseURL，无需重建镜像）。

停止与运维：`./scripts/stop.sh`、`./scripts/logs.sh backend-python`、`./scripts/reset-data.sh`（会二次确认）。

---

## 2. 本地开发（不用 Docker）

### 2.1 Python 后端

```bash
python3.12 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
# 可选生产依赖：pip install -r backend/requirements-prod.txt
cd backend && .venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
```

打开 `http://localhost:8000/docs`。默认**离线确定性模型**，无需任何 API Key。

### 2.2 Java 后端

```bash
cd java-backend
./mvnw spring-boot:run       # http://localhost:8080
```

未配置 MySQL/Redis/RabbitMQ/Milvus/API Key 时自动内存回退。

### 2.3 前端（共用）

```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173
# 默认代理到 :8000；VITE_API_BASE_URL=http://localhost:8080 可切到 Java
```

### 2.4 测试

```bash
cd backend  && .venv/Scripts/python.exe -m pytest -q   # 422+ passed
cd backend  && .venv/Scripts/python.exe -m pytest tests/test_infra.py -q
cd java-backend && ./mvnw test                          # 32 passed（JDK17 + Maven 实测）
ECOM_JAVA_BACKEND_URL=http://localhost:8080 backend/.venv/Scripts/python.exe -m pytest backend/tests/test_cross_backend.py -q   # 两后端在线时 9 passed
cd frontend && npm test -- --run && npm run build        # 7+ passed + 构建成功
docker compose --env-file .env.example config            # Compose 语法校验
```

---

## 3. 演示账号

| 用户名 | 密码 | 角色 |
|---|---|---|
| 张三 | 123456 | customer（U001） |
| 李四 | 123456 | customer（U002） |
| 王客服 | 123456 | service（S001） |
| 管理员 | 123456 | admin（A001） |

**演示路径**：张三问"推荐降噪耳机" → "我的订单" → "O1003 想退货退款"；切李四问"O1001"看越权拦截；管理员在工作流页运行 O1001 并审批；管理页查看 Trace / Audit / 基础设施健康；最后在管理页切换到 Java 引擎重新登录，对比两引擎结果。

---

## 4. 核心能力

- **MCP TOOL**：8 个业务工具，`local` 进程内与 FastMCP `streamable-http` 双模式，同一函数真源。
- **Agent 工程**：Agent Loop、意图路由、ReAct / Plan-and-Solve、反思自纠错、5 类编排模式、Tool RAG、A2A 骨架、Middleware 生命周期。
- **多智能体**：Supervisor + 商品/订单/售后/通用 specialist，最小工具集隔离。
- **工作流与 HITL**：LangGraph 履约图，`interrupt()` 大额审批、`Command(resume=...)` 恢复、Checkpoint 长任务恢复。
- **上下文工程**：优先级装箱、字符/Token 预算、滑窗压缩、可解释快照。
- **RAG 与知识治理**：Milvus 向量库（可回退内存）、混合检索 + Rerank、查询改写、RAGAS、引用校验、Text2SQL/Text2Cypher、GraphRAG、版本治理、ACL 权限检索。
- **三层记忆**：会话 / 情景 / 用户长期记忆，Redis 可替换存储。
- **多模型**：DeepSeek、千问、OpenAI 兼容协议接入，模型选型 Benchmark、推理参数、JSON Schema 强约束、Prompt 版本管理。
- **安全与对齐**：Prompt 注入（直接/间接）防御、越狱检测、输出审核、MCP 工具投毒防护、RBAC + 数据隔离、审计、PII 脱敏、红队测试。
- **可靠性**：重试/超时/幂等/降级/终止条件、限流/熔断/背压、Feature Flag 灰度、密钥轮换、SLO 告警。
- **可观测与评测**：Trace / Audit / Metrics（P95/P99）、LLM-as-Judge、轨迹评测、Golden Case / Replay / 回归门禁、在线 A/B 实验。
- **沙箱**：AST 静态校验 + 受限执行 + Code Mode + Harness。

---

## 5. 目录

```
backend/           Python 后端（app/{domain,security,context,rag,llm,mcp,agents,workflows,
                   observability,api,planning,reliability,memory,sandbox,resume,eval,infra}）
backend/tests/     pytest 用例（392+）
java-backend/      Java 后端（Spring Boot + LangChain4j，src/main/java/com/example/ecom）
frontend/          Vue3 共用前端（views / components / api / stores / router / types）
docker/            MySQL 初始化 SQL、nginx 模板
scripts/           deploy / stop / logs / smoke / reset-data
docs/              架构、产品、API、测试、能力矩阵、生产化、面试题
docker-compose.yml 全栈编排
```

核心文档：

| 文档 | 内容 |
|---|---|
| [`docs/TECHNICAL_ARCHITECTURE.md`](docs/TECHNICAL_ARCHITECTURE.md) | 双后端技术架构、基础设施、多模型、数据流、部署拓扑 |
| [`docs/PRODUCT_ARCHITECTURE.md`](docs/PRODUCT_ARCHITECTURE.md) | 产品功能地图、角色权限、双引擎体验、用户旅程 |
| [`docs/TEST_SUITE.md`](docs/TEST_SUITE.md) | 单元/集成/产品/E2E/一致性/可靠性测试体系 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Python 后端单栈架构细节 |
| [`docs/PRODUCT.md`](docs/PRODUCT.md) | 产品功能说明与演示脚本 |
| [`docs/AGENT_KNOWLEDGE_MAP.md`](docs/AGENT_KNOWLEDGE_MAP.md) | 六类 Agent 知识点全景 + 每项原理要点与 Python/Java 真实源码对照（2331 行） |
| [`docs/CAPABILITY_MATRIX.md`](docs/CAPABILITY_MATRIX.md) | 能力项状态对照 |
| [`docs/API.md`](docs/API.md) | REST/SSE 接口说明 |
| [`docs/TESTING.md`](docs/TESTING.md) | Python/前端测试运行说明 |
| [`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md) | 生产化改造清单 |

---

## 6. 如实说明

1. 默认离线规则模型保证零 Key 可跑；真实语义理解需配置 DeepSeek / 千问密钥。
2. 基础设施未配置时自动回退内存实现，`/api/infra/health` 会如实标注 `active:false`。
3. SFT/LoRA/DPO/RLHF、vLLM、灾备多活属训练/基础设施范畴，本项目保留可替换适配点，不伪称在应用代码中实现。
4. Java 后端聚焦核心链路与生产基础设施，Python 后端覆盖全部高级能力；差异见产品架构文档。
