"""多环境配置隔离：dev / staging / prod profile 与启动前校验。

不修改 ``config.py``：以现有 Settings 为基线，叠加环境默认值、显式覆盖与
``ECOM_*`` 环境变量，再通过 ``validate_or_raise`` 校验各环境必需项。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .config import get_settings


class Environment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"

    @classmethod
    def from_value(cls, value: "Environment | str") -> "Environment":
        if isinstance(value, Environment):
            return value
        return cls(str(value).lower())


class ConfigValidationError(ValueError):
    """环境配置缺少必需项时抛出。"""


_PROFILE_DEFAULTS: dict[str, dict[str, Any]] = {
    Environment.DEV.value: {
        "debug": True, "log_level": "DEBUG", "llm_provider": "offline",
        "strict_security": False,
    },
    Environment.STAGING.value: {
        "debug": False, "log_level": "INFO", "llm_provider": "offline",
        "strict_security": True,
    },
    Environment.PROD.value: {
        "debug": False, "log_level": "WARNING", "llm_provider": "openai",
        "strict_security": True,
    },
}

_REQUIRED: dict[str, tuple[str, ...]] = {
    Environment.DEV.value: (),
    Environment.STAGING.value: ("secret_key",),
    Environment.PROD.value: ("secret_key", "openai_api_key"),
}

_DEV_SECRET = "dev-secret-change-me"
_BOOL_KEYS = {"debug", "strict_security"}
_INT_KEYS = {"rag_top_k", "token_ttl_seconds", "audit_max_entries",
             "context_max_chars", "context_recent_messages"}


def _coerce(key: str, value: Any) -> Any:
    if not isinstance(value, str):
        return value
    if key in _BOOL_KEYS:
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if key in _INT_KEYS:
        try:
            return int(value)
        except ValueError:
            return value
    return value


@dataclass
class ProfileConfig:
    """某一环境的完整配置视图。"""

    environment: Environment
    values: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        environment: Environment | str,
        overrides: Mapping[str, Any] | None = None,
        env_vars: Mapping[str, str] | None = None,
    ) -> None:
        env = Environment.from_value(environment)
        base = dict(get_settings().model_dump())
        values: dict[str, Any] = {**base, **_PROFILE_DEFAULTS[env.value]}
        values.update(dict(overrides or {}))
        source: Mapping[str, str] = env_vars if env_vars is not None else os.environ
        for key, value in source.items():
            if key.startswith("ECOM_") and key != "ECOM_":
                name = key[len("ECOM_"):].lower()
                values[name] = _coerce(name, value)
        self.environment = env
        self.values = values

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.values)

    def validate_or_raise(self) -> bool:
        """校验当前环境必需项；失败时抛出 ``ConfigValidationError``。"""
        missing: list[str] = []
        for key in _REQUIRED[self.environment.value]:
            if not self.values.get(key):
                missing.append(key)
        if (self.environment is Environment.PROD
                and self.values.get("secret_key") == _DEV_SECRET):
            missing.append("secret_key（不可使用开发默认值）")
        if (self.values.get("llm_provider") == "openai"
                and not self.values.get("openai_api_key")):
            if "openai_api_key" not in missing:
                missing.append("openai_api_key")
        if missing:
            raise ConfigValidationError(
                f"{self.environment.value} 环境配置缺失：" + "、".join(missing)
            )
        return True


__all__ = ["Environment", "ProfileConfig", "ConfigValidationError", "validate_or_raise"]


def validate_or_raise(profile: ProfileConfig) -> bool:
    """函数式入口：校验给定 profile 的配置。"""
    return profile.validate_or_raise()
