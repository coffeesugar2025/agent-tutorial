"""Token 估算与成本折算单元测试。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-17] 评测与迭代  （支撑）
# 职责：Token 估算与成本折算单元测试
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import pytest

from app.common.tokens import (
    cost_in_cents,
    estimate_messages_tokens,
    estimate_tokens,
    fit_texts,
    truncate_to_tokens,
)

pytestmark = pytest.mark.unit


def test_empty_text_estimates_zero_and_whitespace_is_cheap():
    assert estimate_tokens(None) == 0
    assert estimate_tokens("") == 0
    # 纯空白不携带信息，按"2 字符 1 token"折算，成本可忽略
    assert estimate_tokens("   \n\t ") <= 3


def test_cjk_costs_roughly_one_token_per_char():
    assert estimate_tokens("退款") == 2
    assert estimate_tokens("退货运费") == 4
    assert estimate_tokens("退货运费") > estimate_tokens("退款")


def test_ascii_uses_four_chars_per_token():
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcdefgh") == 2
    assert estimate_tokens("abcdefgh") > estimate_tokens("abcd")


def test_mixed_text_costs_more_than_each_part():
    cjk = estimate_tokens("退款政策")
    ascii_part = estimate_tokens("refund policy")
    mixed = estimate_tokens("退款政策 refund policy")

    assert mixed >= cjk + ascii_part - 1
    assert mixed > cjk


def test_truncate_to_tokens_respects_budget():
    text = "".join(f"第{i}句说明退货运费规则。" for i in range(50))
    truncated = truncate_to_tokens(text, 20)

    assert truncated
    assert truncated.endswith("…")
    assert len(truncated) < len(text)
    assert estimate_tokens(truncated) <= 22
    assert truncate_to_tokens(text, 0) == ""


def test_fit_texts_keeps_what_fits_and_drops_the_rest():
    assert fit_texts(["abc", "def"], 100) == "abc\n\ndef"

    long_text = "很长的政策说明。" * 100
    fitted = fit_texts(["短文本", long_text], 20)
    assert "短文本" in fitted
    assert long_text not in fitted


def test_estimate_messages_tokens_includes_overhead():
    messages = [("system", "你是电商客服助手"), ("user", "退货运费谁承担")]
    total = estimate_messages_tokens(messages)

    assert total > estimate_tokens("你是电商客服助手") + estimate_tokens("退货运费谁承担")
    assert total > estimate_messages_tokens([("user", "退款")])


def test_cost_in_cents_rounds_up_and_handles_zero():
    # 单价单位是"分 / 百万 token"
    assert cost_in_cents(1_000_000, 0, 190.0, 790.0) == 190
    assert cost_in_cents(0, 1_000_000, 190.0, 790.0) == 790
    assert cost_in_cents(1_000, 0, 190.0, 790.0) == 1
    assert cost_in_cents(0, 0, 190.0, 790.0) == 0
