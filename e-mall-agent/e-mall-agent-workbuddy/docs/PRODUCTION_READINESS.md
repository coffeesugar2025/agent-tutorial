# 电商智能体上生产环境改造清单

> 基于当前仓库源码逐项核对（核对时间：2026-11-23）。
> 结论先行：**当前版本是可演示/可测试的原型（demo-grade），不具备直接上生产的条件**。
> 核心阻塞点有六个：内存数据、明文口令与自研 Token、离线规则模型、内存会话与检查点、MCP 无鉴权、全链路无可观测性。
> 好消息是：分层结构、工具单一真源、上下文快照、中间件链、LangGraph 拓扑、前后端 API 契约都可以保留，改造集中在"替换实现、不动接口"。

---

## 0. 现状评级

| 维度 | 现状 | 生产可用性 |
|---|---|---|
| 业务数据 | `InMemoryRepository` 全内存字典 + `RLock` | 不可用：重启丢数据、多副本不一致 |
| 认证 | 自研 HMAC Token、明文口令、无效 Token 静默降级 guest | 不可用 |
| 智能能力 | `RuleBasedChatModel` 关键词正则 + 模板回答 + 硬编码 P001/O1001 | 不可用 |
| 会话/工作流状态 | `ConversationStore` + 两处 `InMemorySaver` | 不可用：多副本断链、重启丢审批 |
| MCP | FastMCP 监听 `127.0.0.1:8001`，无任何鉴权 | 不可用 |
| RAG | 8 条硬编码文档 + 128 维哈希向量 + 无命中兜底 | 仅演示 |
| 可观测性 | 内存 TraceCollector(1000) / AuditLogger(500) | 不可用且含 PII 泄漏 |
| API 稳定性 | 无限流、无超时、无熔断、无幂等、SSE 无心跳 | 不可用 |
| 前端 | Token 存 localStorage、SSE 不可取消、dev proxy | 需加固 |
| 工程化 | 79 pytest + 4 vitest 已通过，但无 CI/评测集/容器化 | 需补齐 |

---

## 1. 改造总览（按优先级）

优先级定义：
- **P0 上线阻塞**：不改不能上线，涉及数据丢失、越权、错误回答。
- **P1 上线前必做**：不改无法稳定运维、无法定位故障、无法满足合规。
- **P2 上线后迭代**：影响效果与成本，可灰度优化。

| # | 模块 | 优先级 | 一句话改造 |
|---|---|---|---|
| 1 | 数据层 | P0 | 内存仓储 → PostgreSQL + 事务行锁 + 幂等键 + Alembic 迁移 |
| 2 | 认证与身份 | P0 | 自研 HMAC → OIDC/JWT(JWKS)，口令哈希，无效 Token 返回 401 |
| 3 | 授权与租户 | P0 | 静态角色表 → 租户/资源级策略；MCP 远程模式补身份透传 |
| 4 | 模型与路由 | P0 | 离线规则模型 → 真实 LLM + 评测集 + 超时/降级/输出校验 |
| 5 | 会话与检查点 | P0 | 内存会话/检查点 → Redis + PostgresSaver，thread_id 稳定化与归属校验 |
| 6 | 人工审批 | P0 | 任意 thread 可 resume → 审批任务表 + 身份绑定 + 职责分离 + 阈值配置 |
| 7 | MCP Server | P0 | 无鉴权本地端口 → mTLS/网关鉴权 + 终端用户声明传递 + 不暴露公网 |
| 8 | 业务正确性 | P0 | 修 `stock >= 0` 假校验、假锁库存、退款写进地址、无支付态、无幂等 |
| 9 | CORS 与接口暴露 | P0 | `*` + credentials → 白名单；`/docs`、调试接口收口 |
| 10 | 可观测性 | P1 | 内存计数 → OTel 链路 + 结构化日志 + 不可篡改审计 + PII 脱敏 |
| 11 | API 稳定性 | P1 | 加限流/超时/并发闸/熔断/SSE 心跳/统一错误码 |
| 12 | 上下文工程 | P1 | 字符估算 → 模型 tokenizer 预算 + 提示注入防护 + 分层裁剪 |
| 13 | RAG | P1 | 哈希向量 → 真实 Embedding + 向量库 + 重排 + 去掉无命中兜底 |
| 14 | 前端 | P1 | localStorage Token → httpOnly Cookie/BFF；SSE 可取消 + 401 拦截 |
| 15 | 配置与密钥 | P1 | 弱默认密钥 → Secret Manager + 启动预检 fail-fast |
| 16 | 工程化发布 | P1 | 容器化 + 多副本 + 探针 + CI/CD + 灰度 |
| 17 | 合规 | P1 | 数据分级、保留期、删除权、日志脱敏、模型厂商 DPA |
| 18 | 效果与成本 | P2 | 语义缓存、模型分级路由、token 预算与成本告警、答案引用溯源 |

