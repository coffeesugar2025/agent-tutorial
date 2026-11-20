"""Ollama 本地模型 HTTP 客户端。

刻意不用官方 SDK，直接用 httpx 打 REST 接口，目的是让你**看见协议本身**：
生产里换 DeepSeek / Qwen / GLM / vLLM 的 OpenAI 兼容端点，只改 URL 和请求体字段名。

常用端点（以本机 ollama --version / 官方文档为准，本文件做了兼容）：
  GET  /api/tags              列出本地模型
  POST /api/chat              多轮对话，支持 stream / format=json
  POST /api/generate          单轮生成
  POST /api/embed             批量向量（新版）
  POST /api/embeddings        单条向量（旧版，兼容用）
"""
from __future__ import annotations

import httpx

from . import config


class OllamaError(RuntimeError):
    pass


def is_available(timeout: float = 1.5) -> bool:
    """探测本机 Ollama 是否在线。探测失败就走离线演示模式。"""
    try:
        r = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def list_models(timeout: float = 2.0) -> list[str]:
    try:
        r = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=timeout)
        r.raise_for_status()
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return []


def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.0,
    timeout: float | None = None,
) -> str:
    """多轮对话。json_mode=True 时请求结构化输出（Ollama 的 format: "json"）。"""
    body: dict = {
        "model": model or config.OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if json_mode:
        body["format"] = "json"
    try:
        r = httpx.post(
            f"{config.OLLAMA_BASE_URL}/api/chat",
            json=body,
            timeout=timeout or config.OLLAMA_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")
    except Exception as exc:  # 交给上层做重试 / 降级
        raise OllamaError(f"Ollama /api/chat 调用失败: {exc}") from exc


def embed(texts: list[str], *, model: str | None = None, timeout: float | None = None) -> list[list[float]]:
    """批量向量化。先试新版 /api/embed，失败回退旧版 /api/embeddings 逐条调用。"""
    mdl = model or config.OLLAMA_EMBED_MODEL
    tmo = timeout or config.OLLAMA_TIMEOUT
    try:
        r = httpx.post(
            f"{config.OLLAMA_BASE_URL}/api/embed",
            json={"model": mdl, "input": texts},
            timeout=tmo,
        )
        r.raise_for_status()
        vecs = r.json().get("embeddings")
        if vecs and len(vecs) == len(texts):
            return [[float(x) for x in v] for v in vecs]
    except Exception:
        pass
    # 旧版兼容
    out: list[list[float]] = []
    for text in texts:
        r = httpx.post(
            f"{config.OLLAMA_BASE_URL}/api/embeddings",
            json={"model": mdl, "prompt": text},
            timeout=tmo,
        )
        r.raise_for_status()
        out.append([float(x) for x in r.json()["embedding"]])
    return out
