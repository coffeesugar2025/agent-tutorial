"""用户画像：长期记忆的结构化部分（品牌偏好、预算区间、尺码、会员等级）。

画像只存**稳定且可复用**的信息，不存一次性查询条件。写入时机：
* 用户显式表达（"我只看华为"/"预算 5000 以内"）→ 由 Agent 调用工具或会话结束抽取；
* 下单/退货等行为推导 → 由业务侧异步更新。

读取时拼成一行注入 system prompt，体积控制在 200 字以内，避免挤占上下文预算。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-07] 记忆
# 职责：用户画像：长期记忆的结构化部分（品牌偏好、预算区间、尺码、会员等级）
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import logging
from typing import Any

from app.infra.db import session_scope
from app.infra.models import UserProfile

logger = logging.getLogger(__name__)

MEMBER_LEVELS = ("NORMAL", "SILVER", "GOLD", "PLATINUM")


def get_profile(user_id: int) -> dict[str, Any]:
    """读画像；不存在时返回默认值（不自动建行，避免无意义写入）。"""
    with session_scope() as db:
        row = db.get(UserProfile, user_id)
        if row is None:
            return {
                "userId": user_id,
                "nickname": None,
                "memberLevel": "NORMAL",
                "preferredBrands": [],
                "budgetMin": None,
                "budgetMax": None,
                "sizes": {},
            }
        return _to_vo(row)


def upsert_profile(user_id: int, **fields: Any) -> dict[str, Any]:
    """部分更新画像：只更新传入的字段，``None`` 视为不修改。"""
    allowed = {"nickname", "phone", "member_level", "preferred_brands", "budget_min", "budget_max", "sizes"}
    with session_scope() as db:
        row = db.get(UserProfile, user_id)
        if row is None:
            row = UserProfile(user_id=user_id)
            db.add(row)
            db.flush()
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            if key == "member_level" and value not in MEMBER_LEVELS:
                continue
            if key == "preferred_brands":
                row.preferred_brands = _merge_brands(row.preferred_brands, value)
                continue
            if key == "sizes" and isinstance(value, dict):
                merged = dict(row.sizes or {})
                merged.update({str(k): str(v) for k, v in value.items()})
                row.sizes = merged
                continue
            setattr(row, key, value)
        return _to_vo(row)


def _merge_brands(current: Any, incoming: Any) -> list[str]:
    """合并品牌偏好，去重且保持顺序，最多 8 个。"""
    merged: list[str] = []
    for item in list(current or []) + list(incoming or []):
        text = str(item).strip()
        if text and text not in merged:
            merged.append(text)
    return merged[:8]


def _to_vo(row: UserProfile) -> dict[str, Any]:
    return {
        "userId": row.user_id,
        "nickname": row.nickname,
        "memberLevel": row.member_level,
        "preferredBrands": list(row.preferred_brands or []),
        "budgetMin": float(row.budget_min) if row.budget_min is not None else None,
        "budgetMax": float(row.budget_max) if row.budget_max is not None else None,
        "sizes": dict(row.sizes or {}),
    }


# ──────── [CAP-06] 上下文工程 ────────
#   本处：用户画像注入（≤200 字）
#   域约束：稳定内容在前、易变在后；画像≤200 字、记忆 top5、Skill 正文按触发词加载
def profile_snippet(user_id: int) -> str:
    """拼成注入 system prompt 的一行画像（≤200 字）。"""
    try:
        profile = get_profile(user_id)
    except Exception as exc:  # noqa: BLE001 - 画像缺失不影响对话
        logger.warning("读取用户画像失败 user=%s err=%s", user_id, exc)
        return ""

    parts: list[str] = []
    level = profile.get("memberLevel")
    if level and level != "NORMAL":
        parts.append(f"会员等级 {level}")
    brands = profile.get("preferredBrands") or []
    if brands:
        parts.append("偏好品牌 " + "/".join(brands[:4]))
    low, high = profile.get("budgetMin"), profile.get("budgetMax")
    if low and high:
        parts.append(f"常购价位 {int(low)}-{int(high)} 元")
    elif high:
        parts.append(f"预算上限 {int(high)} 元")
    sizes = profile.get("sizes") or {}
    if sizes:
        parts.append("尺码 " + "/".join(f"{k}:{v}" for k, v in list(sizes.items())[:3]))
    if not parts:
        return ""
    return "【已知用户画像】" + "；".join(parts)


__all__ = ["MEMBER_LEVELS", "get_profile", "profile_snippet", "upsert_profile"]
