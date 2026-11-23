# API 契约（Python / Java 双后端必须逐字节一致）

> 这是两套后端的**唯一事实源**。任何一端改动接口，必须同步另一端与本文件。
> Base URL: `http://localhost:8000` (Python) / `http://localhost:8080` (Java)
> 统一前缀: `/api/v1`

---

## 0. 通用约定

### 0.1 响应信封

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "traceId": "9f2c1e..."
}
```

- `code = 0` 表示成功；非 0 表示业务错误（HTTP 状态码同时反映语义）。
- `traceId` 每次请求唯一，贯穿日志与 agent_trace。

### 0.2 分页

```json
{ "items": [], "total": 0, "page": 1, "size": 20 }
```

### 0.3 错误码

| code | HTTP | 含义 |
|---|---|---|
| 0 | 200 | 成功 |
| 40001 | 400 | 参数校验失败 |
| 40100 | 401 | 未认证 / token 失效 |
| 40300 | 403 | 无权限 |
| 40400 | 404 | 资源不存在 |
| 40900 | 409 | 状态冲突（如重复审批） |
| 42900 | 429 | 触发限流 |
| 50000 | 500 | 服务内部错误 |
| 50300 | 503 | 模型/依赖降级中 |
| 50400 | 504 | 上游超时 |

### 0.4 认证

除 `POST /auth/login`、`GET /health`、`GET /metrics` 外，全部要求：

```
Authorization: Bearer <jwt>
```

JWT payload: `{"sub": "<userId>", "username": "...", "roles": ["USER"], "exp": ...}`

### 0.5 枚举

- `agentType`: `SUPERVISOR` | `SHOPPING` | `SERVICE` | `OPS`
- `risk`: `READ` | `WRITE` | `IRREVERSIBLE`
- `messageRole`: `user` | `assistant` | `system` | `tool`
- `docType`: `POLICY` | `MANUAL` | `FAQ` | `PRODUCT_DOC`
- `visibility`: `PUBLIC` | `INTERNAL` | `ADMIN`
- `orderStatus`: `CREATED` | `PAID` | `SHIPPED` | `DELIVERED` | `FINISHED` | `CANCELLED` | `REFUNDING` | `REFUNDED`
- `approvalStatus`: `PENDING` | `APPROVED` | `REJECTED` | `EXPIRED`

---

## 1. 认证

### POST /api/v1/auth/login
```json
// req
{ "username": "alice", "password": "Passw0rd!" }
// data
{
  "token": "eyJ...",
  "expiresIn": 86400,
  "user": { "id": 1, "username": "alice", "displayName": "Alice", "roles": ["USER"] }
}
```

### GET /api/v1/auth/me
`data`: 同 `user` 对象。

---

## 2. 会话与对话

### POST /api/v1/chat/sessions
```json
// req
{ "title": "可选，缺省自动生成" }
// data  SessionVO
{
  "id": 1, "title": "新会话", "agentType": "SUPERVISOR",
  "status": "ACTIVE", "lastMessageAt": "2026-11-23T10:00:00+08:00",
  "createdAt": "..."
}
```

### GET /api/v1/chat/sessions
`data`: `SessionVO[]`（按 lastMessageAt 倒序，最多 50 条）

### GET /api/v1/chat/sessions/{id}
`data`: `SessionVO`

### DELETE /api/v1/chat/sessions/{id}
`data`: `null`

### GET /api/v1/chat/sessions/{id}/messages?limit=50
```json
// data  MessageVO[]
[
  {
    "id": 10, "role": "assistant", "content": "推荐这三款…",
    "agentType": "SHOPPING",
    "toolCalls": [{ "callId": "c1", "name": "search_products", "args": {}, "ok": true, "summary": "命中 3 件" }],
    "citations": [{ "docId": 2, "chunkId": 88, "title": "7天无理由退货政策", "snippet": "…", "score": 0.87 }],
    "tokenIn": 1200, "tokenOut": 300, "costCents": 2,
    "createdAt": "..."
  }
]
```

### POST /api/v1/chat/stream  ★核心接口
`Content-Type: application/json`，响应 `text/event-stream`。

```json
{ "sessionId": 1, "message": "帮我找 5000 以内的拍照手机", "clientMsgId": "uuid-optional" }
```

**SSE 事件序列（严格按此顺序，`event:` 行 + `data:` 行 + 空行）：**

| event | data | 说明 |
|---|---|---|
| `meta` | `{"traceId":"...","messageId":0,"sessionId":1}` | 必发，第一个 |
| `agent` | `{"agentType":"SHOPPING","reason":"商品导购意图"}` | 路由结果，可多次 |
| `delta` | `{"text":"片段"}` | 增量正文，可多次 |
| `tool_call` | `{"callId":"c1","name":"search_products","args":{...},"risk":"READ"}` | 工具开始 |
| `tool_result` | `{"callId":"c1","name":"search_products","ok":true,"summary":"命中 3 件","latencyMs":120}` | 工具结束 |
| `citation` | `{"docId":2,"chunkId":88,"title":"...","snippet":"...","score":0.87}` | 可多次 |
| `approval` | `{"approvalId":7,"title":"退款审批","detail":{...},"risk":"IRREVERSIBLE","expiresAt":"..."}` | 需人工，流会在此结束 |
| `usage` | `{"promptTokens":1200,"completionTokens":300,"costCents":2,"model":"deepseek-chat"}` | 结束前统计 |
| `done` | `{"messageId":10,"finishReason":"stop"}` | 正常结束；`finishReason`: `stop`\|`interrupted`\|`approval_required`\|`max_steps`\|`error` |
| `error` | `{"code":50300,"message":"模型降级中"}` | 异常结束，不再发 done |

心跳：空闲时每 15s 发送 `: ping` 注释行。

### POST /api/v1/chat/sessions/{id}/interrupt
`data`: `{"interrupted": true}`

### GET /api/v1/chat/approvals?status=PENDING
```json
// data  ApprovalVO[]
[{
  "id": 7, "sessionId": 1, "actionType": "CREATE_REFUND",
  "title": "退款审批", "detail": {"orderNo":"SO2026...","amount":3999},
  "risk": "IRREVERSIBLE", "status": "PENDING",
  "createdAt": "...", "expiresAt": "..."
}]
```

### POST /api/v1/chat/approvals/{approvalId}
```json
// req
{ "decision": "APPROVE", "comment": "同意" }   // APPROVE | REJECT
// data
{ "id": 7, "status": "APPROVED", "result": { "refundNo": "RF2026..." } }
```

---

## 3. 商品

### GET /api/v1/products?keyword=&categoryId=&minPrice=&maxPrice=&page=1&size=20
`data`: 分页的 `ProductVO`

```json
{
  "id": 1, "sku": "PH-001", "title": "...", "subtitle": "...",
  "brand": "Apple", "categoryId": 3, "categoryName": "手机",
  "price": 4999.00, "originalPrice": 5499.00, "stock": 12,
  "rating": 4.8, "sales": 3200, "imageUrl": "...",
  "attrs": {"color":"黑"}, "status": 1
}
```

### GET /api/v1/products/{sku}
`data`: `ProductVO`（含 `description`）

### POST /api/v1/products/search
```json
// req
{ "query": "拍照好的手机", "topK": 5, "maxPrice": 5000, "brands": ["Apple"] }
// data
{ "items": [{ "sku": "PH-001", "title": "...", "price": 4999.0, "score": 0.91, "reason": "..." }], "strategy": "hybrid" }
```

---

## 4. 订单

### GET /api/v1/orders?status=&page=1&size=20
`data`: 分页的 `OrderVO`（仅当前登录用户）

```json
{
  "id": 1, "orderNo": "SO202611230001", "status": "SHIPPED",
  "totalAmount": 4999.00, "payAmount": 4999.00,
  "receiverName": "张三", "receiverPhone": "138****8888",
  "createdAt": "...",
  "items": [{ "sku": "PH-001", "title": "...", "price": 4999.0, "quantity": 1 }]
}
```

### GET /api/v1/orders/{orderNo}
`data`: `OrderVO`

### GET /api/v1/orders/{orderNo}/logistics
```json
// data
{ "company": "顺丰", "trackingNo": "SF123", "status": "IN_TRANSIT",
  "latestEvent": "已到达上海分拣中心",
  "events": [{ "time": "...", "desc": "..." }] }
