# 1)初始化模型

import os
from langchain.chat_models import init_chat_model

os.environ["OPENAI_API_KEY"] = "sk-..."

model = init_chat_model("gpt-6.1-sol")
# 2)模型的核心方法

# 2.1)invoke方法
response = model.invoke("Why do parrots have colorful feathers?")
print(response)

conversation = [
    {"role": "system", "content": "You are a helpful assistant that translates English to French."},
    {"role": "user", "content": "Translate: I love programming."},
    {"role": "assistant", "content": "J'adore la programmation."},
    {"role": "user", "content": "Translate: I love building applications."}
]

# 或者
from langchain.messages import HumanMessage, AIMessage, SystemMessage

conversation = [
    SystemMessage("You are a helpful assistant that translates English to French."),
    HumanMessage("Translate: I love programming."),
    AIMessage("J'adore la programmation."),
    HumanMessage("Translate: I love building applications.")
]

response = model.invoke(conversation)
print(response)  # AIMessage("J'adore créer des applications.")

response = model.invoke(conversation)
print(response)  # AIMessage("J'adore créer des applications.")
# 2.2)stream方法

for chunk in model.stream("Why do parrots have colorful feathers?"):
    print(chunk.text, end="|", flush=True)

full = None  # None | AIMessageChunk
for chunk in model.stream("What color is the sky?"):
    full = chunk if full is None else full + chunk
    print(full.text)

# The
# The sky
# The sky is
# The sky is typically
# The sky is typically blue
# ...

print(full.content_blocks)
# [{"type": "text", "text": "The sky is typically blue..."}]


# 2.3)batch方法

responses = model.batch([
    "Why do parrots have colorful feathers?",
    "How do airplanes fly?",
    "What is quantum computing?"
])
list_of_inputs = [
    "Why do parrots have colorful feathers?",
    "How do airplanes fly?",
    "What is quantum computing?"
]
model.batch(
    list_of_inputs,
    config={
        'max_concurrency': 5,  # Limit to 5 parallel calls
    }
)
for response in responses:
    print(response)

# 3)Tool calling

from langchain.tools import tool


@tool
def get_weather(location: str) -> str:
    """Get the weather at a location."""
    return f"It's sunny in {location}."


model_with_tools = model.bind_tools([get_weather])

response = model_with_tools.invoke("What's the weather like in Boston?")
for tool_call in response.tool_calls:
    # View tool calls made by the model
    print(f"Tool: {tool_call['name']}")
    print(f"Args: {tool_call['args']}")

# 3.1)Tool execution loop
# Bind (potentially multiple) tools to the model
tools = [get_weather]
tools_by_name = {tool.name: tool for tool in tools}
model_with_tools = model.bind_tools(tools)

# Step 1: Model generates tool calls
messages = [{"role": "user", "content": "What's the weather in Boston?"}]
ai_msg = model_with_tools.invoke(messages)
messages.append(ai_msg)

# Step 2: Execute tools and collect results
for tool_call in ai_msg.tool_calls:
    # Execute the tool with the generated arguments
    tool = tools_by_name[tool_call["name"]]
    tool_result = tool.invoke(tool_call)
    messages.append(tool_result)

# Step 3: Pass results back to model for final response
final_response = model_with_tools.invoke(messages)
print(final_response.text)
# "The current weather in Boston is 72°F and sunny."
# 3.2)Forcing tool calls

model_with_tools = model.bind_tools([tools], tool_choice="any")
model_with_tools = model.bind_tools([tools], tool_choice="tool_1")

# 3.3)Parallel tool calls

tools = [get_weather]
tools_by_name = {tool.name: tool for tool in tools}
model_with_tools = model.bind_tools(tools)

response = model_with_tools.invoke(
    "What's the weather in Boston and Tokyo?"
)

# The model may generate multiple tool calls
print(response.tool_calls)
# [
#   {'name': 'get_weather', 'args': {'location': 'Boston'}, 'id': 'call_1'},
#   {'name': 'get_weather', 'args': {'location': 'Tokyo'}, 'id': 'call_2'},
# ]


