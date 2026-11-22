# 电商智能体（LangChain 1.5 + Vue 3）

一个可直接运行的全栈电商智能体示例：后端 Python 3 / FastAPI / **langchain 1.5.2** / LangGraph 1.2 / MCP，前端 Vue 3 + TypeScript + Vite。覆盖 MCP 工具、上下文工程、RAG、多智能体、工作流、可视化与稳定性（权限/审计/人工审批/降级）。

## 快速开始

### 1. 后端

```bash
python3 -m venv .venv
# Windows
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --reload --port 8000
# macOS / Linux
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8000
```

打开 `http://localhost:8000/docs` 查看 Swagger。默认使用**离线确定性模型**，无需任何 API Key。

可选：使用真实模型与独立 MCP 进程

```bash
cp backend/.env.example backend/.env
# 编辑：ECOM_LLM_PROVIDER=openai, ECOM_OPENAI_API_KEY=..., ECOM_MCP_MODE=http
cd backend && ../.venv/Scripts/python.exe -m app.mcp.server --transport streamable-http
```

### 2. 前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173，/api 自动代理到 :8000
```

### 3. 测试

```bash
cd backend && ../.venv/Scripts/python.exe -m pytest -q   # 79 passed（含真实 MCP 协议往返 + 39 例知识点专项）
cd frontend && npm test -- --run && npm run build
```

## 演示账号

| 用户名 | 密码 | 角色 |
|---|---|---|
| 张三 | 123456 | customer（U001） |
| 李四 | 123456 | customer（U002） |
| 王客服 | 123456 | service |
| 管理员 | 123456 | admin |

建议体验路径：对话页问"推荐降噪耳机" → "我的订单" → "O1003 想退货退款"；切李四问"O1001"看越权拦截；管理员在工作流页运行 O1001 并审批；管理页查看 Trace / Audit。

## 已实现能力

- **MCP TOOL**：8 个业务工具，`local` 进程内与 `streamable-http` 独立 FastMCP Server 双模式，`langchain-mcp-adapters` 转换。
- **上下文工程**：优先级装箱、字符预算、历史滑窗与压缩、可解释快照（前端可见）。
- **RAG**：中文 n-gram 确定性向量 + 词面重排，政策/商品知识 8 条，支持工具按需检索。
- **多智能体**：Supervisor 图 + 商品/订单/售后/通用四个 `create_agent` specialist，各自持有最小工具集。
- **工作流**：LangGraph 订单履约图，`interrupt()` 人工审批、`Command(resume=...)` 恢复、checkpointer 持久化。
- **可视化**：SSE 实时节点/工具/上下文事件；SVG 渲染两张图；Trace/Audit/权限矩阵管理页。
- **稳定性**：RBAC 四级角色、ContextVar 身份传递、工具内二次鉴权、HMAC Token、PII 中间件、工具重试、模型调用上限、上下文摘要、离线模型降级、审计与异常结构化处理。

## 目录

```
backend/app/         后端应用（domain / security / context / rag / llm / mcp / agents / workflows / observability / api）
backend/tests/       pytest 用例（8 个文件，79 例；含 39 例 LangChain 知识点专项）
frontend/src/        Vue3 应用（views / components / api / stores / router / types）
frontend/tests/      Vitest 用例
docs/                PRODUCT.md / ARCHITECTURE.md / API.md / TESTING.md / LANGCHAIN_TEST_CASES.md
```

详细文档见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)、[`docs/PRODUCT.md`](docs/PRODUCT.md)、[`docs/API.md`](docs/API.md)、[`docs/TESTING.md`](docs/TESTING.md)、[`docs/LANGCHAIN_TEST_CASES.md`](docs/LANGCHAIN_TEST_CASES.md)。
