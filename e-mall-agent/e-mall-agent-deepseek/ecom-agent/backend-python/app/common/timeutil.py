"""时间工具。

库内所有时间统一存 **naive UTC**（对应 MySQL ``DATETIME(3)``），
对外 ISO8601 输出时转换为 ``settings.timezone`` 时区（默认 +08:00）。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-01] 交互协议  |  [CAP-14] 可靠性/降级  （支撑）
# 职责：时间工具
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings


def utcnow() -> datetime:
    """当前 UTC 时间（naive，入库用）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def now_ms() -> int:
    """当前毫秒时间戳。"""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def local_tz() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def as_utc(value: datetime) -> datetime:
    """把任意 datetime 归一为 naive UTC（带时区的先转换）。"""
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def to_iso(value: datetime | None) -> str | None:
    """naive UTC → 本地时区 ISO8601（契约示例：``2026-11-23T10:00:00+08:00``）。"""
    if value is None:
        return None
    aware = as_utc(value).replace(tzinfo=timezone.utc).astimezone(local_tz())
    return aware.isoformat(timespec="seconds")


def iso_now() -> str:
    return to_iso(utcnow()) or ""


def parse_iso(text: str) -> datetime:
    """解析 ISO8601 字符串，返回 naive UTC。"""
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return as_utc(value)


def from_ms(value: int) -> datetime:
    return as_utc(datetime.fromtimestamp(value / 1000, tz=timezone.utc))


def days_ago(days: int) -> datetime:
    return utcnow() - timedelta(days=days)


def seconds_later(seconds: float) -> datetime:
    return utcnow() + timedelta(seconds=seconds)


def elapsed_ms(started: datetime | None) -> int:
    """从 started 到现在的毫秒数（started 为空返回 0）。"""
    if started is None:
        return 0
    delta = utcnow() - as_utc(started)
    return max(int(delta.total_seconds() * 1000), 0)


def duration_ms(start: float) -> int:
    """从 ``time.perf_counter()`` 起点算出的毫秒数。"""
    import time

    return max(int((time.perf_counter() - start) * 1000), 0)


def day_str(value: datetime | None = None) -> str:
    """``YYYY-MM-DD``（本地时区）。"""
    target = value or utcnow()
    aware = as_utc(target).replace(tzinfo=timezone.utc).astimezone(local_tz())
    return aware.date().isoformat()


def date_range(days: int) -> list[str]:
    """最近 days 天的日期串（含今天，升序）。"""
    today = as_utc(utcnow()).replace(tzinfo=timezone.utc).astimezone(local_tz()).date()
    return [(today - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]


def parse_day(text: str) -> date:
    return date.fromisoformat(text)


def humanize_age(value: datetime | None) -> str:
    """相对时间描述（前端兜底展示用）。"""
    if value is None:
        return "刚刚"
    seconds = int((utcnow() - as_utc(value)).total_seconds())
    if seconds < 60:
        return f"{max(seconds, 0)} 秒前"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    return f"{seconds // 86400} 天前"


__all__ = [
    "as_utc",
    "date_range",
    "day_str",
    "days_ago",
    "duration_ms",
    "elapsed_ms",
    "from_ms",
    "humanize_age",
    "iso_now",
    "local_tz",
    "now_ms",
    "parse_day",
    "parse_iso",
    "seconds_later",
    "to_iso",
    "utcnow",
]