# Execute all tools (can be done in parallel with async)
results = []
for tool_call in response.tool_calls:
    tool = tools_by_name[tool_call["name"]]
    result = tool.invoke(tool_call)
    results.append(result)

# 3.4)Streaming tool calls

for chunk in model_with_tools.stream(
        "What's the weather in Boston and Tokyo?"
):
    # Tool call chunks arrive progressively
    for tool_chunk in chunk.tool_call_chunks:
        if name := tool_chunk.get("name"):
            print(f"Tool: {name}")
        if id_ := tool_chunk.get("id"):
            print(f"ID: {id_}")
        if args := tool_chunk.get("args"):
            print(f"Args: {args}")

# Output:
# Tool: get_weather
# ID: call_SvMlU1TVIZugrFLckFE2ceRE
# Args: {"lo
# Args: catio
# Args: n": "B
# Args: osto
# Args: n"}
# Tool: get_weather
# ID: call_QMZdy6qInx13oWKE7KhuhOLR
# Args: {"lo
# Args: catio
# Args: n": "T
# Args: okyo
# Args: "}


# 3.5) Structured output


# 第一种，Pydantic models
from pydantic import BaseModel, Field


class Movie(BaseModel):
    """A movie with details."""
    title: str = Field(description="The title of the movie")
    year: int = Field(description="The year the movie was released")
    director: str = Field(description="The director of the movie")
    rating: float = Field(description="The movie's rating out of 10")


model_with_structure = model.with_structured_output(Movie)
response = model_with_structure.invoke("Provide details about the movie Inception")
print(response)  # Movie(title="Inception", year=2010, director="Christopher Nolan", rating=8.8)

# 第二种，TypedDict

from typing_extensions import TypedDict, Annotated


class MovieDict(TypedDict):
    """A movie with details."""
    title: Annotated[str, ..., "The title of the movie"]
    year: Annotated[int, ..., "The year the movie was released"]
    director: Annotated[str, ..., "The director of the movie"]
    rating: Annotated[float, ..., "The movie's rating out of 10"]


model_with_structure = model.with_structured_output(MovieDict)
response = model_with_structure.invoke("Provide details about the movie Inception")
print(response)  # {'title': 'Inception', 'year': 2010, 'director': 'Christopher Nolan', 'rating': 8.8}

# 第三种，JSON Schema

import json

json_schema = {
    "title": "Movie",
    "description": "A movie with details",
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "The title of the movie"
        },
        "year": {
            "type": "integer",
            "description": "The year the movie was released"
        },
        "director": {
            "type": "string",
            "description": "The director of the movie"
        },
        "rating": {
            "type": "number",
            "description": "The movie's rating out of 10"
        }
    },
    "required": ["title", "year", "director", "rating"]
}

model_with_structure = model.with_structured_output(
    json_schema,
    method="json_schema",
)
response = model_with_structure.invoke("Provide details about the movie Inception")
print(response)  # {'title': 'Inception', 'year': 2010, ...}

# 第四种，
# It can be useful to return the raw AIMessage object alongside the parsed representation
# to access response metadata such as token counts. To do this, set include_raw=True when calling with_structured_output


from pydantic import BaseModel, Field


class Movie(BaseModel):
    """A movie with details."""
    title: str = Field(description="The title of the movie")
    year: int = Field(description="The year the movie was released")
    director: str = Field(description="The director of the movie")
    rating: float = Field(description="The movie's rating out of 10")


model_with_structure = model.with_structured_output(Movie, include_raw=True)
response = model_with_structure.invoke("Provide details about the movie Inception")
response
# {
#     "raw": AIMessage(...),
#     "parsed": Movie(title=..., year=..., ...),
#     "parsing_error": None,
# }

# 第5种，
from typing_extensions import Annotated, TypedDict


class Actor(TypedDict):
    name: str
    role: str


