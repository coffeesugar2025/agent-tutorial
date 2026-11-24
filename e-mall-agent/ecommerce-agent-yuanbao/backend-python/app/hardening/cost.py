"""成本工程（总纲 0.5 / 5.8）：每成功任务成本 + 预算终止 + 异常花费检测。

有效成本 = 单任务推理成本 / 成功率 + 人工兜底成本。
之前只有「每任务成本」和按步数终止，死循环烧钱防不住；这里补按金额硬终止。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CostLedger:
    budget_usd: float = 1.0
    spent_usd: float = 0.0
    success: int = 0
    failure: int = 0
    human_handoff: int = 0
    human_cost_usd: float = 0.15
    events: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def charge(self, provider: str, tokens_in: int, tokens_out: int,
               price_in: float, price_out: float) -> dict[str, Any]:
        cost = (tokens_in * price_in + tokens_out * price_out) / 1_000_000
        with self._lock:
            self.spent_usd += cost
            self.events.append({"provider": provider, "cost": round(cost, 8),
                                "tokens_in": tokens_in, "tokens_out": tokens_out,
                                "at": time.time()})
            over = self.spent_usd > self.budget_usd
        return {"cost_usd": round(cost, 8), "spent_usd": round(self.spent_usd, 8),
                "budget_usd": self.budget_usd, "over_budget": over,
                "action": "terminate" if over else "continue"}

    def finish(self, success: bool, human: bool = False) -> None:
        with self._lock:
            self.success += int(success)
            self.failure += int(not success)
            self.human_handoff += int(human)

    @property
    def per_task(self) -> float:
        n = self.success + self.failure
        return round(self.spent_usd / max(1, n), 8)

    @property
    def per_success(self) -> float:
        return round(self.spent_usd / max(1, self.success), 8)

    def effective_cost(self) -> dict[str, Any]:
        n = self.success + self.failure
        rate = self.success / max(1, n)
        human = self.human_handoff * self.human_cost_usd / max(1, n)
        return {"success_rate": round(rate, 4), "inference_per_task": self.per_task,
                "per_success_task": self.per_success,
                "human_fallback_per_task": round(human, 6),
                "effective_cost_usd": round(self.per_task / max(1e-9, rate) + human, 6),
                "formula": "单任务推理成本 / 成功率 + 人工兜底成本"}

    def anomaly(self) -> dict[str, Any]:
        """死循环烧钱检测：短窗口内事件数 / 花费突增。"""
        with self._lock:
            recent = [e for e in self.events if time.time() - e["at"] < 10]
            rapid = len(recent) > 20
            return {"events_last_10s": len(recent), "rapid_spend": rapid,
                    "spent_usd": round(self.spent_usd, 8),
                    "recommendation": "触发金额硬终止并告警" if rapid else "正常"}

    def report(self) -> dict[str, Any]:
        return {"budget_usd": self.budget_usd, "spent_usd": round(self.spent_usd, 8),
                "success": self.success, "failure": self.failure,
                "per_task": self.per_task, "per_success_task": self.per_success,
                **self.effective_cost(), "anomaly": self.anomaly()}


LEDGER = CostLedger()


def optimization_order() -> list[dict[str, str]]:
    return [
        {"priority": 1, "action": "缓存（精确/语义/检索/embedding）", "why": "命中即省 100% 调用"},
        {"priority": 2, "action": "模型路由与级联", "why": "小模型先试，置信不足再升级"},
        {"priority": 3, "action": "精简上下文（压缩/裁剪/动态工具注入）", "why": "输入 token 通常占大头"},
        {"priority": 4, "action": "换更便宜模型 / 量化推理", "why": "最后才动，能力回归风险最高"},
    ]
