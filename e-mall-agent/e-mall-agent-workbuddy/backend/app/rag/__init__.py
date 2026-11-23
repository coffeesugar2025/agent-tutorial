"""RAG 子包：基础层（解析/切片/向量）到高阶层（治理/引用/图谱）。

本文件只做重导出，原有 ``from app.rag.pipeline import RAGPipeline`` 等导入保持可用。
"""
from .embeddings import HashEmbeddings, tokenize
from .pipeline import (
    RAGPipeline,
    SEED_DOCS,
    get_rag_pipeline,
    reset_rag_pipeline,
)

from .citation import (
    AnswerWithCitations,
    Citation,
    CitationValidator,
    GroundednessReport,
    GroundednessScorer,
)
from .governance import AuditEntry, KnowledgeAudit, Version, VersionedStore
from .graphrag import (
    Entity,
    GraphContext,
    GraphRAGRetriever,
    KnowledgeGraph,
    Relation,
    Subgraph,
)
from .hybrid import (
    BM25Hit,
    BM25Index,
    HybridRetriever,
    Reranker,
    RetrievedChunk,
    SourceDetail,
    bm25_tokenize,
)
from .ingest import (
    SUPPORTED_FORMATS,
    SUPPORTED_STRATEGIES,
    Chunk,
    Chunker,
    Document,
    Section,
    chunk_document,
    parse_document,
    parse_json,
    parse_markdown,
    parse_text,
)
from .text2sql import (
    ALLOWED_TABLES,
    CypherQuery,
    SQLResult,
    Text2Cypher,
    Text2SQL,
    create_demo_db,
    validate_select,
)

__all__ = [
    # 原有导出
    "HashEmbeddings", "tokenize", "RAGPipeline", "SEED_DOCS",
    "get_rag_pipeline", "reset_rag_pipeline",
    # 新增导出
    "Citation", "AnswerWithCitations", "CitationValidator",
    "GroundednessScorer", "GroundednessReport",
    "KnowledgeAudit", "AuditEntry", "VersionedStore", "Version",
    "KnowledgeGraph", "Entity", "Relation", "Subgraph",
    "GraphRAGRetriever", "GraphContext",
    "BM25Index", "BM25Hit", "HybridRetriever", "Reranker",
    "RetrievedChunk", "SourceDetail", "bm25_tokenize",
    "Chunk", "Section", "Document", "Chunker", "chunk_document",
    "parse_document", "parse_text", "parse_markdown", "parse_json",
    "SUPPORTED_FORMATS", "SUPPORTED_STRATEGIES",
    "Text2SQL", "Text2Cypher", "SQLResult", "CypherQuery",
    "create_demo_db", "validate_select", "ALLOWED_TABLES",
]