---

## 2. P0：上线阻塞项（逐项展开）

### 2.1 数据层：从内存字典到事务型数据库

**当前实现**
- `backend/app/domain/repository.py:11`：单进程 `dict` + `threading.RLock`，`_seed()` 写死 8 个商品、3 笔订单、4 个用户。
- `create_order()`（:129-153）在同一个锁内校验并扣库存，单进程内是原子的；但多副本各自持有一份库存。
- `request_refund()`（:173-178）把退款原因字符串拼进 `order.address`，属于演示 hack。
- `reset_repository()`（:191）是测试专用重置入口，生产不可暴露。

**生产风险**：进程重启订单与库存归零；两个副本同时卖同一 SKU 导致超卖；退款原因污染地址字段；无法做对账与审计追溯。

**改造方案**
1. 抽象出 `Repository` Protocol（保持现在的 `get_product/create_order/list_orders/...` 方法签名不变），新增 `PostgresRepository` 实现。
2. 表设计：`products`、`inventory`（`stock` + `version` 乐观锁）、`orders`、`order_items`、`users`、`idempotency_keys`、`audit_log`、`approval_tasks`。
3. 下单用单事务：`SELECT ... FOR UPDATE` 锁库存行 → 校验 → 扣减 → 写订单 → 写幂等键；重复 `Idempotency-Key` 直接返回首次结果。
4. Alembic 管理迁移；只读查询可接 Redis 缓存（短 TTL + 库存绕过缓存）。
5. 订单增加 `paid / refunded / partially_refunded` 状态机，退款金额独立字段与流水表。

**验收标准**：100 并发抢 1 件库存只成功 1 单；重启后数据完整；重复幂等键不重复扣库存；退款原因不再写进地址。

---

### 2.2 认证：Token 与口令

**当前实现**
- `backend/app/security/rbac.py:100-124`：自研 HMAC-SHA256 Token，payload 仅 `sub/name/role/exp`，无 `iss/aud/iat/jti`，无吊销、无 Refresh。
- `backend/app/domain/repository.py:63-67`：口令明文 `123456`，`authenticate()` 直接字符串比较。
- `backend/app/config.py:30`：`secret_key = "dev-secret-change-me"`。
- `backend/app/api/routes.py:44-55`：Token 缺失/无效/过期时**静默降级为 guest**，而 guest 拥有 `chat:use`、`product:read`（`rbac.py:20`）。
- `frontend/src/api/client.ts:16-24`：Token 存 `localStorage`。

**生产风险**：弱密钥可伪造 admin；口令泄漏即全量泄漏；已离职用户 Token 在有效期内仍可用；前端 XSS 可直接窃取 Token；无效 Token 被当访客继续调用 API，掩盖攻击行为。

**改造方案**
1. 接入企业 IdP / OIDC（Auth0、Keycloak、腾讯云身份等），FastAPI 用 JWKS 验签并校验 `iss/aud/exp/nbf`。
2. 口令若仍需保留，使用 Argon2id/bcrypt 加盐哈希；`authenticate()` 改为哈希比对 + 失败计数锁定。
3. 无效凭证统一返回 **401**；仅公开端点（health、login）允许匿名。前端收到 401 清凭证并跳登录。
4. Token 存 httpOnly + Secure + SameSite Cookie，或引入 BFF；保留 Bearer 仅用于服务间调用。
5. Refresh Token 轮换 + Redis 黑名单实现即时吊销；`user:manage` 禁用用户时同步失效会话。
6. 密钥放 KMS/Vault，启动时强校验：生产环境禁止默认密钥、禁止 `offline` 模型、禁止 `*` CORS。

