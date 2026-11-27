# This quickstart shows you
# how to create a fully functional AI agent in just a few minutes


# In the following example you will build a research agent t
# hat can answer questions about text files. Along the way
# you will explore the following concepts:
# 1)Detailed system prompts for better agent behavior
# 2)Create tools that integrate with external data
# 3)Model configuration for consistent responses
# 4)Conversational memory for chat-like interactions
# 5)Deep Agents for built-in features
# 6)Testing your agent


# 1)Detailed system prompts for better agent behavior
SYSTEM_PROMPT = """You are a literary data assistant.

## Capabilities

- `fetch_text_from_url`: loads document text from a URL into the conversation.
Do not guess line counts or positions—ground them in tool results from the saved file."""

# 2)Create tools that integrate with external data

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

# 3)Model configuration for consistent responses
from langchain.chat_models import init_chat_model

import os
from langchain_openai import ChatOpenAI
model = ChatOpenAI(
    model="deepseek-flash",                       # 注意：去掉 "openai:" 前缀
    api_key="sk-827674a122e54cea865b969ec3fad26d",
    base_url="https://api.deepseek.com",
    temperature=0.5,
    timeout=300,
    max_tokens=25000,
)

# 4)Conversational memory for chat-like interactions


from langgraph.checkpoint.memory import InMemorySaver

checkpointer = InMemorySaver()

# 5)Deep Agents for built-in features
from langchain.agents import create_agent
from deepagents import create_deep_agent

agent = create_agent(
    model=model,
    tools=[fetch_text_from_url],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
)

deep_agent = create_deep_agent(
    model=model,
    tools=[fetch_text_from_url],
    system_prompt=SYSTEM_PROMPT,
    checkpointer=checkpointer,
)

content = f"""Project Gutenberg hosts a full plain-text copy of F. Scott Fitzgerald's The Great Gatsby.
URL: https://www.gutenberg.org/files/64317/64317-0.txt

Answer as much as you can:

1) How many lines in the complete Gutenberg file contain the substring `Gatsby` (count lines, not occurrences within a line, each line ends with a line break).
2) The 1-based line number of the first line in the file that contains `Daisy`.
3) A two-sentence neutral synopsis.

Do your best on (1) and (2). If at any point you realize you cannot **verify** an exact answer with
your available tools and reasoning, do not fabricate numbers: use `null` for that field and spell out
the limitation in `how_you_computed_counts`. If you encounter any errors please report what the error was and what the error message was."""

print("Running create_agent...", flush=True)
agent_result = agent.invoke(
    {"messages": [{"role": "user", "content": content}]},
    config={"configurable": {"thread_id": "great-gatsby-lc"}},
)
print("Running create_deep_agent...", flush=True)
deep_agent_result = deep_agent.invoke(
    {"messages": [{"role": "user", "content": content}]},
    config={"configurable": {"thread_id": "great-gatsby-da"}},
)
print("\ncreate_agent:")
print(agent_result["messages"][-1].content_blocks)
print("\ncreate_deep_agent:")
print(deep_agent_result["messages"][-1].content_blocks)


