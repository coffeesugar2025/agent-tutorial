# HR Agent 实战教程

> 从一个 HR 的真实问题出发，用 **Python 3.12 + LangChain 1.x + LangGraph + Vue 3** 做出一个能查制度、调工具、走审批、可评测的 Agent。
> 不是“调个 API 的 Demo”，而是把 Agent、Tool、Memory、RAG、Workflow、HITL、可靠性、评测一层层搭起来。

---

## 这门教程解决什么问题

网上大部分 Agent 教程停在“让模型调用一个天气工具”。但真实岗位要你做的是：

- 员工问“我还有几天年假”，Agent 要查余额、查制度、算资格，而不是背一段政策；
- 招聘要安排面试，Agent 要查候选人、查面试官空闲、发邀请，还要防止重复发送；
- 调薪、开除这类敏感操作，Agent 不能自己做主，必须停下来等人审批；
- 制度有 2024 版、2025 版、2027 讨论稿，答错版本就是事故；
- 上线后老板问“这版比上版好吗”，你要拿得出成功率、工具准确率、P95 延迟和 Bad Case。

这门教程用 **HR 共享服务中心** 这一条业务线，把上述问题逐个拆开，每章一个可运行的最小实现，最后组装成一个前后端完整的项目。

## 你会得到什么

- **18 章循序渐进的教程**：从“什么是 Agent”到“多智能体、沙箱、可观测性、评测”，全部以 LangChain 1.x / LangGraph 为实现框架。
- **单文件版**：[`docs/ALL_IN_ONE.md`](docs/ALL_IN_ONE.md)，约 32 万字，方便离线阅读或打印。
- **16 个可离线运行的 Python 脚本**：不需要 API Key，不联网，`python code/ch02_agent_loop.py` 就能跑；每个脚本都能看到对应的 LangChain/LangGraph API。
- **1 个可交付的全栈项目**：Vue 3 课程站 + HR Agent 工作台 + FastAPI 后端 + RAG + 审批 + 评测看板。
- **一套评测集**：20 条 Golden Case，覆盖制度、假期、招聘、审批、边界拒答。
- **一份求职材料**：简历 bullet、20 道高频面试题、系统设计答题框架、30/60/90 天计划。

## 快速开始

环境：Python 3.12、Node.js 18+（只在跑前端时需要）。

```powershell
# 1. 安装 Python 依赖（LangChain / LangGraph / FastAPI / Pydantic / pytest）
python -m pip install -r code/requirements.txt

# 2. 跑第一个 Agent（离线 Mock 模型）
python code/ch00_hello_agent.py

# 3. 跑全部章节脚本，确认环境 OK
python code/run_all.py

# 4. 跑测试
python -m pytest tests -q

# 5. 启动完整项目
python app/backend/main.py
# 打开 http://127.0.0.1:8000
```

前端开发模式：

```powershell
cd app/frontend
pnpm install
pnpm dev
# http://127.0.0.1:5173，/api 自动代理到 8000
```

> 默认使用 `MockChatModel`（LangChain 原生 `BaseChatModel`）：按脚本返回固定的工具调用，保证离线、确定性、可测试。它**不是真实大模型**。
> 想接真实模型，设置环境变量即可，Agent 代码不用改：
>
> ```powershell
> $env:HR_LLM_MODE="openai"
> $env:HR_LLM_BASE_URL="https://api.deepseek.com/v1"
> $env:HR_LLM_MODEL="deepseek-chat"
> $env:HR_LLM_API_KEY="sk-..."
> python code/ch02_agent_loop.py
> ```

## 课程地图

### 第一部分 · 启程：从 HR 痛点理解 Agent

| 章节 | 你会做出什么 |
| --- | --- |
| [00 从 HR 痛点出发：Agent 到底是什么](docs/00-course-map.md) | 30 行跑通第一个“会查余额”的 Agent |
| [01 LLM 与 Prompt：把 JD 变成结构化数据](docs/01-llm-prompt.md) | JD 抽取 + JSON 校验 + 失败重试 |

### 第二部分 · 单 Agent 核心

| 章节 | 你会做出什么 |
| --- | --- |
| [02 Agent Loop：让模型学会“再来一轮”](docs/02-agent-loop.md) | 用 LangGraph 搭出循环、消息回填、终止条件 |
| [03 Tool Calling：把 HR 系统变成模型的手脚](docs/03-tool-calling.md) | 工具注册、参数校验、幂等、并行调用 |
| [04 Planning：ReAct、Plan-and-Solve 与任务拆解](docs/04-planning.md) | 两种规划模式跑同一个招聘任务 |
| [05 Workflow 与状态机：确定的事交给代码](docs/05-workflow.md) | 入职流程状态机 + 断点恢复 |
| [06 Memory：让助手记住员工与历史](docs/06-memory.md) | 会话/摘要/画像三层记忆 |
| [07 Context Engineering：上下文预算与压缩](docs/07-context-engineering.md) | Token 预算 + 长面试记录 map-reduce |

### 第三部分 · RAG 与知识工程

