"""回归：分类确实接进了 RetryPolicy，而不只是有个 /v3 端点（本轮复盘补的缺口）。"""
from __future__ import annotations

from app.capabilities.reliability import RetryPolicy


def test_validation_error_is_not_retried():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ValueError("422 invalid parameter: sku 格式不对")

    p = RetryPolicy(max_attempts=3, backoff_factor=0)
    try:
        p.run_sync(fn)
    except ValueError:
        pass
    assert calls["n"] == 1, "参数错误不该退避重试"


def test_auth_and_quota_not_retried():
    for msg in ("403 permission denied", "quota exceeded budget"):
        calls = {"n": 0}

        def fn(msg=msg):
            calls["n"] += 1
            raise RuntimeError(msg)
        try:
            RetryPolicy(max_attempts=3, backoff_factor=0).run_sync(fn)
        except RuntimeError:
            pass
        assert calls["n"] == 1, msg


def test_rate_limit_still_retries():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 rate limit")
        return "ok"

    value, errs = RetryPolicy(max_attempts=3, backoff_factor=0).run_sync(fn)
    assert value == "ok" and len(errs) == 2


def test_unknown_error_keeps_legacy_behavior():
    """向后兼容：未命中任何分类关键词的异常仍按原 retry_on 重试。"""
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise RuntimeError("boom")
    try:
        RetryPolicy(max_attempts=3, backoff_factor=0).run_sync(fn)
    except RuntimeError:
        pass
    assert calls["n"] == 3


def test_can_disable_classification():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise ValueError("422 invalid parameter")
    try:
        RetryPolicy(max_attempts=3, backoff_factor=0, classify_errors=False).run_sync(fn)
    except ValueError:
        pass
    assert calls["n"] == 3
