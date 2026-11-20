# HR Agent 从零到生产 · LangChain 版（可运行示例工程）

> 配套教程：[`docs/HR_Agent_从零到生产.md`](docs/HR_Agent_从零到生产.md)
> 技术栈：**Python 3.12 + LangChain / LangGraph + FastAPI + Vue 3 + Vite**，模型默认走 **本地 Ollama（零成本）**
> 组织方式：**16 个独立 Demo**，每章可单独 CLI 运行、单独删除；第 16 章把前 15 章串成一张 LangGraph 全链路状态图

---

## 1. 这一版和「手写版」的区别

**教程从第一章起就用 LangChain / LangGraph 讲，不是最后一章补一个框架 Demo。**
手写循环、手写重试器、手写 Tracer 全部退出教学主线，换成框架原生组件：

| 能力 | 本工程用的框架 API |
| --- | --- |
| 模型 | `BaseChatModel` → `langchain_ollama.ChatOllama` / `langchain_community.OllamaEmbeddings` |
| 编排 | **LCEL**：`ChatPromptTemplate \| ChatModel \| OutputParser`、`RunnableLambda` / `RunnablePassthrough` |
| 循环与流程 | **LangGraph**：`StateGraph`、`add_messages`、`add_conditional_edges`、`recursion_limit` |
| 工具 | `@tool` → `StructuredTool` → `bind_tools` → `ToolNode` → `ToolMessage` |
| 规划 | `PydanticOutputParser` / `with_structured_output` |
| 检索 | `Document` → `Embeddings` → `InMemoryVectorStore.as_retriever()` → 自定义 `BaseRetriever`（三路 RRF） |
| 人工审批 | `langgraph.types.interrupt` + `Command(resume=...)` + `MemorySaver` |
| 记忆 | `InMemoryStore`（长期/用户）+ `checkpointer`（会话）+ `add_messages` |
| 上下文 | `langchain_core.messages.trim_messages` |
| MCP | `langchain-mcp-adapters.MultiServerMCPClient` → 真实 stdio JSON-RPC Server |
| 可靠性 | `Runnable.with_retry()` / `Runnable.with_fallbacks()` + 幂等键 + 熔断 |
| 可观测 | `langchain_core.callbacks.BaseCallbackHandler` → 统一 Trace / Metrics |

底层只保留**业务数据源**（SQLite 假 HCM、组织图、BM25 与 RRF 的教学实现），它们不是 Agent 编排，属于「被工具读取的系统」。

## 2. 能跑什么

- 「我今年还剩几天年假」→ `bind_tools` + `ToolNode` 查 HCM，答案带 `source` 与 `as_of`
- 「公司有几天婚假」「试用期辞退流程」→ `InMemoryVectorStore` + 三路混合 `BaseRetriever`，带版本与 `[n]` 引用
- 「帮我给陈明办入职」→ `StateGraph` + `interrupt` 挂起主管审批，控制台点按钮用 `Command(resume)` 从 checkpoint 续跑
- 「产品部上月平均加班多久」→ `Text2SQL` 走 `@tool` 只读网关；「谁和张三同项目」→ 图谱检索
- 「这批简历谁最匹配」→ LangGraph supervisor 四角色 + 共享黑板 + 合规一票否决
- 第 16 章 → 一张图跑通「路由 → 上下文装配 → 工具循环 / RAG / 状态机 → 引用校验 → 长期记忆 → Trace」

## 3. 两种运行模式（小白友好）

| 模式 | 触发条件 | 效果 |
| --- | --- | --- |
| **离线演示模式** | 没装 Ollama，或 `HR_AGENT_MOCK=1` | `TeachingChatModel`（继承 `BaseChatModel`）返回确定性应答，**LCEL、bind_tools、ToolNode、interrupt、回调链全部真实执行**，零配置零成本 |
| **真实模型模式** | 装好 Ollama 并拉了模型 | 一行配置切到 `ChatOllama`，链路代码一行不用改 |

> 离线模型是**框架内的合法替身**，不是绕过框架。生产必须删掉它，只留真实模型 + 输出校验。

## 4. 五分钟跑起来