class MovieDetails(TypedDict):
    title: str
    year: int
    cast: list[Actor]
    genres: list[str]
    budget: Annotated[float | None, ..., "Budget in millions USD"]


model_with_structure = model.with_structured_output(MovieDetails)

# 或者
from pydantic import BaseModel, Field


class Actor(BaseModel):
    name: str
    role: str


class MovieDetails(BaseModel):
    title: str
    year: int
    cast: list[Actor]
    genres: list[str]
    budget: float | None = Field(None, description="Budget in millions USD")


model_with_structure = model.with_structured_output(MovieDetails)

# 第六种，返回异常捕捉
from langchain_core.exceptions import ModelRefusalError

model_with_structure = model.with_structured_output(Movie)

try:
    response = model_with_structure.invoke("Provide details about the movie Inception")
except ModelRefusalError as error:
    print(error)  # Model refused to produce the requested output (category='cyber'): ...
    refused = error.raw_message
# 或者
model_with_structure = model.with_structured_output(Movie, include_raw=True)
response = model_with_structure.invoke("Provide details about the movie Inception")
if isinstance(response["parsing_error"], ModelRefusalError):
    refused = response["raw"]

# 4）高级主题

# 4.1)动态模型选择
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse

basic_model = ChatOpenAI(model="gpt-5.4-mini")
advanced_model = ChatOpenAI(model="gpt-6.1-sol")


@wrap_model_call
def dynamic_model_selection(request: ModelRequest, handler) -> ModelResponse:
    """Choose model based on conversation complexity."""
    message_count = len(request.state["messages"])

    if message_count > 10:
        # Use an advanced model for longer conversations
        model = advanced_model
    else:
        model = basic_model

    return handler(request.override(model=model))


agent = create_agent(
    model=basic_model,  # Default model
    tools=[],
    middleware=[dynamic_model_selection]
)

# 4.2，Configurable models

# You can also create a runtime-configurable model
# by specifying configurable_fields.
# If you don’t specify a model value,
# then 'model' and 'model_provider' will be configurable by default

from langchain.chat_models import init_chat_model

configurable_model = init_chat_model(temperature=0)

configurable_model.invoke(
    "what's your name",
    config={"configurable": {"model": "gpt-5-nano"}},  # Run with GPT-5-Nano
)
configurable_model.invoke(
    "what's your name",
    config={"configurable": {"model": "claude-sonnet-4-6"}},  # Run with Claude
)

# We can create a configurable model with default model values,
# specify which parameters are configurable, and add prefixes to configurable params:
first_model = init_chat_model(
    model="gpt-5.4-mini",
    temperature=0,
    configurable_fields=("model", "model_provider", "temperature", "max_tokens"),
    config_prefix="first",  # Useful when you have a chain with multiple models
)

first_model.invoke(
    "what's your name",
    config={
        "configurable": {
            "first_model": "claude-sonnet-4-6",
            "first_temperature": 0.5,
            "first_max_tokens": 100,
        }
    },
)

# We can call declarative operations like bind_tools, with_structured_output,
# with_configurable, etc. on a configurable model and chain a configurable model in the same way
# that we would a regularly instantiated chat model object.
from pydantic import BaseModel, Field


class GetWeather(BaseModel):
    """Get the current weather in a given location"""

    location: str = Field(description="The city and state, e.g. San Francisco, CA")


class GetPopulation(BaseModel):
    """Get the current population in a given location"""

    location: str = Field(description="The city and state, e.g. San Francisco, CA")


model = init_chat_model(temperature=0)
model_with_tools = model.bind_tools([GetWeather, GetPopulation])

model_with_tools.invoke(
    "what's bigger in 2024 LA or NYC", config={"configurable": {"model": "gpt-5.4-mini"}}
).tool_calls

first_model.invoke("what's your name")

model_with_tools.invoke(
    "what's bigger in 2024 LA or NYC",
    config={"configurable": {"model": "claude-sonnet-4-6"}},
).tool_calls


