"""知识库接口：上传、列表、删除、重建索引、作业进度、检索调试。"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, get_db, require_ops
from app.common.envelope import ok
from app.common.errors import not_found, param_invalid
from app.common.ids import checksum_bytes, new_ulid
from app.common.tracecontext import get_trace_id
from app.config import settings
from app.infra.models import KnowledgeDocument, KnowledgeJob
from app.security.ratelimit import limit_ingest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["知识库"])

ALLOWED_SUFFIX = {".md", ".txt", ".pdf", ".docx"}
DOC_TYPES = {"POLICY", "MANUAL", "FAQ", "PRODUCT_DOC"}
VISIBILITIES = {"PUBLIC", "INTERNAL", "ADMIN"}


class SearchReq(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    top_k: int = Field(default=5, ge=1, le=20, alias="topK")
    doc_types: list[str] | None = Field(default=None, alias="docTypes")
    mode: str = "hybrid"

    model_config = {"populate_by_name": True}


@router.post("/documents", summary="上传文档（异步索引）")
def upload_document(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    doc_type: str = Form(default="FAQ"),
    visibility: str = Form(default="PUBLIC"),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_ops),
):
    """保存文件 → 建文档与作业 → 投递索引任务。立即返回，不等索引完成。"""
    limit_ingest(user.id)

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise param_invalid(f"仅支持 {', '.join(sorted(ALLOWED_SUFFIX))} 格式")
    doc_type = doc_type.upper()
    visibility = visibility.upper()
    if doc_type not in DOC_TYPES:
        raise param_invalid(f"docType 必须是 {sorted(DOC_TYPES)}")
    if visibility not in VISIBILITIES:
        raise param_invalid(f"visibility 必须是 {sorted(VISIBILITIES)}")

    payload = file.file.read()
    limit_bytes = settings.max_upload_mb * 1024 * 1024
    if len(payload) > limit_bytes:
        raise param_invalid(f"文件超过 {settings.max_upload_mb}MB 限制")
    if not payload:
        raise param_invalid("文件内容为空")

    upload_dir = settings.upload_path
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{new_ulid()}{suffix}"
    target = upload_dir / safe_name
    target.write_bytes(payload)

    document = KnowledgeDocument(
        title=(title or Path(file.filename or "未命名").stem)[:255],
        doc_type=doc_type,
        source=str(target),
        visibility=visibility,
        status="PENDING",
        version=1,
        chunk_count=0,
        checksum=checksum_bytes(payload),
    )
    db.add(document)
    db.flush()

    job = KnowledgeJob(document_id=int(document.id), job_type="INDEX", status="QUEUED", progress=0)
    db.add(job)
    db.flush()
    db.commit()

    _publish("knowledge.index", {"documentId": int(document.id), "jobId": int(job.id)})
    return ok({"documentId": document.id, "jobId": job.id, "status": "QUEUED"})


@router.get("/documents", summary="文档列表")
def list_documents(
    doc_type: str | None = Query(default=None, alias="docType"),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    query = db.query(KnowledgeDocument).filter(KnowledgeDocument.deleted_at.is_(None))
    if doc_type:
        query = query.filter(KnowledgeDocument.doc_type == doc_type.upper())
    if status:
        query = query.filter(KnowledgeDocument.status == status.upper())
    rows = query.order_by(KnowledgeDocument.id.desc()).limit(200).all()
    return ok(
        [
            {
                "id": row.id,
                "title": row.title,
                "docType": row.doc_type,
                "visibility": row.visibility,
                "status": row.status,
                "version": row.version,
                "chunkCount": row.chunk_count,
                "createdAt": row.created_at.isoformat(timespec="seconds") if row.created_at else None,
            }
            for row in rows
        ]
    )


@router.delete("/documents/{document_id}", summary="删除文档（软删 + 异步清理向量）")
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_ops),
):
    row = db.get(KnowledgeDocument, document_id)
    if row is None or row.deleted_at is not None:
        raise not_found("文档不存在")

    job = KnowledgeJob(document_id=document_id, job_type="DELETE", status="QUEUED", progress=0)
    db.add(job)
    db.flush()
    db.commit()

    _publish("knowledge.delete", {"documentId": document_id, "jobId": int(job.id)})
    return ok({"jobId": job.id})


@router.post("/documents/{document_id}/reindex", summary="重建索引")
def reindex_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(require_ops),
):
    row = db.get(KnowledgeDocument, document_id)
    if row is None or row.deleted_at is not None:
        raise not_found("文档不存在")

    job = KnowledgeJob(document_id=document_id, job_type="REINDEX", status="QUEUED", progress=0)
    db.add(job)
    row.status = "PENDING"
    db.flush()
    db.commit()

    _publish("knowledge.index", {"documentId": document_id, "jobId": int(job.id), "force": True})
    return ok({"jobId": job.id})


@router.get("/jobs/{job_id}", summary="索引作业进度")
def get_job(job_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    row = db.get(KnowledgeJob, job_id)
    if row is None:
        raise not_found("作业不存在")
    return ok(
        {
            "id": row.id,
            "documentId": row.document_id,
            "jobType": row.job_type,
            "status": row.status,
            "progress": row.progress,
            "error": row.error,
        }
    )


@router.post("/search", summary="检索调试：dense/sparse/rerank 分数全透视")
async def search(req: SearchReq, user: CurrentUser = Depends(get_current_user)):
    """直接调用 RAG 检索管线，返回各阶段分数，用于调参与排障。"""
    from app.rag.retriever import hybrid_search

    result = await hybrid_search(
        query=req.query,
        top_k=req.top_k,
        doc_types=req.doc_types,
        mode=req.mode,
        visibility=None,
    )
    items = [_chunk_to_vo(chunk) for chunk in getattr(result, "chunks", [])]
    debug = getattr(result, "debug", {}) or {}
    debug.setdefault("traceId", get_trace_id())
    return ok({"items": items, "debug": debug, "degraded": getattr(result, "degraded", False)})


def _chunk_to_vo(chunk: Any) -> dict[str, Any]:
    """兼容 dataclass / dict 两种返回形态。"""
    get = chunk.get if isinstance(chunk, dict) else lambda k, d=None: getattr(chunk, k, d)
    return {
        "chunkId": get("chunk_id") or get("chunkId"),
        "documentId": get("document_id") or get("documentId"),
        "title": get("title") or "",
        "content": (get("content") or "")[:800],
        "score": float(get("score") or 0.0),
        "denseScore": get("dense_score") or get("denseScore"),
        "sparseScore": get("sparse_score") or get("sparseScore"),
        "rerankScore": get("rerank_score") or get("rerankScore"),
        "route": get("route") or "",
    }


def _publish(routing_key: str, payload: dict[str, Any]) -> None:
    """投递 MQ；失败落 async_task 由本地 drainer 兜底。"""
    try:
        from app.infra.rabbit import message_bus

        message_bus.publish(routing_key, payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("投递 %s 失败: %s", routing_key, exc)


__all__ = ["router"]
