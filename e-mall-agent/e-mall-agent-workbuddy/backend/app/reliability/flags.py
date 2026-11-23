"""Feature Flag / 灰度 / A-B 分桶：按 user_id 稳定哈希，支持白名单与百分比灰度。"""
from __future__ import annotations

import hashlib
from typing import Iterable

_BUCKETS = 100


class FeatureFlag:
    """单个功能开关。

    分桶公式 ``sha256(salt:name:user_id) % 100`` 对用户稳定、跨功能隔离。
    优先级：关闭 > 白名单 > 百分比灰度；A-B 变体用同一分桶取模选择。
    """

    def __init__(
        self,
        name: str,
        enabled: bool = True,
        rollout: float = 0.0,
        whitelist: Iterable[str] | None = None,
        variants: Iterable[str] | None = None,
        salt: str = "",
    ) -> None:
        if not 0.0 <= rollout <= 1.0:
            raise ValueError("rollout 必须在 [0, 1] 之间")
        self.name = name
        self.enabled = enabled
        self.rollout = rollout
        self.whitelist = set(whitelist or [])
        self.variants = list(variants or [])
        self.salt = salt

    def bucket(self, user_id: str) -> int:
        """返回 0-99 的稳定分桶编号。"""
        raw = f"{self.salt}:{self.name}:{user_id}".encode("utf-8")
        return int(hashlib.sha256(raw).hexdigest()[:8], 16) % _BUCKETS

    def is_enabled(self, user_id: str) -> bool:
        if not self.enabled or not user_id:
            return False
        if user_id in self.whitelist:
            return True
        return self.bucket(user_id) < self.rollout * _BUCKETS

    def variant(self, user_id: str) -> str | None:
        """返回该用户命中的 A-B 变体；未开启或未配置变体返回 None。"""
        if not self.is_enabled(user_id) or not self.variants:
            return None
        return self.variants[self.bucket(user_id) % len(self.variants)]


class FlagRegistry:
    """按名称管理多个 FeatureFlag。"""

    def __init__(self, flags: Iterable[FeatureFlag] | None = None) -> None:
        self._flags: dict[str, FeatureFlag] = {}
        for flag in flags or []:
            self.register(flag)

    def register(self, flag: FeatureFlag) -> FeatureFlag:
        self._flags[flag.name] = flag
        return flag

    def get(self, name: str) -> FeatureFlag | None:
        return self._flags.get(name)

    def is_enabled(self, name: str, user_id: str) -> bool:
        flag = self.get(name)
        return flag.is_enabled(user_id) if flag else False

    def variant(self, name: str, user_id: str) -> str | None:
        flag = self.get(name)
        return flag.variant(user_id) if flag else None

    def names(self) -> list[str]:
        return sorted(self._flags)


def is_enabled(flag: FeatureFlag, user_id: str) -> bool:
    """函数式入口：判断某用户是否命中开关。"""
    return flag.is_enabled(user_id)


def variant(flag: FeatureFlag, user_id: str) -> str | None:
    """函数式入口：返回某用户的 A-B 变体。"""
    return flag.variant(user_id)


__all__ = ["FeatureFlag", "FlagRegistry", "is_enabled", "variant"]
