

from langchain_openai import ChatOpenAI
model = ChatOpenAI(
    model="deepseek-flash",                       # 注意：去掉 "openai:" 前缀
    api_key="sk-827674a122e54cea865b969ec3fad26d",
    base_url="https://api.deepseek.com",
    temperature=0.5,
    timeout=300,
    max_tokens=25000,
)
import urllib.error
import urllib.request
from langchain.tools import tool
@tool
def fetch_text_from_url(url: str) -> str:
    """Fetch the document from a URL.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; quickstart-research/1.0)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
    except urllib.error.URLError as e:
        return f"Fetch failed: {e}"
    text = raw.decode("utf-8", errors="replace")
    return text
from pydantic import BaseModel
class Answer(BaseModel):
    summary: str
    confidence: float

from langchain.agents import AgentState


class MyState(AgentState):
    user_id: str
    call_count: int

from dataclasses import dataclass
@dataclass
class Context:
    user_id: str


from langchain.agents import create_agent

agent = create_agent(
    model="google_genai:gemini-4-hydrogen",
    tools=[],
    state_schema=MyState,
    context_schema=Context,
)
class MyState(AgentState):
    user_id: str
    call_count: int

# 1)Model

from langgraph.checkpoint.memory import InMemorySaver

checkpointer = InMemorySaver()

SYSTEM_PROMPT = """You are a literary data assistant.

## Capabilities

