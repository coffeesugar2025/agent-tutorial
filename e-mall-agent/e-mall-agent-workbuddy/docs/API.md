# API 文档

基址：`http://localhost:8000`，Swagger UI：`/docs`，OpenAPI：`/openapi.json`。
除 `/api/health`、`/api/graphs` 外均需 `Authorization: Bearer <token>`（未携带按 guest 处理）。

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

## 错误码

| 状态码 | 含义 |
|---|---|
| 400 | 业务校验失败（商品不存在、库存不足、数量非法） |
| 401 | 登录凭证错误 |
| 403 | 角色缺少权限或越权访问他人数据 |
| 404 | 商品/订单不存在 |

工具内部错误不会中断 Agent，而是以 JSON `{"error": "...", "permission_denied": true}` 回传，便于模型向用户解释。