**验收标准**：篡改/过期/错误 aud 的 Token 全部 401；禁用用户 5 秒内失效；镜像与代码库中无任何明文口令；XSS 场景无法读取会话凭证。

---

### 2.3 授权与租户隔离（含 MCP 身份透传）

**当前实现**
- `backend/app/security/rbac.py:19-25`：角色权限写死；`:72-75`：`admin`/`service` 可访问全部客户数据。
- `backend/app/api/routes.py:58-62`：`require(permission)` 只做角色判定。
- `backend/app/agents/tools.py:25-39`：HTTP 模式把 `Bearer token` 放进 MCP client headers，但 `backend/app/mcp/server.py` **没有任何解析 Token / 设置 ContextVar 的中间件**；工具内 `get_current_user()`（`mcp/tools.py` 多处）会拿到默认 guest，导致权限判断失真。
- `backend/app/security/rbac.py:87-89`：工具按名字过滤，但 LLM 可输出的 tool 名由模型决定，过滤只在装载时做一次。

**生产风险**：远程 MCP 模式下所有终端用户被当成 guest，要么功能不可用，要么绕过客户级隔离；客服角色天然可看全部订单，缺少工单/授权依据；无租户概念，无法做多商家 SaaS。

**改造方案**
1. 引入 `tenant_id` 与资源级策略（ABAC/ReBAC）：`can_access_customer(user, customer_id)` 增加租户与授权单校验。
2. MCP Server 增加认证中间件：解析 JWT → 建立请求级 `ContextVar`/session → 工具执行前二次鉴权；服务间用 mTLS，终端用户声明用短时 token 传递并对每个工具校验。
3. 工具过滤从"装载时"扩展为"执行时"：`wrap_tool_call` 中再次校验 `permission_for_tool(name)`，拒绝时写审计并返回结构化错误。
4. 高风险工具（`create_order`、`initiate_refund`、`resume_fulfillment`）加额度阈值与二次确认，必要时接人工审批工作流。

**验收标准**：MCP HTTP 模式下 customer A 查 B 的订单被拒并留审计；service 无有效工单时越权被拒；越权尝试可在审计表按 actor/resource 检索。

---

### 2.4 模型、意图路由与输出可靠性

**当前实现**
- `backend/app/llm/factory.py:25-182`：`RuleBasedChatModel` 用关键词表 `pick_tool()`，参数抽取大量默认值（`:71` 默认 `P001`、`:81/:83` 默认 `O1001`），回答由 `_format_tool_result()` 模板拼接。
- `backend/app/agents/supervisor.py:40-53`：`classify_route()` 同样是关键词规则。
- `get_model()`（factory.py:185-195）已预留 `ChatOpenAI` 入口，`temperature=0, streaming=True`，但缺 timeout/retry/fallback。
- `PIIMiddleware` 只覆盖 email 与手机号（`specialists.py:52-54`）。

**生产风险**：用户换个说法即无法识别；默认订单号/商品号会造成**答非所问甚至泄露他人数据假象**；无真实模型超时与降级，单次调用可能挂死 Worker。

**改造方案**
1. 生产配置 `ECOM_LLM_PROVIDER=openai`（或企业内模型网关），保留 `RuleBasedChatModel` 仅用于单测与离线演示。
2. 为 `ChatOpenAI` 配置 `timeout`、`max_retries`、并发上限；配置 `ModelFallbackMiddleware`（主模型 → 备模型 → 安全兜底回复）。
3. 建立**评测集**（不少于 100 条真实问法 + 20 条越权/注入攻击样本），指标：意图路由准确率、工具选择准确率、参数抽取准确率、幻觉率、越权拒绝率。每次 prompt/模型变更跑回归。
4. 输出校验：回答中出现的商品 id/订单 id/金额必须能在工具结果中溯源，否则触发重试或安全回复；身份与权限提示写入 system prompt（`context/engine.py` 已有"当前用户"段落）。
5. 意图路由可先用"规则优先 + LLM 兜底"，避免规则误判直接拒答。