# 4.3) Invocation config
# When invoking a model, you can pass additional configuration through the config parameter
# using a RunnableConfig dictionary.
# This provides run-time control over execution behavior, callbacks, and metadata tracking.
# Common configuration options include:

def my_callback_handler():
    pass


response = model.invoke(
    "Tell me a joke",
    config={
        "run_name": "joke_generation",  # Custom name for this run
        "tags": ["humor", "demo"],  # Tags for categorization
        "metadata": {"user_id": "123"},  # Custom metadata
        "callbacks": [my_callback_handler],  # Callback handlers
    }
)

# These configuration values are particularly useful when:
# Debugging with LangSmith tracing
# Implementing custom logging or monitoring
# Controlling resource usage in production
# Tracking invocations across complex pipelines




# 4.4)Token usage

# A number of model providers return token usage information as part of the invocation response.
# When available, this information will be included on the AIMessage objects produced by the corresponding model.
# For more details, see the messages guide.

# You can track aggregate token counts across models in an application using either a callback or context manager, as shown below:


# callback
from langchain.chat_models import init_chat_model
from langchain_core.callbacks import UsageMetadataCallbackHandler

model_1 = init_chat_model(model="gpt-5.4-mini")
model_2 = init_chat_model(model="claude-haiku-4-5-20251001")

callback = UsageMetadataCallbackHandler()
result_1 = model_1.invoke("Hello", config={"callbacks": [callback]})
result_2 = model_2.invoke("Hello", config={"callbacks": [callback]})
print(callback.usage_metadata)

# context manager
from langchain.chat_models import init_chat_model
from langchain_core.callbacks import get_usage_metadata_callback

model_1 = init_chat_model(model="gpt-5.4-mini")
model_2 = init_chat_model(model="claude-haiku-4-5-20251001")

with get_usage_metadata_callback() as cb:
    model_1.invoke("Hello")
    model_2.invoke("Hello")
    print(cb.usage_metadata)


# 4.5) Log probabilities
# Certain models can be configured to return token-level log probabilities
# representing the likelihood of a given token by setting the logprobs parameter when initializing the model:
model = init_chat_model(
    model="gpt-6.1-sol",
    model_provider="openai"
).bind(logprobs=True)

response = model.invoke("Why do parrots talk?")
print(response.response_metadata["logprobs"])


# 4.6) Base URL and proxy settings
# You can configure a custom base URL for providers that implement the OpenAI Chat Completions API.

# BASE_URL
model = init_chat_model(
    model="MODEL_NAME",
    model_provider="openai",
    base_url="BASE_URL",
    api_key="YOUR_API_KEY",
)

# HTTP proxy configuration

from langchain_openai import ChatOpenAI

model = ChatOpenAI(
    model="gpt-6.1-sol",
    openai_proxy="http://proxy.example.com:8080"
)



# 4.7) Rate limiting
# Many chat model providers impose a limit on the number of invocations
# that can be made in a given time period. If you hit a rate limit,
# you will typically receive a rate limit error response from the provider,
# and will need to wait before making more requests.
# To help manage rate limits, chat model integrations accept a rate_limiter parameter
# that can be provided during initialization to control the rate at which requests are made.
from langchain.rate_limiters import InMemoryRateLimiter

rate_limiter = InMemoryRateLimiter(
    requests_per_second=0.1,  # 1 request every 10s
    check_every_n_seconds=0.1,  # Check every 100ms whether allowed to make a request
    max_bucket_size=10,  # Controls the maximum burst size.
)

model = init_chat_model(
    model="gpt-6.1-sol",
    model_provider="openai",
    rate_limiter=rate_limiter
)

# 4.8) Model exceptions
# Major integration packages raise standard exception types from langchain_core.exceptions for common model failures
# such as authentication errors, rate limits, and timeouts.
# These exceptions inherit from both the LangChain base type and the provider
# SDK’s own exception type, so you can catch either one:

from langchain.chat_models import init_chat_model
from langchain_core.exceptions import ModelTimeoutError

