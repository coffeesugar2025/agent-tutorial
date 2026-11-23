"""ID 生成：trace/span、ULID、雪花 ID、幂等键与内容校验和。

* trace_id：32 位 hex，与 docs/03 示例 ``9f2c1e...`` 风格一致；
* ULID：26 位 Crockford Base32，按时间单调，可作对外短 ID；
* 雪花：64 位整型，worker_id 取自环境变量，单进程内线程安全。
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
import uuid

# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_trace_id() -> str:
    """32 位十六进制 traceId。"""
    return uuid.uuid4().hex


def new_span_id() -> str:
    """16 位十六进制 spanId。"""
    return uuid.uuid4().hex[:16]


def new_client_msg_id() -> str:
    """客户端消息 ID（幂等去重用）。"""
    return uuid.uuid4().hex


def new_ulid(ts_ms: int | None = None) -> str:
    """生成 ULID：48 位毫秒时间戳 + 80 位随机，字典序即时间序。"""
    ts = int(time.time() * 1000) if ts_ms is None else int(ts_ms)
    # 48 位时间戳 → 10 个 Base32 字符
    ts_part = []
    for shift in range(45, -1, -5):
        ts_part.append(_CROCKFORD[(ts >> shift) & 0x1F])
    # 80 位随机 → 16 个 Base32 字符
    rand_bits = int.from_bytes(secrets.token_bytes(10), "big")
    rand_part = []
    for shift in range(75, -1, -5):
        rand_part.append(_CROCKFORD[(rand_bits >> shift) & 0x1F])
    return "".join(ts_part) + "".join(rand_part)


# ---------------------------------------------------------------------------
# 雪花 ID
# ---------------------------------------------------------------------------
class SnowflakeGenerator:
    """Snowflake：41 位时间 + 10 位机器 + 12 位序列。"""

    EPOCH_MS = 1704067200000  # 2024-01-01T00:00:00Z
    WORKER_BITS = 10
    SEQ_BITS = 12
    MAX_WORKER = (1 << WORKER_BITS) - 1
    MAX_SEQ = (1 << SEQ_BITS) - 1

    def __init__(self, worker_id: int | None = None) -> None:
        if worker_id is None:
            worker_id = int(os.getenv("SNOWFLAKE_WORKER_ID", "0"))
        self.worker_id = max(0, min(int(worker_id), self.MAX_WORKER))
        self._lock = threading.Lock()
        self._last_ms = -1
        self._seq = 0

    def next_id(self) -> int:
        with self._lock:
            now = int(time.time() * 1000)
            if now < self._last_ms:
                # 时钟回拨：沿用上一个时间戳，序列继续自增避免重复
                now = self._last_ms
            if now == self._last_ms:
                self._seq = (self._seq + 1) & self.MAX_SEQ
                if self._seq == 0:
                    now = self._wait_next_ms(self._last_ms)
            else:
                self._seq = 0
            self._last_ms = now
            return ((now - self.EPOCH_MS) << (self.WORKER_BITS + self.SEQ_BITS)) | (
                self.worker_id << self.SEQ_BITS
            ) | self._seq

    @staticmethod
    def _wait_next_ms(last_ms: int) -> int:
        now = int(time.time() * 1000)
        while now <= last_ms:
            time.sleep(0.001)
            now = int(time.time() * 1000)
        return now


_snowflake = SnowflakeGenerator()


def next_id() -> int:
    """进程级雪花 ID（用于内部记录 ID、向量主键等）。"""
    return _snowflake.next_id()


# ---------------------------------------------------------------------------
# 幂等 / 校验
# ---------------------------------------------------------------------------
def short_hash(*parts: object, length: int = 32) -> str:
    """把任意片段稳定折叠成短哈希（幂等键、去重键）。"""
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()[:length]


def idempotency_key(scope: str, *parts: object) -> str:
    """生成幂等键：``scope:hash``，长度控制在 160 字符内（贴合表结构）。"""
    return f"{scope}:{short_hash(scope, *parts)}"


def checksum_text(text: str) -> str:
    """文本内容校验和（64 位 hex），用于知识文档幂等索引。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def checksum_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


__all__ = [
    "SnowflakeGenerator",
    "checksum_bytes",
    "checksum_text",
    "idempotency_key",
    "new_client_msg_id",
    "new_span_id",
    "new_trace_id",
    "new_ulid",
    "next_id",
    "short_hash",
]