- `fetch_text_from_url`: loads document text from a URL into the conversation.
Do not guess line counts or positions—ground them in tool results from the saved file."""

checkpointer = InMemorySaver()

agent = create_agent(
    model=model,
    tools=[fetch_text_from_url],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
    response_format=Answer,
    state_schema=MyState,
)

# 2) Tool,上图中的tools

# 3) System prompt,上图中的 system_prompt

# 4) Structured output

result = agent.invoke({"messages": [{"role": "user", "content": "Summarize AI trends"}]})
result["structured_response"]  # Answer(summary=..., confidence=...)

# 5） AgentState
# Every agent manages its execution context through AgentState,
# a typed dictionary that holds the current conversation history
# and any custom fields your tools and middleware need.




# 6)Invocation

# You can invoke an agent with a message. Behind the scenes that passes
# an update to the agent’s State. All agents include a sequence of messages
# in their state; to invoke the agent, pass a new message along with a thread_id
# so the agent can persist and resume conversation history:



from langchain_core.utils.uuid import uuid7
config = {"configurable": {"thread_id": str(uuid7())}}

result = agent.invoke(
    {"messages": [{"role": "user", "content": "What's the weather in San Francisco?"}]},
    config=config,
)

# A follow-up turn on the same conversation: reuse the same thread_id to keep history
result = agent.invoke(
    {"messages": [{"role": "user", "content": "What about tomorrow?"}]},
    config=config,
)


# If you also need to pass per-run configuration (such as a user ID,
# API keys, or feature flags) to tools and middleware,
# pass it as context alongside config. Define the shape of that data
# with context_schema
# and access it through runtime.context:


result = agent.invoke(
    {"messages": [{"role": "user", "content": "What's the weather in San Francisco?"}]},
    config={"configurable": {"thread_id": str(uuid7())}},
    context=Context(user_id="user-123"),
)



# 7) Streaming

from langchain.messages import AIMessage, HumanMessage


stream = agent.stream_events(
    {"messages": [{"role": "user", "content": "Search for AI news and summarize the findings"}]},
    version="v3",
)
for snapshot in stream.values:
    # Each snapshot contains the full state at that point
    latest_message = snapshot["messages"][-1]
    if latest_message.content:
        if isinstance(latest_message, HumanMessage):
            print(f"User: {latest_message.content}")
        elif isinstance(latest_message, AIMessage):
            print(f"Agent: {latest_message.content}")
    elif latest_message.tool_calls:
        print(f"Calling tools: {[tc['name'] for tc in latest_message.tool_calls]}")

# 8) config the harness

from langchain.agents import create_agent
from deepagents.backends import StateBackend
from deepagents.middleware import FilesystemMiddleware


# 8.1)Execution environment
# Agents are especially useful when they can take action rather than
# just generate text.
# The execution environment gives the agent a workspace:
# tools it can call, a filesystem for reading and writing files
# across turns, and code execution for running scripts or shell commands.

agent = create_agent(
    model="google_genai:gemini-4-hydrogen",
    tools=[fetch_text_from_url],
    middleware=[FilesystemMiddleware(backend=StateBackend())],
)

# 8.2) Context management
# Every model call has a fixed context window.
# As an agent runs, that window fills with accumulating history,
# tool results, and intermediate steps.
# Summarization compresses history before overflow hits; memory loads persistent
# instructions at startup so knowledge carries across sessions; skills surface
# domain knowledge on demand rather than loading everything upfront.

from deepagents.backends import StateBackend
from deepagents.middleware import FilesystemMiddleware, MemoryMiddleware, SkillsMiddleware, SummarizationMiddleware

backend = StateBackend()
model = "google_genai:gemini-4-hydrogen"

agent = create_agent(
    model=model,
    tools=[fetch_text_from_url],
    middleware=[
        FilesystemMiddleware(backend=backend),
        SummarizationMiddleware(model=model, backend=backend),
        MemoryMiddleware(backend=backend, sources=["./AGENTS.md"]),
        SkillsMiddleware(backend=backend, sources=["./skills/"]),
    ],
)




# 8.3) Planning and delegation
# Complex tasks often exceed what one context window can handle.
# Delegation lets the main agent break work into pieces,
# hand them to subagents that each run in their own isolated context,
# and stay focused on coordination rather than execution.
# Work can run in parallel; the main agent’s context stays clean.
from deepagents.backends import StateBackend
from deepagents.middleware import FilesystemMiddleware
from deepagents.middleware.subagents import SubAgentMiddleware
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain.tools import tool


@tool
def search(query: str) -> str:
    """Search for a query and return a short summary."""
    return f"Search results for: {query}"


backend = StateBackend()

agent = create_agent(
    model="google_genai:gemini-4-hydrogen",
    tools=[search],
    middleware=[
        FilesystemMiddleware(backend=backend),
        TodoListMiddleware(),
        SubAgentMiddleware(
            backend=backend,
            subagents=[
                {
                    "name": "researcher",
                    "description": "Searches and returns a structured summary.",
                    "system_prompt": "Use the search tool to research the question and summarize key points.",
                    "tools": [search],
                    "model": "anthropic:claude-sonnet-4-6",
                    "middleware": [],
                }
            ],
        ),
    ],
)

# 8.3) Name your agent
# Optionally use an identifier for the agent.
# This is especially useful when embedding the agent as a subgraph in multi-agent systems.

agent = create_agent(model="google_genai:gemini-4-hydrogen", tools=search, name="research_assistant")



from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware, ToolRetryMiddleware
from langchain.tools import tool


# 8,4) Fault tolerance
# Agents in production encounter failures that rarely appear in development:
# rate limits, model timeouts, transient API errors.
# Fault tolerance middleware handles these at the infrastructure level
# so your tools and business logic don’t need try/catch around every call.
@tool
def search(query: str) -> str:
    """Search for a query and return a short summary."""
    return f"Search results for: {query}"


agent = create_agent(
    model="google_genai:gemini-4-hydrogen",
    tools=[search],
    middleware=[
        ModelRetryMiddleware(max_retries=3),
        ToolRetryMiddleware(max_retries=2),
    ],
)



# 8.6) Guardrails
# Some policies can’t live in a prompt—they need to be enforced deterministically
# regardless of what the model does.
# Guardrails intercept data as it flows through the agent loop,
# applying compliance rules or content policies before tool results reach the model’s context.
from langchain.agents import create_agent
from langchain.agents.middleware import PIIMiddleware
from langchain.tools import tool


@tool
def search(query: str) -> str:
    """Search for a query and return a short summary."""
    return f"Search results for: {query}"


agent = create_agent(
    model="google_genai:gemini-4-hydrogen",
    tools=[search],
    middleware=[PIIMiddleware("email")],
)

# 8.7) Steering
# Full autonomy isn’t always appropriate.
# Steering lets you place humans at specific decision points—before destructive writes,
# expensive API calls, or anything requiring judgment—without restructuring your agent.
# The agent pauses and waits; a human approves, edits, or rejects; execution continues.

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.tools import tool


@tool
def search(query: str) -> str:
    """Search for a query and return a short summary."""
    return f"Search results for: {query}"


agent = create_agent(
    model="google_genai:gemini-4-hydrogen",
    tools=[search],
    middleware=[HumanInTheLoopMiddleware(interrupt_on={"write_file": True})],
)
