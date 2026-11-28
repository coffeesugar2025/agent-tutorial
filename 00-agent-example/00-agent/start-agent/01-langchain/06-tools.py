


# Tools extend what agents can do—letting them fetch real-time data,
# execute code, query external databases, and take actions in the world.
# Under the hood, tools are callable functions with well-defined inputs
# and outputs that get passed to a chat model. The model decides
# when to invoke a tool based on the conversation context, and what input arguments to provide.

# 1）创建工具

# 1.1，基础创建
from langchain.tools import tool

@tool
def search_database(query: str, limit: int = 10) -> str:
    """Search the customer database for records matching the query.

    Args:
        query: Search terms to look for
        limit: Maximum number of results to return
    """
    return f"Found {limit} results for '{query}'"

# 1.2，自定义工具属性
# 自定义工具名称
@tool("web_search")  # Custom name
def search(query: str) -> str:
    """Search the web for information."""
    return f"Results for: {query}"

print(search.name)  # web_search
# 自定义工具描述
@tool("calculator", description="Performs arithmetic calculations. Use this for any math problems.")
def calc(expression: str) -> str:
    """Evaluate mathematical expressions."""
    return str(eval(expression))

# 定义高级的schema 属性

# Define complex inputs with Pydantic models or JSON schemas:

# Pydantic models
from pydantic import BaseModel, Field
from typing import Literal

class WeatherInput(BaseModel):
    """Input for weather queries."""
    location: str = Field(description="City name or coordinates")
    units: Literal["celsius", "fahrenheit"] = Field(
        default="celsius",
        description="Temperature unit preference"
    )
    include_forecast: bool = Field(
        default=False,
        description="Include 5-day forecast"
    )

@tool(args_schema=WeatherInput)
def get_weather(location: str, units: str = "celsius", include_forecast: bool = False) -> str:
    """Get current weather and optional forecast."""
    temp = 22 if units == "celsius" else 72
    result = f"Current weather in {location}: {temp} degrees {units[0].upper()}"
    if include_forecast:
        result += "\nNext 5 days: Sunny"
    return result


# JSON schemas:
weather_schema = {
    "type": "object",
    "properties": {
        "location": {"type": "string"},
        "units": {"type": "string"},
        "include_forecast": {"type": "boolean"}
    },
    "required": ["location", "units", "include_forecast"]
}

@tool(args_schema=weather_schema)
def get_weather(location: str, units: str = "celsius", include_forecast: bool = False) -> str:
    """Get current weather and optional forecast."""
    temp = 22 if units == "celsius" else 72
    result = f"Current weather in {location}: {temp} degrees {units[0].upper()}"
    if include_forecast:
        result += "\nNext 5 days: Sunny"
    return result

# 1.3 Reserved argument names

# The following parameter names are reserved and cannot be used as tool arguments. Using these names will cause runtime errors.
# Parameter name	Purpose
# config	Reserved for passing RunnableConfig to tools internally
# runtime	Reserved for ToolRuntime parameter (accessing state, context, store)
# To access runtime information, use the ToolRuntime parameter instead of naming your own arguments config or runtime.
# If you use InjectedState, InjectedStore, get_runtime(), or InjectedToolCallId, see Migrate from older injection patterns.


# 2,Access context

# Tools are most powerful when they can access runtime information
# like conversation history, user data, and persistent memory.
# This section covers how to access and update this information from within your tools.
# Tools can access runtime information through the ToolRuntime parameter, which provides:

## 2.1,Short-term memory (State)
# State represents short-term memory that exists for the duration of a conversation.
# It includes the message history and any custom fields you define in your graph state.

## 2.1.1 Access state
# Add runtime: ToolRuntime to your tool signature to access state.
# At call time, ToolNode injects the value automatically;
# the parameter is not included in the tool schema sent to the model.
# Use runtime.state to read the current conversation state:

from langchain.tools import tool, ToolRuntime
from langchain.messages import HumanMessage

@tool
def get_last_user_message(runtime: ToolRuntime) -> str:
    """Get the most recent message from the user."""
    messages = runtime.state["messages"]

    # Find the last human message
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return message.content

    return "No user messages found"

# Access custom state fields
@tool
def get_user_preference(
    pref_name: str,
    runtime: ToolRuntime
) -> str:
    """Get a user preference value."""
    preferences = runtime.state.get("user_preferences", {})
    return preferences.get(pref_name, "Not set")