**验收标准**：评测集意图准确率达标（建议 ≥90%）、越权样本 100% 拒绝、无虚构订单号、P95 端到端延迟满足 SLA。

---

### 2.5 会话历史与检查点

**当前实现**
- `backend/app/agents/supervisor.py:56-85`：`ConversationStore` 内存字典，12 轮滑窗。
- `backend/app/agents/supervisor.py:150` 与 `backend/app/workflows/fulfillment.py:103`：两处 `InMemorySaver`。
- `supervisor.py:167/184`：每次调用都给 `thread_id` 追加随机 8 位后缀，**checkpointer 实际没有复用同一会话的状态**，历史只靠 `ConversationStore` 维持。
- `fulfillment.py:127-138`：以客户端传入的 `thread_id` 作为唯一流程标识。

**生产风险**：多副本会话漂移、重启丢历史与待审批状态；用户可猜测 thread_id 恢复他人工作流；检查点无限增长无 TTL。

**改造方案**
1. `checkpointer` 换 `AsyncPostgresSaver`（或 Redis），`ConversationStore` 换 Redis（按 `tenant:user:thread` 命名，TTL 7 天）。
2. `thread_id` 由服务端生成并做归属绑定；`run_agent` 不再追加随机后缀，用稳定 thread + turn 序号。
3. `resume_fulfillment` 前校验 `thread_id → order_id → customer_id/tenant` 归属，且审批状态必须为 `awaiting_approval`。
4. 检查点与会话表设置保留期和清理任务；敏感内容入检查点前脱敏。

**验收标准**：任意副本接续同一会话；重启后待审批任务仍可恢复；伪造 thread_id 返回 403/404 且写审计。

---

### 2.6 人工审批（HITL）安全

**当前实现**
- `backend/app/workflows/fulfillment.py:25`：`APPROVAL_THRESHOLD = 500.0` 硬编码。
- `:54-63`：金额达阈值即 `interrupt()`，`Command(resume=...)` 继续。
- `backend/app/api/routes.py:195-200`：resume 接口只要求 `order:manage`，直接把客户端 `thread_id` 与 `approved` 传给图，**不校验审批人身份、不要求发起人与审批人分离、不记录审批依据**，且审计在调用前无条件写 `allow`。

**生产风险**：任何有 `order:manage` 的人可审批任意大额订单；自批自单；审批凭证缺失；重复 resume 导致状态混乱。

**改造方案**
1. 新增 `approval_tasks` 表：`thread_id / order_id / amount / requester / approver / status / expires_at / decision_reason`。
2. 阈值配置化（按品类/地区/客户等级），审批人角色与发起人做职责分离；大额二次复核。
3. resume 接口：校验任务存在、未过期、状态正确、审批人有权；写入审批人与理由后再推进图；重复请求返回原结果（幂等）。
4. 超时未审批自动拒绝并回滚库存；拒绝走补偿事务（Saga）归还库存与优惠券。

**验收标准**：自批被拒；过期任务不可 resume；重复 resume 不重复发货；审批记录可追溯到具体审批人。

---

### 2.7 MCP Server 生产化

**当前实现**
- `backend/app/mcp/server.py:15`：`FastMCP(... host="127.0.0.1", port=8001)`，无 TLS、无鉴权。
- `:18-19`：一次性注册全部 8 个工具，无工具级白名单。
- `agents/tools.py:28-36`：HTTP 模式仅透传 Bearer，服务端无消费逻辑（见 2.3）。

**改造方案**：Server 只部署在内网并置于 API 网关之后；强制 mTLS 或网关 OAuth2；终端用户身份声明逐请求传入并在工具内二次鉴权；工具按租户/角色动态注册；配置连接超时、重试、健康检查；保留 stdio 模式仅用于本地测试。