```bash
cd hr-agent-course
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 方式 A：直接跑某一章（不需要起服务）
python demos/ch01_loop/demo.py
python demos/ch16_langchain_fullchain/demo.py '{"scenario":"onboarding"}'

# 方式 B：起 API 服务
uvicorn backend.main:app --reload --port 8000     # http://127.0.0.1:8000/docs
```

前端（Node 20+）：

```bash
cd frontend && npm install && npm run dev          # http://127.0.0.1:5173
```

接真实模型（可选）：

```bash
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
ollama serve
cp .env.example .env
```

## 5. 目录结构

```
hr-agent-course/
├── docs/HR_Agent_从零到生产.md     ← 教程正文（全程 LangChain，循序渐进）
├── README.md
├── requirements.txt                ← LangChain 生态为必装核心依赖
├── requirements-langchain.txt      ← 版本约束说明
├── common/
│   ├── context.py                  LangChain 运行上下文：chat_model() / embeddings() / Trace / Metrics
│   ├── lc_models.py                BaseChatModel / Embeddings 的可切换实现
│   ├── lc_tools.py                 @tool 工具集 + 真实 MCP 桥接
│   ├── lc_retrieval.py             自定义 BaseRetriever：向量 + BM25 + 图谱 RRF
│   ├── lc_callbacks.py             BaseCallbackHandler → 统一 Trace
│   ├── lc_kit.py                   15 章共用构建块（LCEL / trim / checkpointer / Store）
│   ├── lc_academy.py               第 1–15 章的独立实现
│   ├── lc_graph.py                 第 16 章全链路 StateGraph
│   ├── hr_data.py                  假 HR 数据库 + 组织图 + 业务数据
│   ├── bm25.py / graph.py / vectorstore.py   教学用检索算法（非编排层）
│   └── reliability.py / observability.py / schema.py
├── demos/chNN_xxx/demo.py         ← 16 个独立入口（薄封装，统一契约）
├── backend/main.py                ← FastAPI：16 章 API + 双通道 HITL 恢复
├── frontend/                      ← Vue3 控制台：Trace / 状态机 / 审批 / 指标
└── data/handbook/                 ← 4 篇 HR 制度文档（RAG 语料）
```

## 6. 统一 Demo 契约

```python
def run(payload: dict | None = None, ctx: Context | None = None) -> dict:
    return {
        "chapter": "...", "mode": "mock | ollama", "trace_id": "...",
        "answer": "给用户的最终回答",
        "steps":  [{"type": "thought|tool|llm|retrieve|hitl|state|error", "content": "...", "meta": {...}}],
        "metrics": {"llm_calls": ..., "tool_calls": ..., "tokens_est": ..., ...},
        "state":   {...},        # 框架组件、状态机、检索结果等结构化数据
        "hitl":    {...},        # interrupt 挂起时才有，前端渲染审批按钮
    }
```

`POST /api/demo/{chapter_id}` 调用它；前端把 `steps` 画成 Trace 时间线、`state` 画成状态机看板、`hitl` 画成审批按钮。
**人工审批回传 `hitl.case_id`**：第 4 章的 case_id 就是 `thread_id`，第 16 章的 `hitl.case_id` 也刻意设成 `thread_id`（`lc-` 前缀），后端据此路由到 `Command(resume=...)`。

## 7. 常见问题

- **没装 Ollama 会报错吗？** 不会，自动用 `TeachingChatModel`，返回 `mode: "mock"`。
- **`ModuleNotFoundError: langchain_core`？** 执行 `pip install -r requirements.txt`；本版框架是必装项。
- **MCP 适配器报 `mcp.shared.session`？** `mcp` 装成了 2.x，执行 `pip install "mcp>=1.9,<2"`。
- **LangGraph 报 `'plan' is already being used as a state key`？** 节点名不能和 State 的 key 同名，本工程已把节点改叫 `planner`。
- **条件边报 `NameError: LoopState`？** 不要在定义局部 `TypedDict` 的模块里启用 `from __future__ import annotations`，LangGraph 的 `get_type_hints()` 会解析不到。
- **数据库在哪？** `data/hr_agent.db`，首次运行自动建表，可随时删掉重建。
- **想换向量库 / 图数据库？** 只改 `common/lc_retrieval.py` 的 `VectorStore` 与 `Embeddings`，Demo 与 StateGraph 不用动。