# 2.1.2,Update state
# Use Command to update the agent’s state.
# This is useful for tools that need to update custom state fields.
# Include a ToolMessage in the update so the model can see the result of the tool call:

from langchain.agents import AgentState
from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command


class CustomState(AgentState):
    user_name: str


@tool
def set_user_name(new_name: str, runtime: ToolRuntime[None, CustomState]) -> Command:
    """Set the user's name in the conversation state."""
    return Command(
        update={
            "user_name": new_name,
            "messages": [
                ToolMessage(
                    content=f"User name set to {new_name}.",
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )

# 2.2,context
# Context provides immutable configuration data that is passed at invocation time.
# Use it for user IDs, session details, or application-specific settings-
# that shouldn’t change during a conversation.

# Access context through runtime.context.
# Configure a checkpointer and pass context with a stable thread_id
# so the conversation persists across invocations:

from dataclasses import dataclass

from langchain.agents import create_agent
from langchain.tools import tool, ToolRuntime
from langchain_core.utils.uuid import uuid7
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver


USER_DATABASE = {
    "user123": {
        "name": "Alice Johnson",
        "account_type": "Premium",
        "balance": 5000,
        "email": "alice@example.com",
    },
    "user456": {
        "name": "Bob Smith",
        "account_type": "Standard",
        "balance": 1200,
        "email": "bob@example.com",
    },
}


@dataclass
class UserContext:
    user_id: str


@tool
def get_account_info(runtime: ToolRuntime[UserContext]) -> str:
    """Get the current user's account information."""
    user_id = runtime.context.user_id

    if user_id in USER_DATABASE:
        user = USER_DATABASE[user_id]
        return (
            f"Account holder: {user['name']}\n"
            f"Type: {user['account_type']}\n"
            f"Balance: ${user['balance']}"
        )
    return "User not found"


model = ChatOpenAI(model="gpt-6.1-sol")
agent = create_agent(
    model,
    tools=[get_account_info],
    context_schema=UserContext,
    checkpointer=InMemorySaver(),
    system_prompt="You are a financial assistant.",
)

thread_id = str(uuid7())
config = {"configurable": {"thread_id": thread_id}}
context = UserContext(user_id="user123")

result = agent.invoke(
    {"messages": [{"role": "user", "content": "What's my current balance?"}]},
    config=config,
    context=context,
)
print(result["messages"][-1].content_blocks)

result = agent.invoke(
    {"messages": [{"role": "user", "content": "What was my balance again?"}]},
    config=config,
    context=context,
)
print(result["messages"][-1].content_blocks)

# 2.3,Long-term memory (Store)

# The BaseStore provides persistent storage that survives across conversations.
# Unlike state (short-term memory), data saved to the store remains available in future sessions.
# Access the store through runtime.store. The store uses a namespace/key pattern to organize data:

from langgraph.store.memory import InMemoryStore
from langchain.agents import create_agent
from langchain.tools import tool, ToolRuntime
from langchain_openai import ChatOpenAI

# Access memory
@tool
def get_user_info(user_id: str, runtime: ToolRuntime) -> str:
    """Look up user info."""
    store = runtime.store
    user_info = store.get(("users",), user_id)
    return str(user_info.value) if user_info else "Unknown user"

# Update memory
@tool
def save_user_info(user_id: str, name: str, age: int, email: str, runtime: ToolRuntime) -> str:
    """Save user info."""
    store = runtime.store
    store.put(("users",), user_id, {"name": name, "age": age, "email": email})
    return "Successfully saved user info."

model = ChatOpenAI(model="gpt-6.1-sol")

store = InMemoryStore()
agent = create_agent(
    model,
    tools=[get_user_info, save_user_info],
    store=store
)

# First session: save user info
agent.invoke({
    "messages": [{"role": "user", "content": "Save the following user: userid: abc123, name: Foo, age: 25, email: foo@langchain.dev"}]
})

# Second session: get user info
agent.invoke({
    "messages": [{"role": "user", "content": "Get user info for user with id 'abc123'"}]
})
# Here is the user info for user with ID "abc123":
# - Name: Foo
# - Age: 25
# - Email: foo@langchain.dev

# 2.4,Stream writer
 # Stream real-time updates from tools during execution.
# This is useful for providing progress feedback to users during long-running operations.
# Use runtime.stream_writer to emit custom updates:

from langchain.tools import tool, ToolRuntime

@tool
def get_weather(city: str, runtime: ToolRuntime) -> str:
    """Get weather for a given city."""
    writer = runtime.stream_writer

    # Stream custom updates as the tool executes
    writer(f"Looking up data for city: {city}")
    writer(f"Acquired data for city: {city}")

    return f"It's always sunny in {city}!"

# 2.5,Execution info
# Access thread ID, run ID, and retry state from within a tool via runtime.execution_info:

from langchain.tools import tool, ToolRuntime

@tool
def log_execution_context(runtime: ToolRuntime) -> str:
    """Log execution identity information."""
    info = runtime.execution_info
    print(f"Thread: {info.thread_id}, Run: {info.run_id}")
    print(f"Attempt: {info.node_attempt}")
    return "done"

# 2.6,Server info
# When your tool runs on Agent Server,
# access the assistant ID, graph ID, and authenticated user via runtime.server_info:
from langchain.tools import tool, ToolRuntime

@tool
def get_assistant_scoped_data(runtime: ToolRuntime) -> str:
    """Fetch data scoped to the current assistant."""
    server = runtime.server_info
    if server is not None:
        print(f"Assistant: {server.assistant_id}, Graph: {server.graph_id}")
        if server.user is not None:
            print(f"User: {server.user.identity}")
    return "done"

# 3,Tool execution
# In LangChain, tools are used by agents (for example via create_agent)
# and tool error handling is configured through middleware.
# For LangGraph workflows, tool execution is handled by ToolNode.
# See ToolNode for Graph API usage, including how tools
# can access the current graph state and run-scoped context.

# 3.1,返回字符串
from langchain.tools import tool


@tool
def get_weather(city: str) -> str:
    """Get weather for a city."""
    return f"It is currently sunny in {city}."

# 3.2，返回对象
from langchain.tools import tool


@tool
def get_weather_data(city: str) -> dict:
    """Get structured weather data for a city."""
    return {
        "city": city,
        "temperature_c": 22,
        "conditions": "sunny",
    }

# 3.3，返回Return multimodal content
# Tools are not limited to plain text. When the model supports multimodal tool results,
# the tool can return standard content blocks
# so the model receives text, images, and other media in one tool result.
from langchain.tools import tool


@tool
def capture_screenshot() -> list[dict]:
    """Capture a screenshot of the current page."""
    return [
        {"type": "text", "text": "Screenshot of the current page:"},
        {"type": "image", "url": "https://example.com/page.png"},
    ]


# 3.4，返回命令行
#Return a Command
#Return a Command when the tool needs to update graph state
# (for example, setting user preferences or app state).
# When the Command targets the current graph, include a ToolMessage
# in the update whose tool call ID matches the current tool call.
# Every tool call in the message history must have a corresponding ToolMessage.
#Use runtime.tool_call_id for the tool_call_id parameter.
# ToolNode enforces this requirement:
# if the update has no ToolMessage matching the tool call, it raises a ValueError

from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command


@tool
def set_language(language: str, runtime: ToolRuntime) -> Command:
    """Set the preferred response language."""
    return Command(
        update={
            "preferred_language": language,
            "messages": [
                ToolMessage(
                    content=f"Language set to {language}.",
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )
# Behavior:
# The command updates state using update.
# Updated state is available to subsequent steps in the same run.
# Use reducers for fields that may be updated by parallel tool calls.
# Use this when the tool is not just returning data, but also mutating agent state.

# 3.5，Return directly from a tool
# Set return direct on a tool to short-circuit the agent loop:
# the agent returns the tool’s output to the caller immediately,
# without sending it back through the model for further processing.
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI


@tool(return_direct=True)
def fetch_order_status(order_id: str) -> str:
    """Fetch the current status of a customer order."""
    # In production, query your order management system here
    return f"Order {order_id} is shipped and will arrive in 2 days."


agent = create_agent(
    ChatOpenAI(model="gpt-5.4-mini"),
    tools=[fetch_order_status],
)

result = agent.invoke({
    "messages": [{"role": "user", "content": "What is the status of order #12345?"}]
})
# The agent returns the tool output directly without another LLM call:
# "Order 12345 is shipped and will arrive in 2 days."

# 3.6，Return a Command with return_direct


# A tool with return_direct=True can also return a Command
# to update graph state before the agent exits.
# Unlike a plain return value, a Command is not automatically converted
# into a ToolMessage. When the Command targets the current graph
# (graph is not set or is None), include a ToolMessage in Command.
# update matching the tool call’s tool_call_id. Omitting it causes
# ToolNode to raise a ValueError, because every AIMessage tool call
# must have a corresponding ToolMessage in the message history.

from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command


@tool(return_direct=True)
def fetch_and_store_order(order_id: str, runtime: ToolRuntime) -> Command:
    """Fetch order status and store it in state."""
    status = f"Order {order_id} is shipped and will arrive in 2 days."
    return Command(
        update={
            "last_order_status": status,
            # Must include a ToolMessage so the message history stays valid
            "messages": [
                ToolMessage(
                    content=status,
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )

# 3.7，error handling
# Handle tool errors using LangChain agent middleware to
# retry failed tool calls or return custom error messages:
from collections.abc import Callable

from langchain.agents import create_agent
from langchain.agents.middleware import wrap_tool_call
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest


@wrap_tool_call
def handle_tool_errors(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage],
) -> ToolMessage:
    """Convert tool exceptions into ToolMessages the model can handle."""
    try:
        return handler(request)
    except Exception as e:
        return ToolMessage(
            content=f"Tool error: Please check your input and try again. ({e})",
            tool_call_id=request.tool_call["id"],
        )


agent = create_agent(
    model="google_genai:gemini-4-hydrogen",
    tools=[],
    middleware=[handle_tool_errors],
)


# 3.8 State injection
# Tools access graph state through ToolRuntime.
# See Access context for state, context, store, and streaming APIs

from langchain.tools import tool, ToolRuntime

@tool
def get_message_count(runtime: ToolRuntime) -> str:
    """Get the number of messages in the conversation."""
    messages = runtime.state["messages"]
    return f"There are {len(messages)} messages."

# 4）Dynamic tool selection

# 4.1）Filtering pre-registered tools
# When all possible tools are known at agent creation time,
# you can pre-register them and dynamically filter
# which ones are exposed to the model based on state, permissions, or context.

# state
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse
from typing import Callable

@wrap_model_call
def state_based_tools(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse]
) -> ModelResponse:
    """Filter tools based on conversation State."""
    # Read from State: check if user has authenticated
    state = request.state
    is_authenticated = state.get("authenticated", False)
    message_count = len(state["messages"])

    # Only enable sensitive tools after authentication
    if not is_authenticated:
        tools = [t for t in request.tools if t.name.startswith("public_")]
        request = request.override(tools=tools)
    elif message_count < 5:
        # Limit tools early in conversation
        tools = [t for t in request.tools if t.name != "advanced_search"]
        request = request.override(tools=tools)

    return handler(request)

agent = create_agent(
    model="gpt-6.1-sol",
    tools=[public_search, private_search, advanced_search],
    middleware=[state_based_tools]
)

# store
from dataclasses import dataclass
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse
from typing import Callable
from langgraph.store.memory import InMemoryStore

@dataclass
class Context:
    user_id: str

@wrap_model_call
def store_based_tools(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse]
) -> ModelResponse:
    """Filter tools based on Store preferences."""
    user_id = request.runtime.context.user_id

    # Read from Store: get user's enabled features
    store = request.runtime.store
    feature_flags = store.get(("features",), user_id)

    if feature_flags:
        enabled_features = feature_flags.value.get("enabled_tools", [])
        # Only include tools that are enabled for this user
        tools = [t for t in request.tools if t.name in enabled_features]
        request = request.override(tools=tools)

    return handler(request)

agent = create_agent(
    model="gpt-6.1-sol",
    tools=[search_tool, analysis_tool, export_tool],
    middleware=[store_based_tools],
    context_schema=Context,
    store=InMemoryStore()
)

# runtime context
from dataclasses import dataclass
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse
from typing import Callable

@dataclass
class Context:
    user_role: str

@wrap_model_call
def context_based_tools(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse]
) -> ModelResponse:
    """Filter tools based on Runtime Context permissions."""
    # Read from Runtime Context: get user role
    if request.runtime is None or request.runtime.context is None:
        # If no context provided, default to viewer (most restrictive)
        user_role = "viewer"
    else:
        user_role = request.runtime.context.user_role

    if user_role == "admin":
        # Admins get all tools
        pass
    elif user_role == "editor":
        # Editors can't delete
        tools = [t for t in request.tools if t.name != "delete_data"]
        request = request.override(tools=tools)
    else:
        # Viewers get read-only tools
        tools = [t for t in request.tools if t.name.startswith("read_")]
        request = request.override(tools=tools)

    return handler(request)

agent = create_agent(
    model="gpt-6.1-sol",
    tools=[read_data, write_data, delete_data],
    middleware=[context_based_tools],
    context_schema=Context
)

# 4.2)Runtime tool registration

# When tools are discovered or created at runtime
# (e.g., loaded from an MCP server, generated based on user data,
# or fetched from a remote registry),
# you need to both register the tools and handle their execution dynamically.
# This requires two middleware hooks:
# wrap_model_call - Add the dynamic tools to the request
# wrap_tool_call - Handle execution of the dynamically added tools

from langchain.tools import tool
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRequest, ToolCallRequest

# A tool that will be added dynamically at runtime
@tool
def calculate_tip(bill_amount: float, tip_percentage: float = 20.0) -> str:
    """Calculate the tip amount for a bill."""
    tip = bill_amount * (tip_percentage / 100)
    return f"Tip: ${tip:.2f}, Total: ${bill_amount + tip:.2f}"

class DynamicToolMiddleware(AgentMiddleware):
    """Middleware that registers and handles dynamic tools."""

    def wrap_model_call(self, request: ModelRequest, handler):
        # Add dynamic tool to the request
        # This could be loaded from an MCP server, database, etc.
        updated = request.override(tools=[*request.tools, calculate_tip])
        return handler(updated)

    def wrap_tool_call(self, request: ToolCallRequest, handler):
        # Handle execution of the dynamic tool
        if request.tool_call["name"] == "calculate_tip":
            return handler(request.override(tool=calculate_tip))
        return handler(request)

agent = create_agent(
    model="gpt-6.1-sol",
    tools=[get_weather],  # Only static tools registered here
    middleware=[DynamicToolMiddleware()],
)

# The agent can now use both get_weather AND calculate_tip
result = agent.invoke({
    "messages": [{"role": "user", "content": "Calculate a 20% tip on $85"}]
})

# 5) Headless tools
# Some tools should run where your user’s app runs (typically the browser),
# not inside the process. Headless tools are tool definitions,
# which include the name, description, and argument schema,
# that you register on the server with your agent.
# The implementation is registered only on the client
# and executed after a short interrupt/resume handshake.
# This is different from ordinary tools whose function body runs
# on the server, and from server-side tool use
# where the model provider executes built-in tools remotely.

# 5.1,When to use headless tools
# Use them when the work depends on the environment, device, or UI that only exists on the client. For example:
# Browser APIs: Geolocation, IndexedDB, Clipboard, Canvas 2D, file pickers, Battery API, etc.
# Privacy and locality: Data stays on the device (for example, local “memory” in IndexedDB).
# Latency: No extra server round trip for purely local operations.
# Structured, safe effects: Prefer many small, typed tools (for example one tool per canvas primitive) instead of sending arbitrary code to eval.

# 5.2,How the pattern works
# In both runtimes, the model sees a normal tool it can call, but the actual execution happens outside the server process.
# Define a headless tool with tool(name=..., description=..., args_schema=...) from langchain.tools. A headless tool is schema-only, with no in-process implementation.
# Register that tool with create_agent or your LangGraph graph so the model can call it normally.
# Handle the interrupt payload when the tool is invoked. Instead of running locally, the graph pauses with a payload shaped like {"type": "tool", "tool_call": {"id", "name", "args"}}.
# Resume the graph after your app, another service, or a human step performs the action. For browser-based flows, you can mirror the schema in the frontend and attach .implement(...) there.


# 6)Prebuilt tools
# LangChain provides a large collection of prebuilt tools and toolkits for common tasks like web search, code interpretation, database access, and more. These ready-to-use tools can be directly integrated into your agents without writing custom code.
# See the tools and toolkits integration page for a complete list of available tools organized by category.

# 7) Tools from MCP servers

# Model Context Protocol (MCP) is an open protocol
# that standardizes how applications expose tools to language models.
# Rather than hand-authoring a tool, you connect to an MCP server and adapt the tools
# it advertises into LangChain tools, ready to pass to an agent like any other tool.
# MCPAdapter discovers a server’s tools and converts them
# into LangChain tools. Open the adapter, call list_tools(), and hand the result to create_agent:

from langchain.agents import create_agent
from langchain.mcp import MCPAdapter

async with MCPAdapter("https://example.com/mcp") as adapter:
    tools = await adapter.list_tools()
    agent = create_agent("claude-sonnet-4-6", tools)

# 8) Server-side tool use

# Some chat models feature built-in tools that are executed server-side
# by the model provider. These include capabilities
# like web search and code interpreters that don’t
# require you to define or host the tool logic.
# Refer to the individual chat model
# integration pages and the tool calling documentation
# for details on enabling and using these built-in tools.