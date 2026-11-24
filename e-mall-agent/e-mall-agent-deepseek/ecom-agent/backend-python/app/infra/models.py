"""ORM 模型（业务主表）：用户/商品/订单/会话/审批/知识库。

表名、字段名与 ``deploy/mysql/init/01-schema.sql`` 严格一致；SQLite 兼容点：
* 主键使用 ``BigInteger().with_variant(Integer, "sqlite")`` 以便自增；
* ``MEDIUMTEXT`` 在 MySQL 方言下生效，其它方言退化为 ``TEXT``；
* 精度金额统一 ``Numeric(asdecimal=False)``，避免 SQLite 的 Decimal 警告。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-14] 可靠性/降级
# 职责：ORM 模型（业务主表）：用户/商品/订单/会话/审批/知识库
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.common.timeutil import utcnow
from app.infra.db import Base

BigIntPK = Integer().with_variant(mysql.BIGINT(), "mysql")
BigInt = Integer().with_variant(mysql.BIGINT(), "mysql")
MediumText = Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
Money = Numeric(12, 2, asdecimal=False)


class SysUser(Base):
    """用户（角色以逗号分隔存储，与 Java 端共享库结构）。"""

    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(128), default=None)
    roles: Mapped[str] = mapped_column(String(255), default="USER", nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class UserProfile(Base):
    """用户画像：长期记忆的结构化部分。"""

    __tablename__ = "user_profile"

    user_id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=False)
    nickname: Mapped[str | None] = mapped_column(String(64), default=None)
    phone: Mapped[str | None] = mapped_column(String(32), default=None)
    member_level: Mapped[str] = mapped_column(String(16), default="NORMAL", nullable=False)
    preferred_brands: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    budget_min: Mapped[float | None] = mapped_column(Numeric(10, 2, asdecimal=False), default=None)
    budget_max: Mapped[float | None] = mapped_column(Numeric(10, 2, asdecimal=False), default=None)
    sizes: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class UserMemory(Base):
    """长期记忆条目（文本 + 重要性 + 向量主键）。"""

    __tablename__ = "user_memory"
    __table_args__ = (Index("idx_mem_user", "user_id", "mem_type", "importance"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    mem_type: Mapped[str] = mapped_column(String(24), nullable=False, default="SEMANTIC")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(Numeric(3, 2, asdecimal=False), default=0.5, nullable=False)
    source_session: Mapped[int | None] = mapped_column(BigInt, default=None)
    vector_id: Mapped[int | None] = mapped_column(BigInt, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class Category(Base):
    __tablename__ = "category"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_id: Mapped[int] = mapped_column(BigInt, default=0, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Product(Base):
    """商品 SPU（search_text 拼装后供 MySQL FULLTEXT 降级检索）。"""

    __tablename__ = "product"
    __table_args__ = (
        Index("idx_product_cat", "category_id", "status"),
        Index("idx_product_price", "price"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(255), default=None)
    brand: Mapped[str | None] = mapped_column(String(64), default=None)
    category_id: Mapped[int] = mapped_column(BigInt, default=0, nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2, asdecimal=False), nullable=False)
    original_price: Mapped[float | None] = mapped_column(Numeric(10, 2, asdecimal=False), default=None)
    stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, default=1, nullable=False)
    rating: Mapped[float] = mapped_column(Numeric(2, 1, asdecimal=False), default=5.0, nullable=False)
    sales: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(512), default=None)
    attrs: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    search_text: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class OrderInfo(Base):
    __tablename__ = "order_info"
    __table_args__ = (Index("idx_order_user", "user_id", "status", "created_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="CREATED", nullable=False)
    total_amount: Mapped[float] = mapped_column(Money, default=0, nullable=False)
    pay_amount: Mapped[float] = mapped_column(Money, default=0, nullable=False)
    receiver_name: Mapped[str | None] = mapped_column(String(64), default=None)
    receiver_phone: Mapped[str | None] = mapped_column(String(32), default=None)
    receiver_address: Mapped[str | None] = mapped_column(String(512), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class OrderItem(Base):
    __tablename__ = "order_item"
    __table_args__ = (Index("idx_item_order", "order_id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    product_id: Mapped[int] = mapped_column(BigInt, default=0, nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2, asdecimal=False), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Logistics(Base):
    __tablename__ = "logistics"
    __table_args__ = (UniqueConstraint("order_id", name="uk_logistics_order"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    order_no: Mapped[str] = mapped_column(String(64), nullable=False)
    company: Mapped[str | None] = mapped_column(String(64), default=None)
    tracking_no: Mapped[str | None] = mapped_column(String(64), default=None)
    status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False)
    latest_event: Mapped[str | None] = mapped_column(String(255), default=None)
    events: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class RefundRequest(Base):
    __tablename__ = "refund_request"
    __table_args__ = (Index("idx_refund_user", "user_id", "status"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    refund_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    order_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    user_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    amount: Mapped[float] = mapped_column(Money, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(24), default="PENDING_APPROVAL", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    approval_id: Mapped[int | None] = mapped_column(BigInt, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ChatSession(Base):
    __tablename__ = "chat_session"
    __table_args__ = (Index("idx_session_user", "user_id", "last_message_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="新会话", nullable=False)
    agent_type: Mapped[str] = mapped_column(String(24), default="SUPERVISOR", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class ChatMessage(Base):
    __tablename__ = "chat_message"
    __table_args__ = (Index("idx_msg_session", "session_id", "id"), Index("idx_msg_trace", "trace_id"))

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str | None] = mapped_column(MediumText, default=None)
    agent_type: Mapped[str | None] = mapped_column(String(24), default=None)
    tool_calls: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    citations: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    token_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    token_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class ApprovalTask(Base):
    __tablename__ = "approval_task"
    __table_args__ = (
        Index("idx_approval_user", "user_id", "status"),
        Index("idx_approval_session", "session_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    message_id: Mapped[int | None] = mapped_column(BigInt, default=None)
    user_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    action_type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    risk: Mapped[str] = mapped_column(String(16), default="IRREVERSIBLE", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    decision_comment: Mapped[str | None] = mapped_column(String(512), default=None)
    decided_by: Mapped[int | None] = mapped_column(BigInt, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_document"
    __table_args__ = (Index("idx_doc_status", "status"), Index("idx_doc_type", "doc_type", "visibility"))

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(32), default="FAQ", nullable=False)
    source: Mapped[str | None] = mapped_column(String(512), default=None)
    visibility: Mapped[str] = mapped_column(String(24), default="PUBLIC", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunk"
    __table_args__ = (Index("idx_chunk_doc", "document_id", "chunk_no"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    chunk_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    parent_content: Mapped[str | None] = mapped_column(MediumText, default=None)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class KnowledgeJob(Base):
    __tablename__ = "knowledge_job"
    __table_args__ = (Index("idx_job_doc", "document_id"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BigInt, nullable=False)
    job_type: Mapped[str] = mapped_column(String(32), default="INDEX", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


__all__ = [
    "ApprovalTask",
    "Category",
    "ChatMessage",
    "ChatSession",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeJob",
    "Logistics",
    "OrderInfo",
    "OrderItem",
    "Product",
    "RefundRequest",
    "SysUser",
    "UserMemory",
    "UserProfile",
]
