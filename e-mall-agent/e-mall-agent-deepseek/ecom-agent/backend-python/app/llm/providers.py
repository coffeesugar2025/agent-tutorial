"""LLM 供应商工厂：统一返回 LangChain ChatModel。

供应商与默认模型：
* ``deepseek``：ChatDeepSeek（缺包时用 ChatOpenAI + base_url 兼容模式）
* ``qwen``：DashScope OpenAI 兼容模式
* ``openai``：官方 / 自建兼容网关
* ``ollama``：本地 Ollama 的 OpenAI 兼容端点（``/v1``）
* ``mock``：确定性 MockChatModel（离线）

所有真实供应商均使用 **懒加载**，缺少 API Key 或依赖时抛
:class:`ProviderUnavailable`，由 ``fallback`` 层切到下一个候选。
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import settings

logger = logging.getLogger(__name__)


class ProviderUnavailable(RuntimeError):
    """供应商不可用（未配置 Key / 依赖缺失 / 初始化失败）。"""


def provider_configured(provider: str) -> bool:
    """是否具备调用条件（本地 ollama 视为已配置）。"""
    provider = provider.lower()
    if provider == "mock":
        return True
    if provider == "deepseek":
        return bool(settings.deepseek_api_key)
    if provider == "qwen":
        return bool(settings.dashscope_api_key)
    if provider == "openai":
        return bool(settings.openai_api_key)
    if provider == "ollama":
        return True
    return False


def default_model(provider: str, fast: bool = False) -> str:
    """供应商的默认模型名（与 docs/00 的环境变量口径一致）。"""
    provider = provider.lower()
    if provider == "deepseek":
        return settings.deepseek_model
    if provider == "qwen":
        return settings.qwen_fast_model if fast else settings.qwen_model
    if provider == "openai":
        return settings.openai_model
    if provider == "ollama":
        return settings.ollama_model
    return "mock-chat"


def _openai_compatible(
    *,
    model: str,
    base_url: str,
    api_key: str,
    temperature: float,
    timeout: float | None = None,
    streaming: bool = True,
) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key or "not-needed",
        temperature=temperature,
        timeout=timeout or settings.llm_request_timeout_seconds,
        max_retries=0,  # 重试由 fallback 层统一负责，避免叠加
        streaming=streaming,
    )


def build_chat_model(
    provider: str | None = None,
    model: str | None = None,
    *,
    temperature: float | None = None,
    streaming: bool = True,
    fast: bool = False,
) -> BaseChatModel:
    """按供应商构建 ChatModel；不支持时抛 ProviderUnavailable。"""
    provider = (provider or settings.effective_primary).lower()
    resolved_model = model or default_model(provider, fast=fast)
    temp = settings.llm_temperature if temperature is None else temperature

    if provider == "mock":
        from app.llm.mock import build_mock_model

        return build_mock_model(temperature=temp)

    if not provider_configured(provider):
        raise ProviderUnavailable(f"供应商 {provider} 未配置 API Key")

    try:
        if provider == "deepseek":
            try:
                from langchain_deepseek import ChatDeepSeek

                return ChatDeepSeek(
                    model=resolved_model,
                    api_key=settings.deepseek_api_key,
                    api_base=settings.deepseek_base_url,
                    temperature=temp,
                    timeout=settings.llm_request_timeout_seconds,
                    max_retries=0,
                    streaming=streaming,
                )
            except ImportError:
                logger.info("langchain_deepseek 未安装，改用 OpenAI 兼容模式连接 DeepSeek")
                return _openai_compatible(
                    model=resolved_model,
                    base_url=settings.deepseek_base_url,
                    api_key=settings.deepseek_api_key,
                    temperature=temp,
                    streaming=streaming,
                )
        if provider == "qwen":
            return _openai_compatible(
                model=resolved_model,
                base_url=settings.dashscope_base_url,
                api_key=settings.dashscope_api_key,
                temperature=temp,
                streaming=streaming,
            )
        if provider == "openai":
            return _openai_compatible(
                model=resolved_model,
                base_url=settings.openai_base_url,
                api_key=settings.openai_api_key,
                temperature=temp,
                streaming=streaming,
            )
        if provider == "ollama":
            base = settings.ollama_base_url.rstrip("/")
            if not base.endswith("/v1"):
                base = f"{base}/v1"
            return _openai_compatible(
                model=resolved_model,
                base_url=base,
                api_key="ollama",
                temperature=temp,
                streaming=streaming,
            )
    except ProviderUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProviderUnavailable(f"构建模型失败 provider={provider} err={exc}") from exc

    raise ProviderUnavailable(f"未知的供应商: {provider}")


def describe_providers() -> list[dict[str, Any]]:
    """``/api/v1/meta/capabilities`` 与排查用：列出供应商可用情况。"""
    rows: list[dict[str, Any]] = []
    for provider in ["deepseek", "qwen", "openai", "ollama", "mock"]:
        rows.append(
            {
                "provider": provider,
                "configured": provider_configured(provider),
                "model": default_model(provider),
                "fastModel": default_model(provider, fast=True),
            }
        )
    return rows


__all__ = [
    "ProviderUnavailable",
    "build_chat_model",
    "default_model",
    "describe_providers",
    "provider_configured",
]
