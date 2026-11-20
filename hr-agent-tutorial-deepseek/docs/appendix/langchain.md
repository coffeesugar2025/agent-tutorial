---
title: "附录 C | LangChain 1.x 速查：本书用到的 12 个 API"
slug: "langchain"
order: 103
minutes: 30
difficulty: "入门"
prerequisites: ["00", "02"]
summary: "把全书用到的 LangChain/LangGraph API 浓缩成一张速查表，附最小代码。"
---

# 附录 C | LangChain 1.x 速查：本书用到的 12 个 API

> 本书所有 demo 都基于 LangChain 1.x + LangGraph 1.x。你不需要先学完整个框架，先掌握这 12 个 API，就能读懂全部章节代码。

## 1. 安装与版本

```powershell
python -m pip install -r code/requirements.txt
python -c "import langchain, langgraph; print(langchain.__version__)"
```

本书验证版本：`langchain 1.4.x`、`langchain-core 1.7.x`、`langgraph 1.2.x`。1.x 与 0.x 的 `AgentExecutor`、`initialize_agent` 写法不同，网上旧教程不要直接抄。

## 2. 消息：一切上下文都是 Message

```python
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

messages = [
    SystemMessage("你是 HR 助手，回答必须带制度引用。"),
    HumanMessage("我还有几天年假？"),
]
```

`AIMessage.tool_calls` 是模型发起的工具调用；`ToolMessage` 是工具结果回填。第 02 章会看到完整序列。

## 3. 模型：统一用 BaseChatModel

```python
from common.lc import MockChatModel, get_chat_model

llm = MockChatModel(script=[{"content": "你还有 13 天年假。"}])
# 或：有 Key 时返回 ChatOpenAI（兼容 DeepSeek/Qwen/Ollama/vLLM）
llm = get_chat_model()
```

真实模型只换这一层，Agent、工具、RAG、评测代码不变。

## 4. 工具：@tool

```python
from langchain_core.tools import tool

@tool
def get_leave_balance(employee_id: str) -> str:
    """查询员工年假余额。参数是工号，如 E1001。"""
    return "13"
```

函数名、docstring、类型标注会自动变成给模型看的 Schema。复杂参数用 `args_schema=PydanticModel`。

## 5. 单 Agent：create_agent

```python
from langchain.agents import create_agent

agent = create_agent(
    model=llm,
    tools=[get_leave_balance],
    system_prompt="你是 HR 助手，先查工具再回答。",
)
result = agent.invoke({"messages": [{"role": "user", "content": "我还有几天年假？"}]})
print(result["messages"][-1].content)
```

`create_agent` 内部就是“模型 → 工具 → 模型”的循环，基于 LangGraph 编译；可以用 `recursion_limit` 控制步数。

## 6. 图：StateGraph

```python
from langgraph.graph import StateGraph, START, END, MessagesState

def model_node(state: MessagesState):
    return {"messages": [llm.invoke(state["messages"])]}

graph = StateGraph(MessagesState)
graph.add_node("model", model_node)
graph.add_edge(START, "model")
graph.add_edge("model", END)
app = graph.compile()
```

第 02、04、05、12、13 章都用它。显式建图的好处是：每个节点、每条边、每个终止条件都看得见。

## 7. 工具节点：ToolNode + tools_condition

```python
from langgraph.prebuilt import ToolNode, tools_condition

graph.add_node("tools", ToolNode([get_leave_balance]))
graph.add_conditional_edges("model", tools_condition, {"tools": "tools", END: END})
graph.add_edge("tools", "model")
```

这就是 Agent Loop 的图形化写法：模型判断要不要调工具，工具节点执行，再回到模型。

## 8. 检查点：InMemorySaver

```python
from langgraph.checkpoint.memory import InMemorySaver

app = graph.compile(checkpointer=InMemorySaver())
config = {"configurable": {"thread_id": "employee-E1001"}}
app.invoke({"messages": [HumanMessage("你好")]}, config)
state = app.get_state(config)   # 会话、步骤、下一步都能取回
```

生产换成 `SqliteSaver` / `PostgresSaver`，接口不变。第 05、06、12、14 章用它做恢复。

## 9. 人工审批：interrupt + Command

```python
from langgraph.types import interrupt, Command

def approval_node(state):
    decision = interrupt({"action": "adjust_salary", "employee_id": "E1001"})
    return {"approved": decision == "approve"}

app.invoke(input, config)                 # 停在 interrupt
app.invoke(Command(resume="approve"), config)  # 人审批后继续
```

第 12 章用它实现“暂停 → 审批 → 恢复”。更完整的方案是 `HumanInTheLoopMiddleware`，第 16 章后端会用到。

## 10. 提示词与解析：ChatPromptTemplate / PydanticOutputParser

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

prompt = ChatPromptTemplate.from_messages([
    ("system", "你是 JD 抽取器。{format_instructions}"),
    ("human", "{jd}"),
])
chain = prompt | llm | PydanticOutputParser(pydantic_object=JobCard)
```

第 01 章用它做结构化输出、校验与重试。

## 11. 检索：Splitter / VectorStore / Retriever

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.vectorstores import InMemoryVectorStore

splitter = RecursiveCharacterTextSplitter(chunk_size=400, chunk_overlap=60)
docs = splitter.split_documents(raw_docs)
store = InMemoryVectorStore(embedding=my_embeddings)
store.add_documents(docs)
retriever = store.as_retriever(search_kwargs={"k": 3})
```

第 08 章用 `InMemoryVectorStore`，第 09 章用 `BM25Retriever` + `EnsembleRetriever` 做混合检索。

## 12. 可观测：Callback

```python
from common.lc import TracerCallbackHandler

tracer = TracerCallbackHandler()
agent.invoke(input, config={"callbacks": [tracer]})
print(tracer.summary())
```

第 15 章用它采集 LLM 调用、工具调用、token，再算成功率、P95、成本。生产可接 LangSmith。

## 13. 常见坑

1. **1.x 没有 `AgentExecutor`**：用 `create_agent` 或 `create_react_agent`，旧教程的 `initialize_agent` 已移除。
2. **`tool_calls` 的字段是 `args`**：不是 OpenAI 原始格式的 `arguments`；混用会解析失败。
3. **checkpointer 必须配 `thread_id`**：否则恢复、HITL 都无从谈起。
4. **`interrupt` 只能暂停，不能执行副作用**：审批前不要写库、发邮件。
5. **InMemoryVectorStore 不是生产向量库**：它适合教学与测试；生产换 Qdrant/Milvus/pgvector。
6. **MockChatModel 不读 Prompt**：它按脚本返回，用来保证离线可复现；真实模型才会理解 Prompt。

> 📌 **考点**：面试被问“为什么用 LangChain”，不要只说“方便”。说清三点：统一模型/工具/消息抽象，降低替换成本；LangGraph 提供可恢复的状态与 HITL；生态里有 Retriever、Callback、LangSmith 等工程组件。然后补一句“但核心循环和状态机仍然要能画出来”。
