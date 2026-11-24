"""Prompt 版本化 / hash / 灰度 / 回滚（总纲 5.7 / 9.2 / C#12）。

之前 prompt.py 是代码里的裸字符串，改一行没有 diff、没有 hash、上游模型还会静默升级。
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from typing import Any

from app.agent.prompt import SYSTEM_PROMPT


@dataclass
class PromptVersion:
    prompt_id: str
    version: int
    content: str
    hash: str
    stage: str = "canary"       # canary | stable | rolled_back
    traffic: float = 0.1
    model_pin: str = ""


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]


class PromptRegistry:
    def __init__(self) -> None:
        self._versions: dict[str, list[PromptVersion]] = {}
        self._lock = threading.RLock()
        self.register("system.guide", SYSTEM_PROMPT, stage="stable", traffic=1.0)

    def register(self, prompt_id: str, content: str, stage: str = "canary",
                 traffic: float = 0.1, model_pin: str = "") -> PromptVersion:
        with self._lock:
            seq = self._versions.setdefault(prompt_id, [])
            v = PromptVersion(prompt_id, len(seq) + 1, content, _h(content), stage, traffic, model_pin)
            seq.append(v)
            return v

    def resolve(self, prompt_id: str, bucket: float = 0.5) -> PromptVersion:
        """灰度：稳定版兜底，canary 按 bucket 分流。"""
        with self._lock:
            seq = list(self._versions.get(prompt_id, []))
        if not seq:
            raise KeyError(prompt_id)
        canary = next((v for v in reversed(seq) if v.stage == "canary"), None)
        if canary and bucket < canary.traffic:
            return canary
        stable = next((v for v in reversed(seq) if v.stage == "stable"), None)
        return stable or seq[-1]

    def diff(self, prompt_id: str, a: int, b: int) -> dict[str, Any]:
        with self._lock:
            seq = self._versions.get(prompt_id, [])
        va, vb = next((v for v in seq if v.version == a), None), next((v for v in seq if v.version == b), None)
        if not va or not vb:
            return {"ok": False, "error": "版本不存在"}
        lines_a, lines_b = va.content.splitlines(), vb.content.splitlines()
        changed = [i for i in range(max(len(lines_a), len(lines_b)))
                   if (lines_a[i] if i < len(lines_a) else None) != (lines_b[i] if i < len(lines_b) else None)]
        return {"ok": True, "hash_a": va.hash, "hash_b": vb.hash,
                "changed_lines": changed[:20], "changed_count": len(changed)}

    def promote(self, prompt_id: str, version: int) -> dict[str, Any]:
        with self._lock:
            for v in self._versions.get(prompt_id, []):
                if v.version == version:
                    v.stage, v.traffic = "stable", 1.0
                elif v.stage == "stable":
                    v.stage = "rolled_back"
            return {"prompt_id": prompt_id, "stable": version}

    def spec(self) -> dict[str, Any]:
        with self._lock:
            return {k: [{"version": v.version, "hash": v.hash, "stage": v.stage,
                         "traffic": v.traffic, "model_pin": v.model_pin} for v in vs]
                    for k, vs in self._versions.items()}


REGISTRY = PromptRegistry()


def assert_model_pin(actual: str, expected: str) -> dict[str, Any]:
    """模型版本锁定：上游静默升级直接拒绝启动。"""
    return {"ok": actual == expected, "actual": actual, "expected": expected,
            "action": "启动" if actual == expected else "阻断发布并告警"}
