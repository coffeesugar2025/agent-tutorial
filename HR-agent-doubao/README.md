# HR 场景 Agent 工程教程（LangChain / LangGraph 全程实战）

> 面向零基础，Python 3.12 + Vue 3，**21 章正文 + 19 个可独立运行的小 demo**。
> 全书不用"伪代码"：每一章的代码都用真实的 **LangChain 1.5 / LangGraph** 原语实现，可以直接搬进项目。
> 没有 API Key 也能跑完（内置 `ScriptedChatModel` 假模型，流程、工具循环、结构化输出都是真实发生的）。

---

## 这本书想解决什么问题

市面上的 Agent 教程大多停在"能跑个 demo"。但 JD 里那句"不是跑 demo，是上生产干活"，翻译过来是六个字：

**接系统、调工具、读知识、跑流程、出结果、可验收。**

所以全书按这个顺序组织，且每一步都落在具体的 LangChain / LangGraph 原语上：

| 阶段 | 你学完能干什么 | 章节 | 主要原语 |
|---|---|---|---|
| 一、能对话 | 让模型稳定输出结构化数据 | 00–02 | `ChatPromptTemplate`、LCEL、`with_structured_output` |
| 二、能干活 | 自己跑循环、定义工具、按计划执行 | 03–06 | `create_agent`、`StateGraph`、`ToolNode`、`Send` |
| 三、有记忆 | 上下文不爆、跨会话记得住、能删干净 | 07–08 | `RunnableWithMessageHistory`、`InMemoryVectorStore`、`trim_messages` |
| 四、懂知识 | 从接向量库到混合检索、版本治理、Text2SQL/图 | 09–11 | `RecursiveCharacterTextSplitter`、`BM25Retriever`、`EnsembleRetriever`、`SQLDatabase` |
| 五、能协作 | 工具标准化、多智能体、人在环 | 12–14 | MCP 适配、Supervisor、`interrupt()`/`Command(resume=)` |
| 六、敢上线 | 重试幂等降级、长任务、Trace 与评测 | 15–17 | `with_retry`、`with_fallbacks`、`BaseCallbackHandler` |
| 七、交付产品 | Vue3 工作台、模型工程、求职落点 | 18–20 | `astream_events(v2)`、`init_chat_model` |

---

## 目录

### 第一部分 · 打地基（能对话）
- [00 导读与环境准备](docs/00-导读与环境准备.md) —— 技术底座总表、1.x 与 0.x 差异、必装依赖、5 周节奏
- [01 第一次调用大模型](docs/01-第一次调用大模型.md) —— LCEL 的 `|`、四种消息角色、stream
- [02 Prompt 与结构化输出](docs/02-Prompt与结构化输出.md) —— 五部位 prompt、`with_structured_output`、修复循环、evidence

### 第二部分 · Agent 内核（能干活）
- [03 Agent Loop](docs/03-Agent-Loop.md) —— `create_agent` → 手搭 `StateGraph` → 四道刹车
- [04 Tool / Function Calling](docs/04-Tool-Calling.md) —— `@tool`/`args_schema`、错误回填、写门禁
- [05 Planning](docs/05-Planning.md) —— 计划即数据、拓扑排序、环检测、重规划改依赖
- [06 Workflow 与状态机](docs/06-Workflow与状态机.md) —— 转移表、CAS 版本、非法转移拦截、checkpoint

### 第三部分 · 记忆与上下文
- [07 Memory](docs/07-Memory.md) —— 三种记忆、`filter` 是函数（1.x 坑）、去重、合规删除
- [08 Context Engineering](docs/08-Context-Engineering.md) —— token 预算、`trim_messages`、摘要压缩、六种手段

### 第四部分 · RAG 与知识工程
- [09 RAG 基础层](docs/09-RAG基础.md) —— 三种切片、元数据、`as_retriever`、LCEL RAG 链
- [10 RAG 进阶层](docs/10-RAG进阶.md) —— BM25 + 向量 + Ensemble、版本取最新、rerank 阈值、引用校验
- [11 RAG 高阶层](docs/11-RAG高阶.md) —— Text2SQL 三层护栏、图查询与 GraphRAG 边界

### 第五部分 · 协作与生态
- [12 MCP / Skill / Plugin](docs/12-MCP与Skill.md) —— MCP 三步握手、JSON Schema 适配、Skill 的写法
- [13 Multi-Agent](docs/13-Multi-Agent.md) —— Supervisor 串行、仲裁一票否决、`Send` 并行
- [14 Human-in-the-loop](docs/14-Human-in-the-loop.md) —— `interrupt`/`resume`、approve/edit/reject、四道校验

### 第六部分 · 生产级可靠性
- [15 可靠性工程](docs/15-可靠性工程.md) —— 重试、超时、降级、幂等、熔断
- [16 Sandbox 与长任务](docs/16-Sandbox与长任务.md) —— 断点续跑、分批、沙箱四道闸、预算闸门
- [17 可观测性与评测](docs/17-可观测性与评测.md) —— Callback 埋点、Golden Case、四指标、隐私红线

