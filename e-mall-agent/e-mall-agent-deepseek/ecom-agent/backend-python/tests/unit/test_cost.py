"""成本与 token 统计单元测试：单价折算、缓存计价、usage 提取与落库。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm.cost import (
    TokenUsage,
    compute_cost_cents,
    extract_usage,
    record_llm_call,
)
from app.llm.router import make_choice
from app.infra.models_obs import LlmCall

pytestmark = pytest.mark.unit


def _choice(model: str = "deepseek-chat"):
    return make_choice("deepseek", "strong", model)


def test_compute_cost_cents_uses_per_million_prices():
    choice = _choice()
    assert choice.price_in == 190.0 and choice.price_out == 790.0

    assert compute_cost_cents(choice, TokenUsage(prompt_tokens=1_000_000)) == 190
    assert compute_cost_cents(choice, TokenUsage(completion_tokens=1_000_000)) == 790
    assert compute_cost_cents(choice, TokenUsage(prompt_tokens=1)) == 1  # 有消耗至少记 1 分
    assert compute_cost_cents(choice, TokenUsage()) == 0


def test_cached_tokens_are_cheaper_than_fresh_prompt():
    choice = _choice()
    fresh = compute_cost_cents(choice, TokenUsage(prompt_tokens=1_000_000))
    cached = compute_cost_cents(choice, TokenUsage(prompt_tokens=1_000_000, cached_tokens=1_000_000))

    assert cached == 40  # price_cached=40 分/百万
    assert cached < fresh


def test_extract_usage_prefers_model_metadata():
    message = SimpleNamespace(
        usage_metadata={"input_tokens": 100, "output_tokens": 20, "input_token_details": {"cache_read": 10}},
        response_metadata={},
    )
    usage = extract_usage(message)

    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 20
    assert usage.cached_tokens == 10
    assert usage.total_tokens == 120
    assert usage.cache_hit_rate == pytest.approx(0.1)


def test_extract_usage_falls_back_to_estimation():
    usage = extract_usage(None, messages=[("user", "退货运费谁承担")], text="运费由买家承担")

    assert usage.prompt_tokens > 0
    assert usage.completion_tokens > 0
    assert usage.cached_tokens == 0


def test_token_usage_add_and_zero_cache_rate():
    first = TokenUsage(prompt_tokens=10, completion_tokens=5, cached_tokens=2)
    second = TokenUsage(prompt_tokens=20, completion_tokens=5, cached_tokens=8)
    total = first + second

    assert total.prompt_tokens == 30
    assert total.completion_tokens == 10
    assert total.cached_tokens == 10
    assert TokenUsage().cache_hit_rate == 0.0


def test_mock_provider_is_free():
    choice = make_choice("mock", "fast")
    usage = TokenUsage(prompt_tokens=1000, completion_tokens=200)

    assert choice.model == "mock-chat"
    assert compute_cost_cents(choice, usage) == 0


def test_record_llm_call_persists_row(db_session):
    choice = _choice()
    call_id = record_llm_call(
        choice,
        TokenUsage(prompt_tokens=120, completion_tokens=30),
        cost_cents=1,
        latency_ms=42,
        status="OK",
        trace_id="trace-test",
    )

    assert call_id > 0
    db_session.expire_all()
    row = db_session.get(LlmCall, call_id)
    assert row is not None
    assert row.provider == "deepseek"
    assert row.prompt_tokens == 120
    assert row.cost_cents == 1
    assert row.status == "OK"