```

---

## 5. 知识库（ADMIN / OPS）

### POST /api/v1/knowledge/documents  (multipart/form-data)
字段：`file`（必填，.md/.txt/.pdf/.docx）、`title`、`docType`、`visibility`
```json
// data
{ "documentId": 5, "jobId": 9, "status": "QUEUED" }
```
索引为异步任务（RabbitMQ），立即返回。

### GET /api/v1/knowledge/documents?docType=&status=
```json
// data
[{ "id":5,"title":"7天无理由退货政策","docType":"POLICY","visibility":"PUBLIC",
   "status":"READY","version":1,"chunkCount":12,"createdAt":"..." }]
```

### DELETE /api/v1/knowledge/documents/{id}
软删除 + 异步清理 Milvus 向量。`data`: `{"jobId": 10}`

### POST /api/v1/knowledge/documents/{id}/reindex
`data`: `{"jobId": 11}`

### GET /api/v1/knowledge/jobs/{jobId}
```json
// data
{ "id":9,"documentId":5,"jobType":"INDEX","status":"RUNNING","progress":60,"error":null }
```

### POST /api/v1/knowledge/search  ★检索调试
```json
// req
{ "query":"退货运费谁承担", "topK":5, "docTypes":["POLICY"], "mode":"hybrid" }
// data
{
  "items":[{
    "chunkId":88,"documentId":2,"title":"7天无理由退货政策",
    "content":"...","score":0.87,
    "denseScore":0.83,"sparseScore":0.91,"rerankScore":0.87,
    "route":"dense+sparse"
  }],
  "debug":{"denseTopK":20,"sparseTopK":20,"rerankTopN":5,"latencyMs":86}
}
```

---

## 6. 运营与可观测（ADMIN）

### GET /api/v1/admin/overview?days=7
```json
{
  "totalSessions": 120, "totalMessages": 3400,
  "successRate": 0.93, "avgLatencyMs": 2400, "p95LatencyMs": 5200,
  "totalCostCents": 12345, "costPerSuccessCents": 4.1,
  "approvalPending": 2, "toolErrorRate": 0.02,
  "topTools": [{ "name":"search_products", "count": 320 }],
  "trend": [{ "date":"2026-11-17", "sessions": 12, "costCents": 800 }]
}
```

### GET /api/v1/admin/traces?sessionId=&status=&limit=20
`data`: `TraceVO[]`

### GET /api/v1/admin/traces/{traceId}  ★可重放
```json
{
  "trace": { "traceId":"...", "sessionId":1, "agentType":"SHOPPING",
             "status":"SUCCESS", "totalLatencyMs":2400, "totalCostCents":3, "stepCount":4 },
  "spans": [{ "spanId":"s1","parentSpanId":null,"name":"supervisor.route","spanType":"AGENT",
              "seq":1,"input":{},"output":{},"latencyMs":300,"status":"OK" }],
  "replayable": true
}
```

### GET /api/v1/admin/costs?days=7
```json
{ "total": 12345, "byModel":[{"model":"deepseek-chat","calls":120,"costCents":900}],
  "byProvider":[{"provider":"deepseek","costCents":900}], "daily":[...] }
