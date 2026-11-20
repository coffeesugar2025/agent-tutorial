"""全书统一的 LangChain 模型层。

两个原则：
1. **一切走 LangChain 原语**：模型、工具、提示词、解析器、Agent、Graph，都从 langchain / langgraph 里拿，
   不自己造 HTTP 客户端。
2. **没有 API Key 也能跑通全流程**：用一个脚本驱动的假模型（`ScriptedChatModel`）替代真模型。
   它是 LangChain 官方 `FakeMessagesListChatModel` 的子类，能返回带 `tool_calls` 的 AIMessage，
   所以 `create_agent` 的工具循环、`astream_events` 的流式事件、`with_structured_output`
   的结构化解析 —— 全都真实发生，只是"模型"是剧本。

接真模型：
    复制 demos/.env.example 为 demos/.env，填 LLM_BASE_URL / LLM_MODEL / LLM_API_KEY。
    任何 OpenAI 兼容服务都行：DeepSeek、Qwen、GLM、vLLM、Ollama、Xinference …
"""

from __future__ import annotations

import os
import pathlib

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

# ------------------------------------------------------------------ .env
def load_env(path: str | pathlib.Path | None = None) -> None:
    """极简 .env 解析（不引入 python-dotenv）。

    只支持 `KEY=VALUE` 与 `#` 注释，够用；已存在的环境变量不覆盖。
    """
    path = pathlib.Path(path) if path else pathlib.Path(__file__).resolve().parents[1] / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


# ------------------------------------------------------------------ 假模型
class ScriptedChatModel(FakeMessagesListChatModel):
    """剧本驱动的假模型：按顺序吐出预设的 AIMessage。

    和普通假模型的区别只有一处：
      - 覆盖 `bind_tools` / `bind`，让 `create_agent`、`with_structured_output` 能正常绑定。
        （真模型这里会发一份 tools schema 给服务端；假模型不需要，原样返回自己。）

    剧本里可以放两类消息：
      - `ai_tool("get_employee", {"emp_id": "E10086"})`  → 触发一次工具调用
      - `ai_text("张伟在技术中心")`                      → 直接给出最终答案
    """

    def bind_tools(self, tools, **kwargs):  # noqa: D401
        return self

    def bind(self, **kwargs):
        return self


def ai_tool(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    """剧本项：调用工具。"""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}])


def ai_text(text: str) -> AIMessage:
    """剧本项：直接回答。"""
    return AIMessage(content=text)


# ------------------------------------------------------------------ 工厂
_HINTED = False


def has_real_model() -> bool:
    load_env()
    key = os.getenv("LLM_API_KEY", "")
    return bool(key) and not key.startswith("sk-你的") and os.getenv("LLM_PROVIDER", "") != "mock"


def get_model(script: list | None = None, temperature: float = 0.0) -> BaseChatModel:
    """拿到一个聊天模型。有 Key 用真模型，没 Key 用剧本假模型。

    参数
      script: 仅假模型使用，按顺序消费的 AIMessage 列表
      temperature: 仅真模型使用（假模型无意义）
    """
    global _HINTED
    load_env()

    if has_real_model():
        from langchain_openai import ChatOpenAI   # 延迟 import：没装 openai 也能跑假模型

        return ChatOpenAI(
            model=os.getenv("LLM_MODEL", "deepseek-chat"),
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1"),
            api_key=os.getenv("LLM_API_KEY"),
            temperature=temperature,
        )

    if not _HINTED:
        print("[提示] 没检测到 LLM_API_KEY，已切换到 ScriptedChatModel（剧本假模型）。")
        print("       剧本里的 tool_calls / 结构化输出都是真实走完 LangChain 链路的。")
        _HINTED = True
    return ScriptedChatModel(responses=script or [ai_text("（空剧本）")])


# ------------------------------------------------------------------ 叙事输出
BAR = "=" * 66


def title(text: str, sub: str | None = None) -> None:
    print(BAR)
    print(text)
    if sub:
        print(sub)
    print(BAR)


def section(text: str) -> None:
    print()
    print(f"--- {text} " + "-" * max(0, 60 - len(text)))


def star(text: str) -> None:
    """★ 打在教学重点上，全书的惯例。"""
    print(f"  ★ {text}")


def practice(items: list[str]) -> None:
    print()
    print("-" * 66)
    print("动手练习：")
    for i, s in enumerate(items, 1):
        print(f"{i}. {s}")
    print("-" * 66)