### 第七部分 · 交付与落地
- [18 Vue3 前端工作台](docs/18-Vue3前端工作台.md) —— `astream_events` + SSE + 事件时间线
- [19 模型工程与部署](docs/19-模型工程与部署.md) —— `init_chat_model`、三档路由、成本测算、微调判据
- [20 岗位地图与学习路径](docs/20-岗位地图与学习路径.md) —— 能力对照、作品集、面试题

---

## 三种读法

| 读法 | 怎么打开 | 适合 |
|---|---|---|
| **Markdown（源本）** | `docs/` 下 21 个 `.md` | VS Code 边读边改 |
| **离线网页书** | 双击 `site/index.html` | 侧边目录、上一章下一章、代码高亮 |
| **Demo 优先** | 直接跑 `demos/chXX/main.py` | 先看现象再读原理 |

改了 Markdown 想刷新网页书就重编：

```powershell
cd "C:\Users\a1572\Doubao\chats\2026-11-15\new-chat\HR-Agent-教程"
python build_site.py            # 生成 site/
python check_site.py            # 自检：有没有漏渲染的 markdown 标记
```

---

## 怎么跑起来

```powershell
cd "C:\Users\a1572\Doubao\chats\2026-11-15\new-chat\HR-Agent-教程\demos"

python -m venv .venv
.\.venv\Scripts\Activate.ps1      # 报"禁止运行脚本"就先 Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

pip install -r requirements.txt   # 必装：langchain 1.5 / langchain-core / langgraph / langchain-openai 等

python ch01_hello_llm\main.py
```

> `demos\.venv` 里已经装好全套依赖，可以直接用：
> `.\.venv\Scripts\python.exe ch03_agent_loop\main.py`

批量跑全部章节（PowerShell，ch18 走 server+client 单独验证）：

```powershell
cd demos
Get-ChildItem -Directory -Filter "ch*" | ForEach-Object {
  if ($_.Name -eq "_legacy" -or $_.Name -eq "ch18_vue_frontend") { return }
  $m = Join-Path $_.FullName "main.py"
  if (Test-Path $m) { Write-Host "== $($_.Name)"; & ".\.venv\Scripts\python.exe" $m }
}
```

两个特殊章节：

- **ch12（MCP）**：默认走本地 Mock 服务演示完整协议往返；`ch12_mcp\server.py` 是可选的真 MCP 服务端（需 `pip install mcp langchain-mcp-adapters`）。
- **ch18（前端）**：`server.py` + `client.py` 可在无浏览器环境验收；`index.html` 是单文件 Vue3（首次需联网拉 unpkg）。

**接真模型**：复制 `demos\.env.example` 为 `.env`，填 `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`（默认指向 DeepSeek）。
不填则每个 demo 首行提示"已切换到 ScriptedChatModel"，这不是报错。

---

## 每章怎么读

统一骨架：**目标 → 对应的 LangChain 原语 → 代码讲解 → 实测输出 → 常见坑 → 自检清单 → 练习**。

"实测输出"都是真跑出来的，包括**踩过的坑**（比如 `InMemoryVectorStore` 的 `filter` 要传函数、`EnsembleRetriever` 搬去了 `langchain-classic`、同步 `stream_events` 不支持 v2）。这些是本章最值钱的部分——它们能替你省下几个小时。

---

## 交付前做过哪些验收

| 验收项 | 方法 | 结果 |
|---|---|---|
| 语法 | `python -m compileall -q demos` | 通过 |
| 18 个 demo 真跑 | 逐个 `.venv\Scripts\python.exe chXX\main.py` | ch01–ch17、ch19 全部 OK |
| ch18 前端 | `server.py` + `client.py`（无浏览器） | 完整事件链：start → tool_start → tool_end → answer → done |
| 网页书 | `build_site.py` + `check_site.py` | 22 页，无漏渲染标记 |

**没验过的部分（避免误导你）**：

- **没有用真实模型跑过**：仓库无 `.env`，输出全部来自剧本假模型。接真模型时自行确认服务商支持 `tools` 字段。
- **`mcp` / `langchain-mcp-adapters` 未安装**：ch12 走本地 Mock 服务，真 MCP 握手以注释形式给出。
- **无 GPU**：ch19 的 LoRA / vLLM 只给配置与命令，没真训练；vLLM 需 Linux + CUDA。
- **ch18 页面依赖 unpkg CDN**：离线环境页面不渲染，验收以 `client.py` 为准。

---

## 一个约定

教程里所有 HR 数据都是虚构的：`张伟`、`C1024` 这些候选人，`苏州智造集团`、`技术中心` 这些组织，
以及员工手册里的条款，全部为示例而编造，不对应任何真实企业。真实项目请替换成你自己的脱敏数据。
