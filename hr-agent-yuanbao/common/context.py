"""Context：所有 Demo 共用的 LangChain 运行上下文。

本工程**全程使用 LangChain / LangGraph**：模型调用走 BaseChatModel（ChatOllama），
编排走 LCEL Runnable 或 StateGraph，工具走 @tool / ToolNode，检索走 BaseRetriever，
可观测性走 BaseCallbackHandler。Context 只负责四件外围的事：
  1. 决定运行模式（Ollama 真实模型 / 离线教学模型），并提供 chat_model() 入口
  2. Trace（每一步 type + content + meta）——可观测性的最小形态
  3. Metrics（调用次数 / Token 估算 / 耗时）——评测的数据来源
  4. 统一结果封装（result）——前后端契约

【重要】离线教学模型 TeachingChatModel 是实现了 BaseChatModel 的确定性替身，
不是绕过框架：它让 LCEL、bind_tools、ToolNode、interrupt、回调链全部真实执行。
装了 Ollama 后一行配置切到 ChatOllama，链路代码一行不用改。
生产环境必须删掉这个替身，只保留真实模型 + 输出校验。
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable

from . import config, ollama_client

MockValue = str | dict | list | Callable[[str], "str | dict | list"]


@dataclass
class Step:
    type: str          # thought | action | observation | plan | tool | llm | state | hitl | error | memory | retrieve
    content: str
    meta: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S.%f")[:-3])


def _mock_embedding(text: str, dim: int = 64) -> list[float]:
    """离线演示用的确定性伪向量：字符 unigram + bigram 哈希投影。

    它**不是语义模型**，只是让"年假 / 休假 / 年假余额"这类共享字符的文本
    有可复现的相似度，保证 RAG 章节在没有 Ollama 时也能演示召回与融合。
    """
    vec = [0.0] * dim
    clean = "".join(ch for ch in text.lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    grams = list(clean) + [clean[i:i + 2] for i in range(len(clean) - 1)]
    for g in grams:
        h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
        vec[h % dim] += 1.0
        vec[(h >> 8) % dim] += 0.35
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 6) for v in vec]


class Context:
    def __init__(self, chapter: str, *, force_mock: bool | None = None, trace_id: str | None = None):
        self.chapter = chapter
        self.trace_id = trace_id or uuid.uuid4().hex[:12]
        self.started = time.perf_counter()
        self.steps: list[Step] = []
        self.metrics: dict[str, Any] = {
            "llm_calls": 0,
            "tool_calls": 0,
            "embed_calls": 0,
            "tokens_est": 0,
            "retries": 0,
            "errors": 0,
            "duration_ms": 0,
        }
        if force_mock is None:
            offline = config.FORCE_MOCK or not ollama_client.is_available()
        else:
            offline = force_mock
        self.mode = "mock" if offline else "ollama"
        self.trace("state", f"运行模式：{'离线演示（Mock）' if offline else 'Ollama 真实模型'}", mode=self.mode)

    # ---------- Trace / Metrics ----------
    def trace(self, type_: str, content: str, **meta: Any) -> Step:
        step = Step(type=type_, content=str(content), meta=meta)
        self.steps.append(step)
        return step

    def bump(self, key: str, n: int = 1) -> None:
        self.metrics[key] = self.metrics.get(key, 0) + n

    # ---------- LangChain 模型入口（章节编排一律走这里） ----------
    def chat_model(self, role: str = "compose"):
        """返回 LangChain BaseChatModel。

        mock 模式 → TeachingChatModel（同样继承 BaseChatModel，支持 tool_calls）；
        ollama 模式 → langchain_ollama.ChatOllama。
        所有章节的 LCEL 链、bind_tools、StateGraph 节点都只用这个对象。
        """
        from .lc_models import build_chat_model
        return build_chat_model(self.mode, role)

    def embeddings(self):
        """返回 LangChain Embeddings（向量库 / 检索器用）。"""
        from .lc_models import build_embeddings
        return build_embeddings(self.mode)

    # ---------- 兼容数据层（章节编排不再调用） ----------
    def llm(
        self,
        prompt: str,
        *,
        system: str = "你是企业 HR 智能助手，回答准确、简洁、不编造事实。",
        json_mode: bool = False,
        mock: MockValue | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        self.bump("llm_calls")
        self.metrics["tokens_est"] += len(prompt) // 2 + 32
        self.trace("llm", f"调用 LLM（json_mode={json_mode}）", prompt_chars=len(prompt), model=model or config.OLLAMA_MODEL)
        if self.mode == "mock":
            value = mock(prompt) if callable(mock) else mock
            if value is None:
                value = "（离线演示模式：本章未提供预置应答，请检查 Demo 的 mock 参数。）"
            text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
            self.metrics["tokens_est"] += len(text) // 2
            return text
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        text = ollama_client.chat(messages, model=model, json_mode=json_mode, temperature=temperature)
        self.metrics["tokens_est"] += len(text) // 2
        return text

    def llm_json(self, prompt: str, *, mock: MockValue | None = None, **kw: Any) -> dict:
        """结构化输出 + 最基础的容错解析（真实模型常带 ```json 围栏）。"""
        raw = self.llm(prompt, json_mode=True, mock=mock, **kw)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        try:
            data = json.loads(cleaned)
            return data if isinstance(data, dict) else {"data": data}
        except json.JSONDecodeError as exc:
            self.bump("errors")
            self.trace("error", f"JSON 解析失败，返回空结构：{exc}", raw=raw[:200])
            return {}

    def embed(self, texts: list[str], *, mock_vectors: list[list[float]] | None = None) -> list[list[float]]:
        self.bump("embed_calls", len(texts))
        self.trace("retrieve", f"向量化 {len(texts)} 段文本", count=len(texts))
        if self.mode == "mock":
            return mock_vectors or [_mock_embedding(t) for t in texts]
        return ollama_client.embed(texts)

    # ---------- 工具执行统一入口 ----------
    def tool(self, name: str, args: dict, fn: Callable[..., Any]) -> Any:
        """记录工具调用、计时、异常；这是第 2/13 章可靠性演示的挂载点。"""
        self.bump("tool_calls")
        t0 = time.perf_counter()
        self.trace("tool", f"调用工具 {name}", args=args)
        try:
            out = fn(**args)
            self.trace("observation", f"{name} 返回：{str(out)[:220]}", ms=round((time.perf_counter() - t0) * 1000, 2))
            return out
        except Exception as exc:
            self.bump("errors")
            self.trace("error", f"{name} 执行失败：{exc}")
            raise

    # ---------- 结果封装 ----------
    def result(self, answer: str, *, state: dict | None = None, hitl: dict | None = None, **extras: Any) -> dict:
        self.metrics["duration_ms"] = round((time.perf_counter() - self.started) * 1000, 2)
        out: dict[str, Any] = {
            "chapter": self.chapter,
            "mode": self.mode,
            "trace_id": self.trace_id,
            "answer": answer,
            "steps": [asdict(s) for s in self.steps],
            "metrics": self.metrics,
            "state": state or {},
        }
        if hitl:
            out["hitl"] = hitl
        out.update(extras)
        return out
