"""知识入库：解析(md/txt/pdf/docx) → 清洗 → 切片 → 向量化 → 入库（幂等）。

幂等策略：
* 文档级：``checksum`` 相同且状态 READY → 直接跳过（同一份内容重复上传不重复计费）；
* 切片级：每次（重）索引先按 ``document_id`` 物理删除旧 chunk 与旧向量，避免残留；
* 作业级：``knowledge_job`` 记录 QUEUED → RUNNING → SUCCESS/FAILED + progress。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-12] 检索增强 RAG
# 职责：知识入库：解析(md/txt/pdf/docx) → 清洗 → 切片 → 向量化 → 入库（幂等）
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.common.errors import param_invalid
from app.common.ids import checksum_text
from app.common.tokens import estimate_tokens
from app.common.timeutil import utcnow
from app.config import settings
from app.infra.db import session_scope
from app.infra.models import KnowledgeChunk, KnowledgeDocument, KnowledgeJob
from app.obs.metrics import record_degradation
from app.rag.chunker import chunk_document, clean_text
from app.rag.embedding import get_embedding
from app.rag.store import VectorRecord, get_store

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".md", ".markdown", ".txt", ".pdf", ".docx"}


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def parse_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise param_invalid("PDF 解析依赖 pypdf 未安装，请改用 .md/.txt 或安装 pypdf") from exc
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            logger.warning("PDF 单页解析失败: %s", exc)
    return "\n\n".join(pages)


def parse_docx(path: Path) -> str:
    try:
        import docx
    except ImportError as exc:
        raise param_invalid("DOCX 解析依赖 python-docx 未安装") from exc
    document = docx.Document(str(path))
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def parse_file(path: str | Path) -> str:
    """按扩展名解析为纯文本。"""
    file_path = Path(path)
    if not file_path.exists():
        raise param_invalid(f"文件不存在: {file_path}")
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise param_invalid(f"不支持的文件类型: {suffix}（支持 md/txt/pdf/docx）")
    if suffix in {".md", ".markdown", ".txt"}:
        return parse_text_file(file_path)
    if suffix == ".pdf":
        return parse_pdf(file_path)
    return parse_docx(file_path)


# ---------------------------------------------------------------------------
# 作业
# ---------------------------------------------------------------------------
def update_job(job_id: int | None, status: str, progress: int | None = None, error: str | None = None) -> None:
    if not job_id:
        return
    try:
        with session_scope() as db:
            job = db.get(KnowledgeJob, job_id)
            if job is None:
                return
            job.status = status
            if progress is not None:
                job.progress = max(0, min(int(progress), 100))
            if error is not None:
                job.error = error[:4000]
    except Exception as exc:  # noqa: BLE001
        logger.warning("更新 knowledge_job 失败 job=%s err=%s", job_id, exc)


def _set_document_status(document_id: int, status: str, **fields: Any) -> None:
    with session_scope() as db:
        doc = db.get(KnowledgeDocument, document_id)
        if doc is None:
            return
        doc.status = status
        for key, value in fields.items():
            setattr(doc, key, value)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
# ──────── [CAP-12] 检索增强 RAG ────────
#   本处：知识入库（checksum 幂等 + 版本）
#   域约束：任一环节失败必须降级并标记 degraded，不允许静默返回空结果
def ingest_document(
    document_id: int,
    *,
    job_id: int | None = None,
    content: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """索引一个知识文档（幂等）。返回摘要 dict，供 MQ handler / 脚本使用。"""
    update_job(job_id, "RUNNING", 5)
    with session_scope() as db:
        doc = db.get(KnowledgeDocument, document_id)
        if doc is None:
            update_job(job_id, "FAILED", error=f"文档不存在: {document_id}")
            return {"ok": False, "error": f"文档不存在: {document_id}"}
        raw = content
        if raw is None:
            try:
                raw = parse_file(doc.source) if doc.source else ""
            except Exception as exc:  # noqa: BLE001
                _set_document_status(document_id, "FAILED")
                update_job(job_id, "FAILED", error=str(exc))
                return {"ok": False, "error": str(exc)}
        cleaned = clean_text(raw)
        if not cleaned:
            _set_document_status(document_id, "FAILED")
            update_job(job_id, "FAILED", error="文档内容为空或无法解析")
            return {"ok": False, "error": "文档内容为空"}
        checksum = checksum_text(cleaned)
        if not force and doc.status == "READY" and doc.checksum == checksum:
            update_job(job_id, "SUCCESS", 100)
            return {
                "ok": True,
                "skipped": True,
                "documentId": document_id,
                "chunkCount": doc.chunk_count,
                "reason": "内容校验和未变化，跳过重复索引",
            }
        was_ready = doc.status == "READY"
        doc.status = "INDEXING"
        doc.checksum = checksum

    update_job(job_id, "RUNNING", 20)

    try:
        chunks = chunk_document(
            cleaned,
            size=settings.chunk_size,
            overlap=settings.chunk_overlap,
            parent_size=settings.parent_chunk_size,
            metadata={"documentId": document_id},
        )
        if not chunks:
            raise ValueError("切片结果为空")

        # 清理旧切片与旧向量（物理删除，保持重索引干净）
        with session_scope() as db:
            old_ids = [
                int(row[0])
                for row in db.query(KnowledgeChunk.id)
                .filter(KnowledgeChunk.document_id == document_id)
                .all()
            ]
            db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document_id).delete()
            doc = db.get(KnowledgeDocument, document_id)
            title = doc.title if doc else ""
            doc_type = doc.doc_type if doc else "FAQ"
            visibility = doc.visibility if doc else "PUBLIC"
            if doc is not None and was_ready:
                doc.version = int(doc.version or 1) + 1
        store = get_store()
        collection = settings.collection("knowledge")
        if old_ids:
            try:
                store.delete(collection, ids=old_ids)
            except Exception as exc:  # noqa: BLE001
                record_degradation("ingest", f"old_vector_delete_failed:{type(exc).__name__}")
                logger.warning("删除旧向量失败 doc=%s err=%s", document_id, exc)

        # 写 chunk 行，拿到自增主键作为向量主键
        payloads: list[dict[str, Any]] = []
        with session_scope() as db:
            for chunk in chunks:
                row = KnowledgeChunk(
                    document_id=document_id,
                    chunk_no=chunk.index,
                    content=chunk.content,
                    parent_content=chunk.parent_content,
                    token_count=chunk.token_count,
                    meta=chunk.metadata,
                )
                db.add(row)
                db.flush()
                payloads.append(
                    {
                        "chunk_id": int(row.id),
                        "document_id": document_id,
                        "title": title,
                        "doc_type": doc_type,
                        "visibility": visibility,
                        "parent_content": chunk.parent_content,
                    }
                )
                chunk.metadata["chunkId"] = int(row.id)

        update_job(job_id, "RUNNING", 55)

        # 向量化 + 入库
        embedding = get_embedding()
        vectors = embedding.embed_documents([chunk.content for chunk in chunks])
        if len(vectors) != len(chunks):
            raise ValueError("embedding 数量与切片数量不一致")
        records = [
            VectorRecord(
                id=int(payload["chunk_id"]),
                vector=vector,
                content=chunk.content,
                payload=payload,
            )
            for chunk, vector, payload in zip(chunks, vectors, payloads, strict=True)
        ]
        store.ensure(collection, len(vectors[0]) if vectors else settings.embedding_dim)
        store.upsert(collection, records)

        total_tokens = sum(chunk.token_count for chunk in chunks)
        _set_document_status(document_id, "READY", chunk_count=len(chunks))
        update_job(job_id, "SUCCESS", 100)
        return {
            "ok": True,
            "skipped": False,
            "documentId": document_id,
            "chunkCount": len(chunks),
            "tokenCount": total_tokens,
            "store": store.name,
            "checksum": checksum,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("索引失败 doc=%s err=%s", document_id, exc)
        _set_document_status(document_id, "FAILED")
        update_job(job_id, "FAILED", error=str(exc))
        return {"ok": False, "error": str(exc), "documentId": document_id}


def delete_document(document_id: int, *, job_id: int | None = None) -> dict[str, Any]:
    """软删除文档 + 物理清理切片与向量。"""
    update_job(job_id, "RUNNING", 10)
    try:
        with session_scope() as db:
            doc = db.get(KnowledgeDocument, document_id)
            if doc is None:
                update_job(job_id, "FAILED", error="文档不存在")
                return {"ok": False, "error": "文档不存在"}
            doc.deleted_at = utcnow()
            doc.status = "PENDING"
            old_ids = [
                int(row[0])
                for row in db.query(KnowledgeChunk.id)
                .filter(KnowledgeChunk.document_id == document_id)
                .all()
            ]
            db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document_id).delete()
        if old_ids:
            try:
                get_store().delete(settings.collection("knowledge"), ids=old_ids)
            except Exception as exc:  # noqa: BLE001
                record_degradation("ingest", f"delete_vector_failed:{type(exc).__name__}")
                logger.warning("删除向量失败 doc=%s err=%s", document_id, exc)
        update_job(job_id, "SUCCESS", 100)
        return {"ok": True, "documentId": document_id, "deletedChunks": len(old_ids)}
    except Exception as exc:  # noqa: BLE001
        update_job(job_id, "FAILED", error=str(exc))
        return {"ok": False, "error": str(exc)}


def reindex_document(document_id: int, *, job_id: int | None = None) -> dict[str, Any]:
    """强制重建索引。"""
    return ingest_document(document_id, job_id=job_id, force=True)


def ingest_text(title: str, text: str, *, doc_type: str = "FAQ", visibility: str = "PUBLIC") -> dict[str, Any]:
    """脚本/测试用：直接以文本创建文档并索引。"""
    cleaned = clean_text(text)
    with session_scope() as db:
        doc = KnowledgeDocument(
            title=title,
            doc_type=doc_type,
            visibility=visibility,
            status="PENDING",
            chunk_count=0,
            checksum=checksum_text(cleaned),
            source=None,
        )
        db.add(doc)
        db.flush()
        document_id = int(doc.id)
        job = KnowledgeJob(document_id=document_id, job_type="INDEX", status="QUEUED")
        db.add(job)
        db.flush()
        job_id = int(job.id)
    result = ingest_document(document_id, job_id=job_id, content=text)
    result["jobId"] = job_id
    return result


def estimate_chunk_plan(text: str) -> dict[str, int]:
    """不落库的切片估算（前端/调试显示用）。"""
    chunks = chunk_document(
        text, size=settings.chunk_size, overlap=settings.chunk_overlap, parent_size=settings.parent_chunk_size
    )
    return {
        "chunks": len(chunks),
        "tokens": sum(chunk.token_count for chunk in chunks),
        "chars": sum(len(chunk.content) for chunk in chunks),
        "avgTokens": estimate_tokens(text) // max(len(chunks), 1),
    }


__all__ = [
    "SUPPORTED_EXTENSIONS",
    "delete_document",
    "estimate_chunk_plan",
    "ingest_document",
    "ingest_text",
    "parse_docx",
    "parse_file",
    "parse_pdf",
    "parse_text_file",
    "reindex_document",
    "update_job",
]
