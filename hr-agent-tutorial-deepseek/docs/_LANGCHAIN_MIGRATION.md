# LangChain 迁移规范（本轮必须遵守）

> 2026-11 更新：全书 demo 从“手写最小实现”改为 **LangChain 1.x + LangGraph 1.x**。
> 旧大纲里“手写 while 循环 / 不写框架 / 不用 LangChain”等表述一律以本文件为准，需要改写。

## 1. 目标

- 每个 `code/chXX_*.py` 都能看到真实的 LangChain/LangGraph API，而不是只用了一个消息 dataclass。
- 保留原有业务场景、数据、断言与教学重点；框架是“更好的实现”，不是把内容换掉。
- 仍要讲清框架内部发生了什么：用 `StateGraph` 显式搭循环、用 `ToolNode` 看工具节点、用 checkpointer 看恢复，而不是只写 `agent.invoke()` 一句。

## 2. 统一依赖与公共层

依赖已写入 `code/requirements.txt`：`langchain`、`langchain-core`、`langchain-openai`、`langchain-text-splitters`、`langchain-community`、`langgraph`、`rank-bm25`。

公共层 `code/common/lc.py` 已提供并测试通过：

| API | 用途 |
| --- | --- |
| `MockChatModel(script=[...])` | LangChain 原生 `BaseChatModel`，按脚本返回 `AIMessage` / `tool_calls`，离线可跑 |
| `get_chat_model(script=...)` | 有 Key 返回 `ChatOpenAI`，否则返回 `MockChatModel` |
| `run_agent(tools, messages, script, system_prompt, max_steps)` | 一行调用 `create_agent`，返回最终 state |
| `final_text(state)` / `tool_names(state)` | 从 state 取最终回答/工具名 |
| `TracerCallbackHandler` | 汇总 LLM 调用、工具调用、token |

脚本头部统一：

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.lc import MockChatModel, get_chat_model, run_agent, final_text, tool_names
```

> 不要修改 `common/lc.py`；如果缺能力，先在汇报里说明，由主线程统一补。

## 3. 章节映射（必须用到的 API）

| 章 | 必须体现的 LangChain/LangGraph 能力 |
| --- | --- |
| 00 | `create_agent` + `@tool` + `MockChatModel`；用 60–90 行跑通“查余额 → 答”；讲清 `messages` 与工具回填 |
| 01 | `ChatPromptTemplate` + `PydanticOutputParser` / `JsonOutputParser` + `RunnableLambda` 重试；`get_chat_model` |
| 02 | `StateGraph` + `ToolNode` + `tools_condition`，显式画出 model→tools→model 循环；用 `recursion_limit`/步数计数器终止 |
| 03 | `@tool(args_schema=...)` / `StructuredTool` + `create_agent`；权限/幂等/并行作为工具包装层保留 |
| 04 | `StateGraph` 的 plan → execute → replan 图；计划用 Pydantic 模型；`Command` 或条件边实现分支 |
| 05 | `StateGraph` 入职状态机 + `InMemorySaver`；用 `get_state` / `update_state` 或重新 invoke 演示恢复 |
| 06 | `MessagesState` + `InMemorySaver` + `trim_messages`；长期画像/事实可以自定义，但消息与线程用 LangGraph |
| 07 | `trim_messages` + `ChatPromptTemplate` + `RunnableLambda`；token 预算与 map-reduce 用 LangChain 链 |
| 08 | `RecursiveCharacterTextSplitter` + 自定义 `Embeddings` + `InMemoryVectorStore` + `ChatPromptTemplate`；引用校验保留 |
| 09 | `BM25Retriever` + `InMemoryVectorStore.as_retriever()` + `EnsembleRetriever`（或手写 RRF 融合两路 retriever）；元数据过滤在检索前 |
| 10 | `SQLDatabase` + `QuerySQLDataBaseTool`（或 `SQLDatabase.run`）；SQL 白名单/只读/ LIMIT 作为安全包装；图谱部分可自定义 |
| 11 | `Runnable.with_retry()` + `.with_fallbacks()`；熔断/幂等/补偿保留自定义实现 |
| 12 | `StateGraph` + `interrupt()` + `Command(resume=...)` + `InMemorySaver`；审批/ RBAC/审计链保留 |
| 13 | `StateGraph` supervisor 多 Agent；用条件边/`Command` 交接；共享 state + 轮次/预算终止 |
| 14 | LangChain `@tool` 包装沙箱执行；`create_agent` 的 Code Mode；长任务 checkpoint 可用 `InMemorySaver` 或原 JSON |
| 15 | `create_agent` + `TracerCallbackHandler` / `BaseCallbackHandler` 采集指标；Golden Case 评测保留 |
| 16 | 后端 `agent.py` 改为 `create_agent` + `HumanInTheLoopMiddleware` + `InMemorySaver`；前端不变 |

## 4. 文档改写规则

1. frontmatter 后立刻加一个提示块（章本章节）：

```markdown
> 🧩 **框架说明**：本章 demo 基于 **LangChain 1.x + LangGraph**，核心 API：`create_agent` / `@tool` / `StateGraph`。正文中的代码若标注“原理示意”，用于解释内部机制；完整可运行代码见 `code/chXX_*.py`。
```

2. 第 3 节“动手”开头，用 2–4 句话说明本章用了哪些 LangChain 抽象，以及框架替你做了什么。
3. 至少把第 3 节的主代码块替换为真实的 LangChain 版关键代码（可从脚本截取）；其他原理性代码块保留时，必须在代码块前写“原理示意（伪代码）”。
4. 删除/改写所有“不用框架”“不写框架”“手写循环是唯一正确方式”的表述。可以写“用 LangGraph 把循环显式搭出来，看清框架内部”。
5. 第 6 节“工程化视角”补一句：生产里可以直接用 LangChain 生态的哪些组件（checkpointer、LangSmith、LangServe 等），以及本实现的边界。
6. 保留九段结构、字数、练习与答案；不要为了 API 删掉业务解释。

## 5. 验收

```powershell
python code/chXX_*.py              # exit 0，断言全过
python code/run_all.py --only "XX" # 通过
```

汇报时写清：每章用了哪些 LangChain API、哪些逻辑仍是自定义、运行结果。