**验收标准**：未授权调用 MCP 端点返回 401/403；抓包无明文敏感参数；MCP 工具调用失败率与 P95 可观测。

---

### 2.8 业务正确性缺陷（非架构，但必须修）

| 位置 | 问题 | 修复 |
|---|---|---|
| `workflows/fulfillment.py:46` | `p.stock >= 0` 恒真，库存复核形同虚设 | 改为 `p.stock >= 需求数量`，并读取订单明细数量 |
| `workflows/fulfillment.py:51-52` | `reserve_stock` 只写文案，不真锁库存 | 落库存预占表/数据库行锁，超时释放 |
| `domain/repository.py:173-178` | 退款原因拼进 `address` | 拆 `refund_reason`、`refund_amount`、退款流水 |
| `domain/repository.py:129-153` | 下单无幂等、无支付状态 | 幂等键 + 支付状态机 + 价格快照 |
| `api/routes.py:168-179` | 退款无金额/状态校验、无风控 | 校验订单状态、金额上限、频率，写审计 |
| `workflows/fulfillment.py:76-83` | 取消/回滚都只改状态 | Saga 补偿：库存、优惠券、支付原路退回 |
| `agents/specialists.py:26-31` | `order` agent 有 `create_order` 但无库存工具之外的人工确认 | 高风险工具执行前二次确认 |

---

### 2.9 CORS 与调试接口

- `backend/app/main.py:22-26`：`allow_origins=["*"]` 且 `allow_credentials=True`，生产必须改为显式白名单同源域名，并限制 methods/headers。
- `get_settings().debug` 定义了但未使用；生产关闭 `/docs`、`/openapi.json` 或加鉴权。
- `/api/context/preview`（routes.py:223-233）与 `/api/rag/search`（:236-239）只用 `Depends(current_user)`，guest 即可访问；前者会回显工具清单与系统提示片段。生产应收紧为 `admin` 或仅非生产环境开启。
- `/api/graphs`（:204-206）同样对所有用户开放；如非敏感可保留，但建议至少登录后可访问。

---

## 3. P1：稳定运维与合规

### 3.1 可观测性

**当前**：`TraceCollector` 1000 条内存环形缓冲（`observability/tracer.py:60-81`）、`AuditLogger` 500 条（`security/audit.py:12-34`），且 Trace payload 记录工具入参与结果前 400 字符（`specialists.py:40-41`、`supervisor.py:117-119`），可能含手机号、地址、订单明细。

**改造**
- OpenTelemetry SDK + OTLP → Tempo/Jaeger；`trace_id` 从 API 入口贯穿 Supervisor、Agent、工具、MCP、工作流。
- 审计写入 append-only 表并同步到不可篡改存储，保留期 ≥180 天；禁止 `clear()` 在生产可用。
- Trace/Audit 落库前做字段级脱敏（`PIIMiddleware` 扩展到身份证、银行卡、详细地址）。
- 结构化 JSON 日志 + `request_id`；Prometheus 指标：路由分布、工具成功率、重试次数、Token 用量与成本、审批时长、SSE 断连率。
- 告警：工具失败率突增、LLM P95 超阈值、成本超预算、越权拒绝数异常。

**验收**：单请求可在链路系统完整回放；日志中检索不到明文手机号/地址；关键告警可在演练中触发。

### 3.2 API 稳定性

- 限流：按 user/IP/租户三维度（Redis 滑动窗口），聊天接口单独配额。
- 并发闸：每实例 `asyncio.Semaphore` 限制并发 LLM 调用，队列满返回 429 + 重试建议。
- 超时：LLM、MCP、RAG 检索均设 `asyncio.wait_for`；SSE 加心跳注释帧与断线重连，网关 `proxy_read_timeout` 配套调整。
- 熔断/降级：MCP 或模型连续失败时切到降级回复，避免级联雪崩。
- 幂等：`POST /orders`、`/orders/{id}/refund`、`/workflows/.../resume` 支持 `Idempotency-Key`。
- 输入约束：Pydantic 限制 `message` 长度、批量大小、`limit` 上界，防大 payload 打满内存。
- 统一错误码与 `request_id`，4xx/5xx 不泄漏堆栈。

