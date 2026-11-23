"""PII 脱敏：手机号、身份证、银行卡、邮箱、详细地址。

原则：
* 只做"输出侧"脱敏（入库保留原文，便于业务核对）；
* 顺序敏感：先身份证/银行卡（长数字），再手机号，避免被短规则截断；
* ``mask_obj`` 递归处理 dict/list，直接用于工具返回与 SSE 结果。
"""

from __future__ import annotations

import re
from typing import Any

# 中国大陆手机号：1[3-9] + 9 位
PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)")
# 身份证：18 位（末位可为 X）或 15 位
ID_CARD_RE = re.compile(r"(?<!\d)(\d{6})(\d{8})(\d{3}[\dXx]|\d{3})(?!\d)")
# 银行卡：16~19 位连续数字（前后不得为数字/字母）
BANK_CARD_RE = re.compile(r"(?<![\dA-Za-z])(\d{4})(\d{8,11})(\d{4})(?![\dA-Za-z])")
EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-])([A-Za-z0-9._%+-]*)(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
# 详细地址：省市区之后的门牌/楼栋信息
ADDRESS_RE = re.compile(
    r"((?:[\u4e00-\u9fa5]{2,10}(?:省|市|自治区))?"
    r"(?:[\u4e00-\u9fa5]{2,10}(?:市|区|县|镇))?"
    r"(?:[\u4e00-\u9fa5A-Za-z0-9]{0,20}(?:路|街|道|巷|弄|村)))"
    r"([\u4e00-\u9fa5A-Za-z0-9\-]{1,40}?(?:号|栋|幢|单元|室|楼)[\u4e00-\u9fa5A-Za-z0-9\-]{0,20})"
)
# 姓名类：仅对 "收货人/收件人/联系人：张三" 这类显式标签做部分脱敏
NAME_LABEL_RE = re.compile(r"((?:收货人|收件人|联系人|真实姓名)\s*[:：]\s*)([\u4e00-\u9fa5]{2,4})")

MASK = "****"


def mask_phone(phone: str) -> str:
    """138****8888。"""
    return PHONE_RE.sub(lambda m: f"{m.group(1)}{MASK}{m.group(3)}", phone)


def mask_id_card(text: str) -> str:
    """110101********1234。"""
    return ID_CARD_RE.sub(lambda m: f"{m.group(1)}{'*' * 8}{m.group(3)}", text)


def mask_bank_card(text: str) -> str:
    """6222********1234。"""
    return BANK_CARD_RE.sub(lambda m: f"{m.group(1)}{'*' * 8}{m.group(3)}", text)


def mask_email(text: str) -> str:
    """a***@example.com。"""
    return EMAIL_RE.sub(lambda m: f"{m.group(1)}{'***' if m.group(2) else ''}{m.group(3)}", text)


def mask_address(text: str) -> str:
    """保留到街道，门牌/楼栋整体打码。"""

    def _replace(match: re.Match[str]) -> str:
        detail = match.group(2)
        if len(detail) <= 2:
            return f"{match.group(1)}{MASK}"
        return f"{match.group(1)}{detail[0]}{'*' * min(len(detail) - 1, 6)}"

    return ADDRESS_RE.sub(_replace, text)


def mask_name(text: str) -> str:
    """张* / 欧阳**：只打码标签后的姓名。"""

    def _replace(match: re.Match[str]) -> str:
        name = match.group(2)
        if len(name) <= 1:
            return match.group(1) + "*"
        return f"{match.group(1)}{name[0]}{'*' * (len(name) - 1)}"

    return NAME_LABEL_RE.sub(_replace, text)


def mask_text(text: str | None) -> str:
    """按"长数字优先"的顺序对文本做全量脱敏。"""
    if not text:
        return ""
    masked = text
    masked = mask_id_card(masked)
    masked = mask_bank_card(masked)
    masked = mask_phone(masked)
    masked = mask_email(masked)
    masked = mask_address(masked)
    masked = mask_name(masked)
    return masked


def contains_pii(text: str | None) -> bool:
    """是否含 PII（用于审计与告警，不用于拦截）。"""
    if not text:
        return False
    return any(
        pattern.search(text)
        for pattern in (PHONE_RE, ID_CARD_RE, BANK_CARD_RE, EMAIL_RE, ADDRESS_RE)
    )


def mask_obj(value: Any, depth: int = 0) -> Any:
    """递归脱敏任意结构（dict/list/str），用于工具返回与评估落库。"""
    if depth > 8:
        return value
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, dict):
        return {key: mask_obj(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_obj(item, depth + 1) for item in value]
    return value


__all__ = [
    "contains_pii",
    "mask_address",
    "mask_bank_card",
    "mask_email",
    "mask_id_card",
    "mask_name",
    "mask_obj",
    "mask_phone",
    "mask_text",
]
