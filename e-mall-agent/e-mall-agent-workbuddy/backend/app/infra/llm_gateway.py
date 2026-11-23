"""多模型网关：DeepSeek / Qwen 走 OpenAI 兼容协议，缺失依赖时回退离线模型。

不修改 app/llm/factory.py，直接复用其 RuleBasedChatModel 作为统一回退实现。
所有外部 SDK 都是懒加载；status() 会如实说明每个供应商的回退原因。
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from ..llm.factory import RuleBasedChatModel
from .settings import InfraSettings

_DISPLAY_NAMES = {
    "offline": "离线规则模型",
    "deepseek": "DeepSeek",
    "qwen": "通义千问 Qwen",
}
_DEFAULT_MODELS = {
    "offline": "rule-based-offline",
    "deepseek": "deepseek-chat",
    "qwen": "qwen-plus",
}


@dataclass(frozen=True)
class ModelProvider:
    """单个模型供应商的元数据。"""

    name: str
    display_name: str
    base_url: str
    api_key: str
    model: str
    temperature: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        """公开视图：api_key 仅显示是否已配置，不泄露明文。"""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.temperature,
            "api_key_set": bool(self.api_key),
        }


class LLMGateway:
    """按 ECOM_LLM_PROVIDERS 注册供应商，按需创建 LangChain 聊天模型。"""

    def __init__(self, settings: InfraSettings | None = None) -> None:
        self.settings = settings or InfraSettings.from_env()
        self._providers: dict[str, ModelProvider] = {}
        self._init_errors: dict[str, str] = {}
        for name in self.settings.provider_names:
            self._providers[name] = self._build_provider(name)
        # offline 永远是可用兜底：即使 ECOM_LLM_PROVIDERS 只列了外部供应商，
        # 默认提供方仍可能指向 offline（或其无 Key 时需要降级到它）。
        if "offline" not in self._providers:
            self._providers["offline"] = self._build_provider("offline")

    @property
    def default_provider(self) -> str:
        """当前默认供应商名称。"""
        return self.settings.llm_default_provider or "offline"

    def _build_provider(self, name: str) -> ModelProvider:
        key = name.strip().lower()
        if key == "offline":
            return ModelProvider(
                name="offline", display_name=_DISPLAY_NAMES["offline"],
                base_url="local://offline", api_key="",
                model=_DEFAULT_MODELS["offline"], temperature=0.0)
        if key == "deepseek":
            return ModelProvider(
                name="deepseek", display_name=_DISPLAY_NAMES["deepseek"],
                base_url=self.settings.deepseek_base_url,
                api_key=self.settings.deepseek_api_key,
                model=_DEFAULT_MODELS["deepseek"], temperature=0.0)
        if key == "qwen":
            return ModelProvider(
                name="qwen", display_name=_DISPLAY_NAMES["qwen"],
                base_url=self.settings.qwen_base_url,
                api_key=self.settings.qwen_api_key,
                model=_DEFAULT_MODELS["qwen"], temperature=0.0)
        # 未知供应商仍注册占位，创建模型时回退离线，便于平滑上线新供应商
        return ModelProvider(name=key, display_name=key, base_url="",
                             api_key="", model=key, temperature=0.0)

    def list_providers(self) -> list[ModelProvider]:
        """返回已启用的供应商清单（保持配置顺序）。"""
        return list(self._providers.values())

    def get_provider(self, name: str) -> ModelProvider | None:
        """按名称查找供应商，不存在时返回 None。"""
        return self._providers.get((name or "").strip().lower())

    @staticmethod
    def _sdk_available() -> bool:
        return importlib.util.find_spec("langchain_openai") is not None

    def _fallback_reason(self, provider: ModelProvider) -> str | None:
        """推断该供应商无法使用真实模型的原因（offline 视为正常策略）。"""
        if provider.name == "offline":
            return None
        if not provider.api_key:
            return f"{provider.name}: API key 未配置，回退 RuleBasedChatModel"
        if not self._sdk_available():
            return f"{provider.name}: 缺少 langchain-openai SDK，回退 RuleBasedChatModel"
        return self._init_errors.get(provider.name)

    def create_chat_model(self, name: str | None = None) -> BaseChatModel:
        """创建聊天模型；无 key / 无 SDK / 初始化失败时回退 RuleBasedChatModel。"""
        selected = (name or self.default_provider).strip().lower()
        provider = self.get_provider(selected)
        if provider is None:
            raise KeyError(f"未知的模型供应商: {selected}")
        if provider.name == "offline":
            return RuleBasedChatModel()
        reason = self._fallback_reason(provider)
        if reason:
            return RuleBasedChatModel()
        try:
            from langchain_openai import ChatOpenAI  # type: ignore

            model = ChatOpenAI(
                base_url=provider.base_url,
                api_key=provider.api_key,
                model=provider.model,
                temperature=provider.temperature,
            )
        except Exception as exc:  # 可选依赖或参数不兼容
            self._init_errors[provider.name] = (
                f"{provider.name}: 初始化失败({type(exc).__name__})，回退 RuleBasedChatModel")
            return RuleBasedChatModel()
        self._init_errors.pop(provider.name, None)
        return model

    def status(self) -> dict[str, Any]:
        """组件状态：列出每个供应商的激活情况与回退原因。"""
        providers: list[dict[str, Any]] = []
        for provider in self.list_providers():
            reason = self._fallback_reason(provider)
            active = provider.name == "offline" or reason is None
            providers.append({
                **provider.as_dict(),
                "active": active,
                "fallback_reason": reason,
            })
        real_providers = [p for p in self.list_providers() if p.name != "offline"]
        configured = bool(real_providers) and all(p.api_key for p in real_providers)
        active = any(item["active"] and item["name"] != "offline" for item in providers)
        reasons = [item["fallback_reason"] for item in providers if item["fallback_reason"]]
        return {
            "configured": configured,
            "active": active,
            "backend": "openai-compatible" if active else "offline",
            "default_provider": self.default_provider,
            "providers": providers,
            "detail": "; ".join(reasons) if reasons else
                      "所有供应商使用离线规则模型（未启用外部供应商）",
        }
