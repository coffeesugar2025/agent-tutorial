"""可重试错误分类（总纲 5.1）：参数错不该退避重试，限流才该。

之前 reliability.RetryPolicy 默认 retry_on=(Exception,) 会把 422 也重试 3 次。
本模块定义分类表，并把分类接回 RetryPolicy。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RETRYABLE = {"rate_limit", "timeout", "server", "network", "transient", "circuit_half_open"}
NON_RETRYABLE = {"bad_request", "validation", "auth", "permission", "not_found", "quota_hard", "unsupported"}

KEYWORDS = [
    (("rate limit", "429", "too many requests", "限流"), "rate_limit"),
    (("timeout", "timed out", "超时"), "timeout"),
    (("502", "503", "504", "bad gateway", "server error", "上游"), "server"),
    (("connection", "dns", "network", "连接"), "network"),
    (("temporary", "transient", "临时"), "transient"),
    (("invalid", "validation", "422", "参数", "schema"), "validation"),
    (("unauthorized", "401", "403", "permission", "越权", "鉴权"), "auth"),
    (("not found", "404", "不存在"), "not_found"),
    (("quota", "budget exceeded", "预算"), "quota_hard"),
]


@dataclass
class ClassifiedError:
    kind: str
    retryable: bool
    message: str
    suggested_action: str

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "retryable": self.retryable,
                "message": self.message[:200], "suggested_action": self.suggested_action}


ACTIONS = {
    "rate_limit": "指数退避 + jitter 后重试，或切换供应商",
    "timeout": "缩短超时 / 降级到缓存 / 换更便宜模型",
    "server": "重试一次后走 fallback 链",
    "network": "检查网络白名单后重试",
    "validation": "修正参数（可操作错误消息回给模型），不重试",
    "auth": "刷新凭据或转人工，不重试",
    "not_found": "换查询条件，不重试",
    "quota_hard": "立即终止，返回部分结果",
}


def classify(exc: BaseException | str) -> ClassifiedError:
    msg = str(exc)
    low = msg.lower()
    kind = "unknown"
    for words, k in KEYWORDS:
        if any(w in low for w in words):
            kind = k
            break
    if isinstance(exc, (KeyError, TypeError, ValueError)) and kind == "unknown":
        kind = "validation"
    retryable = kind in RETRYABLE
    return ClassifiedError(kind, retryable, msg,
                           ACTIONS.get(kind, "记录 trace 并转人工排查" if not retryable else "按策略重试"))


def retryable(exc: BaseException | str) -> bool:
    return classify(exc).retryable


class RetryDecision(Exception):
    """只承载可重试错误的自定义异常，供 RetryPolicy(retry_on=(RetryDecision,)) 使用。"""
    def __init__(self, original: BaseException):
        super().__init__(str(original))
        self.original = original


def guarded(fn):
    """装饰器：把原异常按分类重写，非可重试错误直接抛出不进退避循环。"""
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as exc:
            c = classify(exc)
            if c.retryable:
                raise RetryDecision(exc) from exc
            raise
    return wrapper