```

### GET /api/v1/admin/models
```json
[{ "provider":"deepseek","model":"deepseek-chat","role":"primary",
   "healthy":true,"circuit":"CLOSED","avgLatencyMs":1800,"calls":120 }]
```

### POST /api/v1/admin/evals/run
```json
{ "suite": "shopping", "repeat": 3 }   // repeat 用于 pass^k
// data: { "runId": 1, "status": "RUNNING" }
```

### GET /api/v1/admin/evals/runs
### GET /api/v1/admin/evals/runs/{id}
```json
{
  "id":1,"suite":"shopping","status":"SUCCESS","total":20,"passed":18,
  "passRate":0.9,"passK":0.78,"avgCostCents":3,"avgLatencyMs":2500,
  "cases":[{"caseId":"s-001","question":"...","expected":"...","actual":"...","passed":true,"score":0.9}]
}
```

---

## 7. 系统

### GET /health
```json
{ "status":"UP", "components":{"mysql":"UP","redis":"UP","rabbitmq":"UP","milvus":"UP"} }
```
任一组件 DOWN 时 `status` 为 `DEGRADED`，HTTP 仍 200（供 k8s 存活探针区分）。

### GET /metrics  (Prometheus text format)
指标前缀 `ecom_agent_`：`requests_total`、`llm_calls_total`、`llm_tokens_total`、`llm_cost_cents_total`、`tool_calls_total`、`agent_step_seconds`、`approval_pending`。

### GET /api/v1/meta/capabilities
```json
{ "backend":"python", "version":"1.0.0",
  "features":{"mcp":true,"skills":true,"codeMode":true,"text2sql":true,"hybridRag":true},
  "llm":{"primary":"deepseek-chat","fallbacks":["qwen-max","qwen-turbo"]} }
```
前端据此显示/隐藏实验性入口。

---

## 8. 内部事件（RabbitMQ）

| Exchange | Routing Key | Payload |
|---|---|---|
| `ecom.agent` (topic) | `knowledge.index` | `{"documentId":5,"jobId":9}` |
| `ecom.agent` | `knowledge.delete` | `{"documentId":5,"jobId":10}` |
| `ecom.agent` | `session.summarize` | `{"sessionId":1,"upToMessageId":80}` |
| `ecom.agent` | `refund.execute` | `{"refundId":3,"approvalId":7}` |
| `ecom.agent` | `eval.batch` | `{"runId":1,"suite":"shopping"}` |

死信：`ecom.agent.dlx`，3 次重试后落 `async_task.status='DEAD'`。
