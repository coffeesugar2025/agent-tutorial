"""PII 脱敏单元测试：手机号、身份证、银行卡、邮箱、地址、姓名与递归对象。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-17] 评测与迭代  （支撑）
# 职责：PII 脱敏单元测试：手机号、身份证、银行卡、邮箱、地址、姓名与递归对象
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import pytest

from app.security.pii import (
    contains_pii,
    mask_address,
    mask_bank_card,
    mask_email,
    mask_id_card,
    mask_name,
    mask_obj,
    mask_phone,
    mask_text,
)

pytestmark = pytest.mark.unit


def test_mask_phone_keeps_prefix_and_suffix():
    assert mask_phone("联系电话 13812345678") == "联系电话 138****5678"
    assert mask_phone("订单号 12345 不是手机号") == "订单号 12345 不是手机号"


def test_mask_id_card_and_bank_card():
    assert mask_id_card("身份证 110101199001011234") == "身份证 110101********1234"
    assert mask_bank_card("卡号 6222021234567890123") == "卡号 6222********0123"


def test_mask_email_keeps_domain():
    masked = mask_email("zhang.san@example.com")

    assert masked == "z***@example.com"
    assert masked.endswith("@example.com")


def test_mask_address_hides_door_number():
    masked = mask_address("浙江省杭州市西湖区文三路100号3幢501室")

    assert "文三路" in masked
    assert "100号" not in masked
    assert "501室" not in masked


def test_mask_name_only_after_explicit_label():
    assert mask_name("收货人：张三") == "收货人：张*"
    assert mask_name("收货人：欧阳修") == "收货人：欧**"
    assert mask_name("张三丰是武侠人物") == "张三丰是武侠人物"


def test_mask_text_handles_mixed_pii():
    raw = "收货人：张三，电话 13812345678，邮箱 zhang.san@example.com"
    masked = mask_text(raw)

    assert "13812345678" not in masked
    assert "138****5678" in masked
    assert "zhang.san@example.com" not in masked
    assert "张*" in masked
    assert contains_pii(raw) is True
    assert contains_pii(masked) is False


def test_mask_obj_recurses_into_dict_and_list():
    payload = {
        "phone": "13812345678",
        "items": [{"email": "zhang@b.com"}],
        "count": 2,
    }
    masked = mask_obj(payload)

    assert masked["phone"] == "138****5678"
    assert masked["items"][0]["email"] == "z***@b.com"
    assert masked["count"] == 2


def test_empty_inputs_are_safe():
    assert mask_text("") == ""
    assert mask_text(None) == ""
    assert contains_pii(None) is False
    assert mask_obj(None) is None