### 3.3 上下文工程与提示安全

- `context/engine.py:17-19` 用 `len/1.5` 估算 token，真实模型偏差大；改用模型 tokenizer 精确计数。
- 预算分层：硬性规则 > 身份权限 > 工具 schema > RAG 证据 > 历史摘要 > 当前输入；工具多时按需加载 schema。
- `compact()`（:78-104）按消息硬截断，可能切断语义；改为按 token 边界 + 摘要中间件生成结构化摘要。
- 防提示注入：RAG 文档与工具返回标记为"不可信数据"，与指令区隔离；对"忽略上面指令"类输入做检测并记录审计。

### 3.4 RAG

- `rag/pipeline.py:11-28` 仅 8 条硬编码政策；`:73-76` 无命中时兜底返回前 3 条，**会把无关政策塞给模型造成误答**，生产必须删除或显式标记"未找到依据"。
- `rag/embeddings.py:28-47` 128 维哈希 n-gram 无语义能力；换 bge-m3 / text-embedding-3，向量库换 pgvector/Qdrant。
- 增加文档入库管线：解析 → 切片 → 去重 → 元数据（生效日期/版本/适用租户）→ 增量更新；检索加 rerank、权限过滤与引用溯源。
- 建立检索评测集（Hit@K、MRR）并纳入 CI 回归。

### 3.5 前端

- `frontend/src/api/client.ts:94-150` 的 `chatStream` 没有 `AbortController`，页面卸载/切会话不会中断连接；补取消、超时、重连与 `done` 事件丢失兜底。
- 全局 401 拦截、统一错误提示、失败重试；`?q=` 参数已有 encode，保持。
- 生产构建由 Nginx 静态托管并反代 `/api`（Vite proxy 仅开发用）；开启 Brotli/gzip、哈希资源长缓存、CSP、`X-Content-Type-Options`、`Referrer-Policy`。
- 管理页（角色切换登录）仅允许演示环境；生产删除快捷切换，接真实 IdP 登录回调。

### 3.6 配置、工程化与发布

- 新增 `ECOM_ENV=prod` 启动预检：拒绝默认 `secret_key`、`offline` 模型、`allow_origins=*`、`debug=true`。
- 所有密钥走 Secret Manager；`.env` 不进镜像；配置分层 dev/staging/prod。
- Dockerfile（多阶段构建、非 root 用户）+ Compose/K8s manifests；探针：liveness `/api/health`、readiness 增加 DB/Redis/LLM 依赖检查。
- 多 worker（`uvicorn --workers N` 或 Gunicorn），HPA 按并发/队列长度；优雅关闭等待在途 SSE。
- CI：lint → `vue-tsc` → pytest 79 例 → vitest → 安全扫描（依赖 CVE）→ 构建镜像 → staging smoke → 灰度发布。
- 增加并发/压力测试、安全测试（越权、注入、限流）、LLM 评测回归；现有 79+4 例是功能正确性基线，不足以支撑上线门禁。

### 3.7 合规

- PII 分级与脱敏规则扩展（身份证、银行卡、地址、邮箱、手机号）；数据保留期与删除权流程。
- 审计记录包含 actor、resource、决策、理由、时间、trace_id；不可删除。
- 与模型/向量服务厂商确认数据处理协议、数据不出境与不用于训练条款。

---

## 4. P2：效果与成本优化

- 语义缓存：相同/近似问题复用答案，但绕过所有写操作与个性化数据。
- 模型分级路由：简单查询走小模型，复杂多步走大模型；按 token 预算与 SLA 动态选择。
- 答案强制引用来源文档/工具结果，前端展示引用标记。
- 工具 schema 按需加载，减少 system prompt 体积。
- 成本看板：按租户/场景统计 token 与调用次数，设置预算告警。

---

## 5. 可以保留、不需要重写的设计