| 章节 | 你会做出什么 |
| --- | --- |
| [08 RAG 基础：从员工手册到可引用回答](docs/08-rag-basics.md) | LangChain 切片、Embedding、向量库、引用校验 |
| [09 RAG 进阶：混合检索、版本治理与引用质检](docs/09-rag-advanced.md) | BM25 + 向量 + RRF + 版本过滤 + 拒答 |
| [10 知识图谱与 Text2SQL：组织、技能与数据查询](docs/10-knowledge-graph.md) | 组织图谱 + 只读 SQL 安全闸门 |

### 第四部分 · 生产级可靠性

| 章节 | 你会做出什么 |
| --- | --- |
| [11 可靠性工程：超时、重试、幂等与降级](docs/11-reliability.md) | 重试、熔断、幂等、批量补偿 |
| [12 Human-in-the-loop 与权限：敏感操作必须有人签字](docs/12-hitl-security.md) | 审批中断/恢复、RBAC、审计哈希链 |
| [13 Multi-Agent：招聘小组如何协作](docs/13-multi-agent.md) | Supervisor + 三个角色 + 冲突仲裁 |
| [14 Sandbox、Code Mode 与长任务恢复](docs/14-sandbox-longtask.md) | AST 沙箱、子进程超时、断点续跑 |
| [15 可观测性与评测：用数据证明 Agent 变好了](docs/15-observability-eval.md) | Trace、指标、Golden Case、回归门禁 |

### 第五部分 · 项目实战与求职

| 章节 | 你会做出什么 |
| --- | --- |
| [16 综合项目：HR 智能服务台（Vue 3 + FastAPI）](docs/16-capstone.md) | 完整前后端 + 审批 + 评测看板 |
| [17 从教程到 Offer：作品集、面试与 90 天进阶](docs/17-career.md) | 简历 bullet、20 道面试题、进阶计划 |

附录：

- [术语表](docs/appendix/glossary.md)
- [LangChain 1.x 速查：本书用到的 12 个 API](docs/appendix/langchain.md)
- [模型工程速查：从 API 到 LoRA、DPO 与 vLLM](docs/appendix/model-engineering.md)
- [Agent 生态：MCP、Skill、Plugin、Harness 与选型](docs/appendix/ecosystem.md)

## 学习路径建议

**4 周冲刺（每天 2 小时）**

- 第 1 周：00–05，重点把 Loop、Tool、Workflow 跑通，能讲清消息序列。
- 第 2 周：06–10，重点 RAG 与版本治理，自己加 5 条评测问题。
- 第 3 周：11–15，重点可靠性、HITL、评测，整理 3 个 Bad Case。
- 第 4 周：16–17，跑通项目，改一个工具，写简历与项目复盘。

**8 周稳学（每天 1 小时）**

每周 2–3 章，每章至少完成 2 道练习；第 7 周做项目扩展，第 8 周做模拟面试。

## 项目架构

```text
Vue 3 工作台
  │  对话 / 轨迹 / 引用 / 审批 / 评测
  ▼
FastAPI
  ├─ Agent（LangChain create_agent + LangGraph 状态图）
  ├─ RAG（LangChain Retriever + BM25 + 向量 + 版本过滤 + 引用校验）
  ├─ Tools（LangChain @tool：余额 / 制度 / 候选人 / 面试 / 调薪 / 工单 / 入职）
  ├─ HITL（审批单 + 中断恢复 + RBAC / 审计链）
  ├─ Memory（会话 / 画像 / 事实）
  └─ Evaluation（LangChain Callback + 20 条 Golden Case / 指标 / 门禁）
  ▼
SQLite + JSON 种子数据 + 制度库
```

## 目录结构

```text
hr-agent-tutorial/
├─ docs/                  # 18 章教程 + 术语表
├─ code/
│  ├─ common/             # MockChatModel、LangChain 适配、Token 工具、数据加载
│  ├─ data/               # 员工、候选人、制度、工单、Golden Case
│  └─ chXX_*.py           # 每章可独立运行的脚本
├─ app/
│  ├─ backend/            # FastAPI + Agent 内核 + RAG + 审批 + 评测
│  └─ frontend/           # Vue 3 课程站与工作台
├─ tests/                 # 公共模块与 API 测试
└─ scripts/               # 文档与代码一致性检查
```

## 设计取舍（为什么这样写）

- **以 LangChain 1.x / LangGraph 为骨架**：`create_agent` 负责单 Agent 循环，`StateGraph` 负责流程、循环与多 Agent，`InMemorySaver` 负责会话与恢复，`@tool` / `ChatPromptTemplate` / `Retriever` 负责工具、提示词与检索。你会学到“框架帮你做了什么”，也会在关键章节拆开图看内部，而不是只背 API。
- **默认 MockChatModel**：让代码可离线、可测试、可复现；真实模型只换 `BaseChatModel` 实现，不换业务代码。
- **所有数据虚构**：Acme 公司、员工、候选人、制度均为教学编造，不涉及真实个人信息。
- **先能跑，再上生产**：每章都有“工程化视角”，明确最小实现离生产还差什么。

## 验证命令

```powershell
python code/run_all.py                 # 16 个章节脚本
python -m pytest tests -q              # 公共模块 + API 测试
python scripts/verify_docs.py          # 文档结构、frontmatter、代码文件检查
```

## License

MIT（代码可自由用于学习与作品集；教程文字转载请注明出处）。
