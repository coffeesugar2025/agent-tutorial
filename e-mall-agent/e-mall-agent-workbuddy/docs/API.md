# API 文档

基址（Python 后端）：`http://localhost:8000`，Swagger UI：`/docs`，OpenAPI：`/openapi.json`。
基址（Java 后端）：`http://localhost:8080`。**两套后端共用 `/api` 契约与前端**，切换只换 baseURL（前端系统管理页可切换，或环境变量 `VITE_API_BASE_URL` / nginx `UPSTREAM_BACKEND`）。
除 `/api/health`、`/api/graphs`、`/api/infra/health` 外均需 `Authorization: Bearer <token>`（未携带按 guest 处理）。
注意：两套后端的 token 不通用，切换引擎后需重新登录。

## 认证

### POST /api/auth/login
```json
{ "username": "张三", "password": "123456" }
```
响应：
```json
{ "token": "...", "user_id": "U001", "role": "customer",
  "permissions": ["chat:use", "order:create", "order:read", "order:refund", "product:read"] }
```

### GET /api/auth/me
返回 `{id, name, role, permissions}`。

## 对话

### POST /api/chat
```json
{ "message": "推荐降噪耳机", "thread_id": "default" }
```
响应：
```json
{ "answer": "为你找到 1 件相关商品：\n- P001 无线降噪耳机 Pro ¥899.0，库存 12",
  "route": "shopping", "trace_id": "default",
  "context": { "sections": [...], "total_chars": 651, "kept_messages": 0 } }
```

### POST /api/chat/stream
`Content-Type: text/event-stream`。事件帧格式 `data: {json}\n\n`：

| event | data | 说明 |
|---|---|---|
| `node` | `"context"` / `"route"` / agent 名 / `"finalize"` | 图节点流转 |
| `context` | ContextSnapshot | 上下文装箱快照 |
| `route` | `"shopping"` / `"order"` / `"support"` / `"general"` | 意图路由 |
| `tool` | `{name, content}` | 工具调用结果（截断 600 字符） |
| `token` | 字符串片段 | 回答流式分片 |
| `done` | 完整回答 | 结束帧 |

## 商品与订单

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | `/api/products?query=&category=` | 商品搜索/列表 | product:read |
| GET | `/api/products/{id}` | 商品详情 | product:read |
| GET | `/api/orders?customer_id=` | 订单列表（默认当前用户） | order:read + 归属校验 |
| POST | `/api/orders` | 下单 `{"items":[{"product_id":"P008","quantity":2}]}` | order:create |
| GET | `/api/orders/{id}` | 订单详情 | order:read + 归属校验 |
| POST | `/api/orders/{id}/refund` | 退款 `{"reason":"不想要了"}` | order:refund + 归属校验 |

## 工作流

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/workflows/fulfillment/run` | `{"order_id":"O1001","thread_id":"wf-1"}`；≥¥500 返回 `status: awaiting_approval` + `interrupt` |
| POST | `/api/workflows/fulfillment/resume` | `{"thread_id":"wf-1","approved":true}`；返回最终状态与 steps |

## 可观测 / 上下文 / 知识库

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | `/api/graphs` | 两张图的节点/边元数据（供可视化） | 登录即可 |
| GET | `/api/traces?limit=50&trace_id=` | 执行轨迹 | trace:read |
| GET | `/api/audit?limit=50&decision=deny` | 审计日志 | audit:read |
| GET | `/api/context/preview?message=` | 上下文装箱预览与消息角色 | 登录即可 |
| GET | `/api/rag/search?q=` | 知识库检索结果 | 登录即可 |
| GET | `/api/health` | 健康检查（含 llm_provider / mcp_mode） | 公开 |

## 扩展能力（/api/capabilities）

| 方法 | 路径 | 请求 | 响应要点 | 权限 |
|---|---|---|---|---|
| POST | `/capabilities/plan` | `{"goal":"查询P001库存并下单1件","mode":"plan_solve"}` | `answer` / `trace` / `terminated_reason`；`mode` 支持 `react`、`plan_solve` | chat:use |
| POST | `/capabilities/rag/hybrid` | `{"query":"退款政策","top_k":3,"mode":"hybrid"}` | `count` / `results`（含 RRF 与双通道来源明细）/ `context`；`mode` 支持 `hybrid`、`bm25`、`vector` | product:read |
| GET | `/capabilities/memory` | `?thread_id=t1&query=耳机` | `working` / `episodes` / `user_summary` / `injected_context` / `token_estimate` | chat:use |
| POST | `/capabilities/memory` | `{"thread_id":"t1","user_input":"...","assistant_output":"...","preference":{"name":"color","value":"黑"},"fact":{"content":"...","source":"user"}}` | 写入条目 | chat:use |
| DELETE | `/capabilities/memory/{user_id}` | — | 按用户彻底删除三层记忆 | audit:read |
| POST | `/capabilities/sandbox` | `{"code":"print(6*7)","mode":"plain"}` | `ok` / `value` / `stdout` / `error` / `duration_ms`；`mode` 支持 `plain`、`code_mode` | chat:use |

`code_mode` 会把当前用户可用的工具包装成 Python 命名空间，模型生成的代码只能调用这些工具且在 AST 校验后的受限环境中执行。

## 基础设施（/api/infra，Python 后端）

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | `/api/infra/health` | MySQL / Redis / RabbitMQ / Milvus / LLM 状态聚合，每项含 `configured`/`active`/`backend`/`detail` | 公开 |
| GET | `/api/infra/providers` | 多模型提供方清单与默认项（deepseek / qwen / offline） | chat:use |
| POST | `/api/infra/events` | 手动发布领域事件 `{"topic":"order.created","payload":{...}}` | user:manage |
| GET | `/api/infra/cache/{key}` | 读取缓存值 | trace:read |
| POST | `/api/infra/cache` | 写入缓存 `{"key":"k","value":"v","ttl":60}` | trace:read |

## 前沿能力（/api/frontier，Python 后端，25 端点）

| 分组 | 路径示例 | 覆盖能力 |
|---|---|---|
| 安全 | `POST /api/frontier/security/scan`、`/moderate`、`/tools` | 注入扫描、越狱/输出审核、工具投毒防护 |
| 规划 | `POST /api/frontier/reflection`、`/orchestration` | 反思自纠错、5 类编排模式 |
| Agent 通信 | `GET /api/frontier/a2a/cards`、`POST /api/frontier/a2a/delegate` | Agent Card 注册与任务委派 |
| RAG | `POST /api/frontier/rag/rewrite`、`/ragas`、`/advanced`、`/acl`、`/cache` | 查询改写、RAGAS、高级范式、权限检索、语义缓存 |
| LLM | `POST /api/frontier/llm/tokenize`、`/structured`、`/model/select` | Token 计数、结构化输出、模型选型 |
| 评测 | `POST /api/frontier/eval/judge`、`/experiment` | LLM-as-Judge、A/B 显著性 |
| 其他 | `POST /api/frontier/prompts/render`、`/flags` | Prompt 版本、Feature Flag |

详见 Swagger `/docs` 与 [`CAPABILITY_QUICKSTART.md`](CAPABILITY_QUICKSTART.md)。

## 错误码

| 状态码 | 含义 |
|---|---|
| 400 | 业务校验失败（商品不存在、库存不足、数量非法） |
| 401 | 登录凭证错误 |
| 403 | 角色缺少权限或越权访问他人数据 |
| 404 | 商品/订单不存在 |

工具内部错误不会中断 Agent，而是以 JSON `{"error": "...", "permission_denied": true}` 回传，便于模型向用户解释。
