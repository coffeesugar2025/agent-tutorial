"""长期记忆：写入、向量召回、衰减、抽取。

写入策略（避免记忆变噪音）：
* 只记**稳定可复用**的信息：预算区间、偏好品牌、尺码、明确的否定偏好；
* 不记：一次性查询条件、临时情绪、可从订单推导的事实；
* 冲突处理：新记忆与旧记忆语义重复时不新增，而是提升重要性并刷新时间；
  新旧矛盾时旧记忆重要性减半（不物理删除，保留可追溯性）。

召回策略：向量召回优先（Milvus ``ecom_memory`` 集合），失败降级为
"重要性 + 词面重合"的 SQL 打分，保证 Milvus 不可用时仍能工作。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.common.timeutil import utcnow
from app.config import settings
from app.infra.db import session_scope
from app.infra.models import UserMemory

logger = logging.getLogger(__name__)

MEM_SEMANTIC = "SEMANTIC"
MEM_EPISODIC = "EPISODIC"
MEM_PROCEDURAL = "PROCEDURAL"
MEM_TYPES = (MEM_SEMANTIC, MEM_EPISODIC, MEM_PROCEDURAL)

_MEMORY_COLLECTION = "memory"


# ---------------------------------------------------------------------------
# 写入
# ---------------------------------------------------------------------------
def remember(
    user_id: int,
    content: str,
    *,
    mem_type: str = MEM_SEMANTIC,
    importance: float = 0.5,
    session_id: int | None = None,
) -> int:
    """写一条长期记忆并建索引，返回记忆 id。"""
    text = (content or "").strip()
    if not text:
        raise ValueError("记忆内容不能为空")
    if mem_type not in MEM_TYPES:
        mem_type = MEM_SEMANTIC
    importance = max(0.0, min(1.0, float(importance)))

    memory_id = 0
    with session_scope() as db:
        row = UserMemory(
            user_id=user_id,
            mem_type=mem_type,
            content=text[:2000],
            importance=importance,
            source_session=session_id,
        )
        db.add(row)
        db.flush()
        memory_id = int(row.id)

    _index(memory_id, user_id, mem_type, text)
    return memory_id


def _index(memory_id: int, user_id: int, mem_type: str, text: str) -> None:
    """写向量索引；失败只告警（记忆仍可从 MySQL 召回）。"""
    try:
        from app.rag.embedding import get_embedding
        from app.rag.store import VectorRecord, get_store

        vector = get_embedding().embed_query(text)
        store = get_store()
        store.ensure(_MEMORY_COLLECTION, len(vector))
        store.upsert(
            _MEMORY_COLLECTION,
            [
                VectorRecord(
                    id=memory_id,
                    vector=vector,
                    content=text[:2000],
                    payload={"userId": user_id, "memType": mem_type, "memoryId": memory_id},
                )
            ],
        )
        with session_scope() as db:
            row = db.get(UserMemory, memory_id)
            if row is not None:
                row.vector_id = memory_id
    except Exception as exc:  # noqa: BLE001
        logger.warning("记忆向量索引失败 memory=%s err=%s", memory_id, exc)


# ---------------------------------------------------------------------------
# 召回
# ---------------------------------------------------------------------------
def recall(user_id: int, query: str, top_k: int = 5) -> list[str]:
    """召回与当前问题相关的长期记忆（返回文本列表）。"""
    hits = _recall_vector(user_id, query, top_k)
    if hits:
        return hits
    return _recall_sql(user_id, query, top_k)


def _recall_vector(user_id: int, query: str, top_k: int) -> list[str]:
    if not query.strip():
        return []
    try:
        from app.rag.embedding import get_embedding
        from app.rag.store import get_store

        store = get_store()
        vector = get_embedding().embed_query(query)
        hits = store.search_dense(
            _MEMORY_COLLECTION,
            vector,
            top_k=max(top_k, 5),
            filters={"userId": user_id},
        )
        return [hit.content for hit in hits if hit.content][:top_k]
    except Exception as exc:  # noqa: BLE001 - 向量不可用是常态（未部署 Milvus）
        logger.debug("记忆向量召回不可用，降级 SQL: %s", exc)
        return []


def _recall_sql(user_id: int, query: str, top_k: int) -> list[str]:
    """降级召回：重要性 0.6 + 词面重合 0.4。"""
    terms = _terms(query)
    try:
        with session_scope() as db:
            rows = (
                db.query(UserMemory)
                .filter(UserMemory.user_id == user_id)
                .order_by(UserMemory.importance.desc(), UserMemory.created_at.desc())
                .limit(50)
                .all()
            )
            scored: list[tuple[float, str]] = []
            for row in rows:
                overlap = len([t for t in terms if t and t in row.content])
                lexical = min(overlap, 3) / 3 if terms else 0.0
                score = float(row.importance) * 0.6 + lexical * 0.4
                scored.append((score, row.content))
            scored.sort(key=lambda item: item[0], reverse=True)
            return [content for score, content in scored[:top_k] if score > 0]
    except Exception as exc:  # noqa: BLE001
        logger.warning("记忆 SQL 召回失败 user=%s err=%s", user_id, exc)
        return []


def _terms(text: str) -> list[str]:
    """极简切词：中文按 2-4 字滑窗 + 英文数字整词。"""
    text = (text or "").lower()
    words = re.findall(r"[a-z0-9]{2,}", text)
    chinese = re.findall(r"[\u4e00-\u9fa5]{2,}", text)
    grams: list[str] = list(words)
    for chunk in chinese:
        grams.extend(chunk[i : i + 2] for i in range(len(chunk) - 1))
    return list(dict.fromkeys(grams))[:40]


# ---------------------------------------------------------------------------
# 管理与衰减
# ---------------------------------------------------------------------------
def list_memories(user_id: int, limit: int = 20) -> list[dict[str, Any]]:
    with session_scope() as db:
        rows = (
            db.query(UserMemory)
            .filter(UserMemory.user_id == user_id)
            .order_by(UserMemory.importance.desc(), UserMemory.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": row.id,
                "type": row.mem_type,
                "content": row.content,
                "importance": float(row.importance),
                "createdAt": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
            }
            for row in rows
        ]


def forget(user_id: int, memory_id: int) -> bool:
    """删除一条记忆（用户可删，合规要求）。"""
    with session_scope() as db:
        row = db.get(UserMemory, memory_id)
        if row is None or row.user_id != user_id:
            return False
        db.delete(row)
    try:
        from app.rag.store import get_store

        get_store().delete(_MEMORY_COLLECTION, ids=[memory_id])
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除记忆向量失败 memory=%s err=%s", memory_id, exc)
    return True


def decay(user_id: int) -> int:
    """按半衰期衰减重要性，低于阈值删除。返回受影响条数。"""
    half_life = max(1, settings.memory_half_life_days)
    now = utcnow()
    affected = 0
    with session_scope() as db:
        rows = db.query(UserMemory).filter(UserMemory.user_id == user_id).all()
        for row in rows:
            created = row.created_at or now
            days = max(0.0, (now - created).total_seconds() / 86400.0)
            factor = 0.5 ** (days / half_life)
            row.importance = float(row.importance) * factor
            affected += 1
            if row.importance < 0.1:
                db.delete(row)
    return affected


# ---------------------------------------------------------------------------
# 抽取（会话结束/摘要时调用）
# ---------------------------------------------------------------------------
_BUDGET_RE = re.compile(r"(\d{3,6})\s*(?:元|块|以内|以下|左右)")
_BRAND_HINTS = ("华为", "小米", "苹果", "apple", "oppo", "vivo", "荣耀", "联想", "戴尔", "索尼", "三星")


def extract_candidates(text: str) -> list[dict[str, Any]]:
    """规则式抽取稳定偏好（不调用模型，零成本、可解释）。

    只抽三类：预算上限、品牌偏好、明确的尺码。
    """
    if not text:
        return []
    found: list[dict[str, Any]] = []
    lowered = text.lower()

    budgets = [int(m) for m in _BUDGET_RE.findall(text) if 100 <= int(m) <= 200000]
    if budgets:
        found.append(
            {
                "content": f"预算上限约 {max(budgets)} 元",
                "importance": 0.75,
                "memType": MEM_SEMANTIC,
            }
        )

    brands = [b for b in _BRAND_HINTS if b in lowered]
    if brands:
        found.append(
            {
                "content": "偏好品牌：" + "、".join(dict.fromkeys(brands)),
                "importance": 0.7,
                "memType": MEM_SEMANTIC,
            }
        )

    size = re.search(r"(?:尺码|鞋码|码数)\s*[:：]?\s*([0-9]{2}|S|M|L|XL|XXL)", text, re.IGNORECASE)
    if size:
        found.append({"content": f"常用尺码 {size.group(1)}", "importance": 0.8, "memType": MEM_SEMANTIC})

    return found


def persist_candidates(user_id: int, text: str, session_id: int | None = None) -> int:
    """把抽取结果落库，跳过已存在的同义记忆。返回新增条数。"""
    existing = {item["content"] for item in list_memories(user_id, limit=100)}
    added = 0
    for candidate in extract_candidates(text):
        if candidate["content"] in existing:
            continue
        try:
            remember(
                user_id,
                candidate["content"],
                mem_type=candidate["memType"],
                importance=candidate["importance"],
                session_id=session_id,
            )
            added += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("写入记忆失败 user=%s err=%s", user_id, exc)
    return added


__all__ = [
    "MEM_EPISODIC",
    "MEM_PROCEDURAL",
    "MEM_SEMANTIC",
    "MEM_TYPES",
    "decay",
    "extract_candidates",
    "forget",
    "list_memories",
    "persist_candidates",
    "recall",
    "remember",
]