| 资产 | 位置 | 保留理由 |
|---|---|---|
| 工具单一真源 | `mcp/tools.py` 的 8 个函数同时供 FastMCP 与 LangChain 使用 | 换传输方式不需改业务逻辑 |
| 上下文快照 | `context/engine.py` 的 `ContextSnapshot` | 可解释性设计好，直接对接前端面板 |
| 中间件链 | `agents/specialists.py:45-56` | 摘要/重试/调用上限/PII/Trace 组合正确，只需调参 |
| Supervisor 图拓扑 | `agents/supervisor.py:137-150` | context→route→specialist→finalize 结构合理 |
| 履约工作流状态机 | `workflows/fulfillment.py:85-103` | 条件边与 HITL 设计正确，只需持久化与补偿 |
| API 契约与 SSE 事件 | `api/routes.py`、`frontend/src/api/client.ts` | 前端无需随后端存储/模型替换而重写 |
| 测试基线 | `backend/tests/`（79 例）+ `frontend/tests/`（4 例） | 改造过程中的回归保护网，先补接口再换实现 |

---

## 6. 生产目标架构（替换点示意）

```
浏览器 (httpOnly Cookie)
      │  HTTPS / CSP
      ▼
Nginx ──静态──> Vue3 dist
   └──/api──> FastAPI (多副本)
                │  JWT 校验 (JWKS)  ──> IdP
                │  限流/并发闸 ──────> Redis
                │
      ┌─────────┼──────────┬─────────────┐
      ▼         ▼          ▼             ▼
  Supervisor  Specialist  RAG Pipeline  OTel SDK
      │         │          │             │
      │    Model Gateway   Vector DB     │
      │    (timeout/fallback) (pgvector) │
      ▼         ▼                        ▼
 PostgresSaver / Redis         OTLP → 链路/指标/日志
      │
      ▼
 MCP Server (内网, mTLS, 身份透传) ──> PostgreSQL (事务/行锁/幂等)
      │
      ▼
 审批任务表 + 人工控制台 (职责分离/超时补偿)
```

---

## 7. 上线门禁 Checklist

上线前逐项打勾，任一 P0 未通过即禁止发布。

- [ ] 生产配置预检开启：非默认密钥、真实 LLM、CORS 白名单、debug 关闭
- [ ] PostgreSQL 迁移完成，重启与双副本数据一致性验证通过
- [ ] OIDC 登录、401 语义、Token 吊销、口令哈希验证通过
- [ ] MCP HTTP 模式身份透传验证通过，跨客户越权样本 100% 拒绝
- [ ] 意图/工具/参数评测集达标，幻觉样本通过率达标
- [ ] 检查点持久化：任意副本恢复会话与待审批流程成功
- [ ] 审批职责分离、幂等、超时补偿验证通过
- [ ] 库存并发压测无超卖，退款金额与流水正确
- [ ] Trace/Audit 落库且脱敏，PII 检索为 0
- [ ] 限流、超时、熔断、SSE 心跳压测通过
- [ ] RAG 无命中兜底已移除，召回评测达标
- [ ] 前端 SSE 可取消、401 跳转、CSP 生效、角色切换入口下线
- [ ] CI 全绿（单测 + 评测 + 安全扫描 + 构建），灰度发布预案就绪
- [ ] 数据保留期、删除权与厂商 DPA 完成法务确认

---

## 8. 建议的推进顺序

1. **第一批（数据与身份）**：Repository 接口抽象 + Postgres 迁移 + OIDC + 401 语义 + CORS 收口。完成后系统才"敢存真实数据"。
2. **第二批（智能与状态）**：真实 LLM + 评测集 + Redis/PostgresSaver + thread 归属 + 审批任务表 + 业务缺陷修复。完成后回答才"可信"。
3. **第三批（运维与合规）**：OTel + 审计落库脱敏 + 限流超时熔断 + 前端加固 + CI/CD + 容器与探针。完成后系统才"可运维"。
4. **第四批（效果与成本）**：RAG 升级 + 提示注入防护 + 语义缓存 + 成本看板。完成后系统才"好用且可控"。

每一批都应保持现有 API 契约不变，用已有 83 个测试用例作为回归基线；新增能力再补对应测试与评测样本。
