# 测试用例与验证

> **双后端版测试体系（单元/集成/产品/E2E/一致性/可靠性 + Java + 前端）见 [`TEST_SUITE.md`](TEST_SUITE.md)**，本文件保留 Python 单栈的历史用例明细。

## 1. 运行方式

```bash
# 后端（在仓库根目录创建 venv 后）
cd backend
../.venv/Scripts/python.exe -m pytest -q        # Windows
# 或 .venv/bin/python -m pytest -q              # macOS/Linux

# 前端
cd frontend
npm install
npm test -- --run
npm run build
```

后端测试结果：基线 **248 passed**，经能力补齐后 **422 passed**（pytest 8.x / Python 3.12），另新增 `test_infra.py`（基础设施适配器）与 `test_cross_backend.py`（双后端一致性，两后端都在线时执行，否则跳过）。其中包含一次真实的 MCP stdio 协议往返测试。按 LangChain 知识点组织的专项用例 39 例见 `docs/LANGCHAIN_TEST_CASES.md`；能力图谱补齐专项 169 例见下表后半部分，逐项覆盖状态见 `docs/CAPABILITY_MATRIX.md`。前端测试与构建命令见 `TEST_SUITE.md`。

## 2. 后端用例清单

| 文件 | 用例 | 覆盖点 |
|---|---|---|
| `test_rbac.py` | 5 | 角色权限矩阵、guest 拒绝、工具按角色过滤、Token 签发/篡改检测、客户数据隔离（含工具内二次鉴权） |
| `test_context.py` | 4 | 优先级装箱、用户身份注入、滑窗丢弃旧轮、超长轮压缩标记、token 估算与文档格式化 |
| `test_rag.py` | 4 | 哈希向量确定性、中文 n-gram 分词、政策召回排序、上下文格式化 |
| `test_tools.py` | 6 | MCP Server 工具注册、商品/库存查询、下单扣库存+审计、跨客户拒绝+退款、RAG 工具、真实 MCP stdio `ListTools`/`CallTool` 往返 |
| `test_agents.py` | 7 | 意图分类、离线模型工具选择、商品导购、订单隔离、售后退款、SSE 事件序列、Trace 记录 |
| `test_workflow.py` | 4 | 大额中断→恢复完成、拒绝→取消、小额跳过审批、订单不存在分支 |
| `test_api.py` | 10 | 健康检查/OpenAPI、登录成功失败、guest 403、客户订单隔离、客服跨客户、对话+SSE、商品下单退款、工作流 API、上下文/RAG/图元数据 |
| `test_langchain_knowledge.py` | 39 | 按 11 个 LangChain 知识点组织：消息/模型、LCEL、Tools、create_agent、Middleware、LangGraph 状态图、HITL、MCP、RAG、上下文工程、稳定性。清单见 `docs/LANGCHAIN_TEST_CASES.md` |
| `test_planning.py` | 15 | 规划拆步与依赖、ReAct 多轮工具轨迹、最大步数终止、Plan-and-Solve 失败降级 |
| `test_reliability.py` | 26 | 重试退避、超时降级、Fallback 链顺序、幂等并发只执行一次、终止条件各分支 |
| `test_memory.py` | 21 | 会话/情景/用户三层记忆、跨用户隔离、预算淘汰、TTL、合规删除、并发写入 |
| `test_rag_advanced.py` | 40 | 三种切片、BM25 中文召回、RRF 融合、重排、无命中返回空、版本/增量/撤销、引用质量、Text2SQL 注入防护、Cypher、图谱检索 |
| `test_sandbox_resume.py` | 40 | AST 安全校验、危险 import 拦截、Code Mode 工具编排、Harness、Checkpoint 断点恢复、幂等步骤 |
| `test_eval.py` | 27 | Counter/Gauge/Histogram P95、回调埋点、Golden Case 导入导出、规则评分、批量评测、Trace Replay、回归门禁 |

## 3. 关键断言示例

- `test_customer_order_scope`：张三访问 `?customer_id=U002` 返回 403，访问 `O1002` 返回 403。
- `test_tool_enforces_customer_scope`：即使绕过 API 直接调用 `list_orders("U002")`，也返回 `permission_denied` 并写审计。
- `test_large_order_interrupts_then_completes`：`run_fulfillment("O1001")` → `awaiting_approval`；`resume(..., True)` → `completed` 且订单状态 `shipped`。
- `test_stream_emits_node_route_and_answer`：SSE 事件包含 `node/route/token/done`，done 中含真实订单号。
- `test_hash_embeddings_are_deterministic`：同一文本两次 embedding 完全相等且 L2 范数为 1。

## 4. 前端用例

- `tests/api.spec.ts`：mock `fetch`，验证登录请求 URL/方法/Token 写入，以及 `chatStream` 将 SSE 帧解析为回调事件。
- `tests/graph.spec.ts`：挂载 `GraphFlow`，断言节点标签与边渲染。
- `tests/capability.spec.ts`：mock `fetch`，验证规划端点请求体与 Token、混合检索 RRF 来源明细解析、沙箱结果解析。
- 实测结果：**3 个测试文件、7 个用例全部通过**；`npm run build`（`vue-tsc --noEmit` + Vite）成功，产出 `dist/`。

## 5. 手动验收清单

- [ ] 用张三登录，问"推荐降噪耳机"得到 P001 与真实库存。
- [ ] 问"我的订单"只看到 U001 的两笔订单。
- [ ] 问"O1003 想退货退款"后订单状态变为 `refund_requested`。
- [ ] 用李四登录问"O1001"被拒绝，管理页审计出现 `deny` 记录。
- [ ] 管理员运行 O1001 履约 → 出现审批中断 → 批准后订单 `shipped`。
- [ ] 对话页上下文侧栏展示 4 个区块及字符数。
- [ ] 工作流页两张 SVG 图正常显示节点与连线。
- [ ] 能力实验室：Plan-and-Solve 执行"查询P001库存并下单1件"，出现 2 步轨迹。
- [ ] 能力实验室：混合检索对比 hybrid/bm25/vector，看到 RRF 与来源明细。
- [ ] 能力实验室：代码沙箱 `import os` 被安全策略拦截。
- [ ] 能力实验室：Text2SQL 生成受限 SELECT；运行评测看到通过率与 P95。
- [ ] 对话一次后刷新指标页，agent_runs 与 tool_calls 计数增加。