model = init_chat_model("openai:gpt-5.6-luna", timeout=0.0001)

try:
    response = model.invoke("Hello")
except ModelTimeoutError:
    print("caught")


# 4.9) Server-side tool use
# Some providers support server-side tool-calling loops:
# models can interact with web search, code interpreters, and other tools
# and analyze the results in a single conversational turn.
# If a model invokes a tool server-side, the content of the response
# message will include content representing the invocation and result of the tool.
# Accessing the content blocks of the response will return the server-side tool calls
# and results in a provider-agnostic format:

from langchain.chat_models import init_chat_model

model = init_chat_model("gpt-5.4-mini")

tool = {"type": "web_search"}
model_with_tools = model.bind_tools([tool])

response = model_with_tools.invoke("What was a positive news story from today?")
print(response.content_blocks)


# 4.10) Prompt caching
# Many providers offer prompt caching features to reduce latency and cost on repeat processing of the same tokens. You can engage caching at three levels:
# Implicit provider caching: providers automatically pass on cost savings if a request hits a cache, with no configuration required. Examples: OpenAI and Gemini.
# Provider-level explicit controls: providers let you manually indicate cache points for greater control or to guarantee cost savings. These mirror the underlying provider/API behavior. Examples:
# ChatOpenAI (via prompt_cache_key)
# Anthropic content-block cache_control
# Gemini.
# AWS Bedrock cachePoint blocks
# LangChain middleware: for agents, middleware lets LangChain optimize caching of stable system prompt and tool content. Examples:
# Anthropic’s AnthropicPromptCachingMiddleware
# AWS Bedrock’s BedrockPromptCachingMiddleware


# 4.11) Local models
# LangChain supports running models locally on your own hardware.
# This is useful for scenarios where either data privacy is critical,
# you want to invoke a custom model, or when you want to avoid the costs incurred when using a cloud-based model.
# Ollama is one of the easiest ways to run chat and embedding models locally.


# 4.12) Reasoning
# Many models are capable of performing multi-step reasoning to arrive at a conclusion.
# This involves breaking down complex problems into smaller, more manageable steps.
# If supported by the underlying model, you can surface this reasoning process to better understand
# how the model arrived at its final answer.

for chunk in model.stream("Why do parrots have colorful feathers?"):
    reasoning_steps = [r for r in chunk.content_blocks if r["type"] == "reasoning"]
    print(reasoning_steps if reasoning_steps else chunk.text)

from langchain_anthropic import ChatAnthropic

model = ChatAnthropic(model="claude-sonnet-4-6")
response = model.invoke(
    "Why do parrots have colorful feathers?",
    reasoning_effort="high",
)

# Supported effort levels and the provider’s documented default vary by model.
# Check a model’s profile for the levels it supports and its default:

model.profile["reasoning_effort_levels"]  # e.g. ['low', 'medium', 'high']
model.profile["reasoning_effort_default"]  # e.g. 'high'


# 4.13) Multimodal
# Certain models can process and return non-textual data such as images, audio, and video.
# You can pass non-textual data to a model by providing content blocks.
# Some models can return multimodal data as part of their response.
# If invoked to do so, the resulting AIMessage will have content blocks with multimodal types.

response = model.invoke("Create a picture of a cat")
print(response.content_blocks)
# [
#     {"type": "text", "text": "Here's a picture of a cat"},
#     {"type": "image", "base64": "...", "mime_type": "image/jpeg"},
# ]

# 4.14) Model profiles

# LangChain chat models can expose a dictionary of supported features and capabilities through a profile attribute:
# LangChain chat models can expose a dictionary of supported features and capabilities through a profile attribute:
model.profile
# {
#   "max_input_tokens": 400000,
#   "image_inputs": True,
#   "reasoning_output": True,
#   "tool_calling": True,
#   ...
# }

custom_profile = {
    "max_input_tokens": 100_000,
    "tool_calling": True,
    "structured_output": True,
    # ...
}
model = init_chat_model("...", profile=custom_profile)