package com.xingtu.agent.infra.repo;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-12] 检索增强 RAG  （支撑）
// 职责：知识库文档与切片访问（knowledge_document / knowledge_chunk）
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * 知识库文档与切片访问（knowledge_document / knowledge_chunk）。
 */
@Repository
public class KnowledgeRepository {

    public record DocumentRow(long id, String title, String docType, String source, String visibility,
                              String status, int version, int chunkCount, String checksum,
                              LocalDateTime createdAt, LocalDateTime deletedAt) {
    }

    public record ChunkRow(long id, long documentId, int chunkNo, String content, String parentContent,
                           int tokenCount, String metadata) {
    }

    private final JdbcTemplate jdbc;

    public KnowledgeRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public long insertDocument(String title, String docType, String source, String visibility,
                               String status, String checksum) {
        return JdbcSupport.insertAndReturnKey(jdbc,
                "INSERT INTO knowledge_document (title, doc_type, source, visibility, status, version, "
                        + "chunk_count, checksum) VALUES (?, ?, ?, ?, ?, 1, 0, ?)",
                title, docType, source, visibility, status, checksum);
    }

    public DocumentRow findDocument(long id) {
        return JdbcSupport.one(jdbc,
                "SELECT id, title, doc_type, source, visibility, status, version, chunk_count, checksum, "
                        + "created_at, deleted_at FROM knowledge_document WHERE id = ?",
                documentMapper(), id);
    }

    public List<DocumentRow> listDocuments(String docType, String status, int limit) {
        StringBuilder sql = new StringBuilder("SELECT id, title, doc_type, source, visibility, status, version, "
                + "chunk_count, checksum, created_at, deleted_at FROM knowledge_document "
                + "WHERE deleted_at IS NULL");
        List<Object> args = new ArrayList<>();
        if (docType != null && !docType.isBlank()) {
            sql.append(" AND doc_type = ?");
            args.add(docType);
        }
        if (status != null && !status.isBlank()) {
            sql.append(" AND status = ?");
            args.add(status);
        }
        sql.append(" ORDER BY id DESC LIMIT ?");
        args.add(limit);
        return JdbcSupport.list(jdbc, sql.toString(), documentMapper(), args.toArray());
    }

    public boolean updateStatus(long id, String status) {
        return JdbcSupport.update(jdbc, "UPDATE knowledge_document SET status = ? WHERE id = ?",
                status, id) > 0;
    }

    public boolean markReady(long id, int chunkCount) {
        return JdbcSupport.update(jdbc,
                "UPDATE knowledge_document SET status = 'READY', chunk_count = ? WHERE id = ?",
                chunkCount, id) > 0;
    }

    public boolean markIndexing(long id) {
        return JdbcSupport.update(jdbc, "UPDATE knowledge_document SET status = 'INDEXING' WHERE id = ?", id) > 0;
    }

    public boolean softDelete(long id) {
        return JdbcSupport.update(jdbc,
                "UPDATE knowledge_document SET deleted_at = ?, status = 'DELETED' WHERE id = ?",
                LocalDateTime.now(), id) > 0;
    }

    public long insertChunk(long documentId, int chunkNo, String content, String parentContent,
                            int tokenCount, String metadataJson) {
        return JdbcSupport.insertAndReturnKey(jdbc,
                "INSERT INTO knowledge_chunk (document_id, chunk_no, content, parent_content, token_count, "
                        + "metadata) VALUES (?, ?, ?, ?, ?, ?)",
                documentId, chunkNo, content, parentContent, tokenCount, metadataJson);
    }

    public int deleteChunks(long documentId) {
        return JdbcSupport.update(jdbc, "DELETE FROM knowledge_chunk WHERE document_id = ?", documentId);
    }

    public List<ChunkRow> chunks(long documentId) {
        return JdbcSupport.list(jdbc,
                "SELECT id, document_id, chunk_no, content, parent_content, token_count, metadata "
                        + "FROM knowledge_chunk WHERE document_id = ? ORDER BY chunk_no",
                chunkMapper(), documentId);
    }

    public List<ChunkRow> chunksByIds(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return List.of();
        }
        StringBuilder sql = new StringBuilder("SELECT id, document_id, chunk_no, content, parent_content, "
                + "token_count, metadata FROM knowledge_chunk WHERE id IN (");
        List<Object> args = new ArrayList<>();
        for (int i = 0; i < ids.size(); i++) {
            sql.append(i == 0 ? "?" : ",?");
            args.add(ids.get(i));
        }
        sql.append(")");
        return JdbcSupport.list(jdbc, sql.toString(), chunkMapper(), args.toArray());
    }

    /** 全量候选（稀疏检索 / 进程内向量降级用），按 id 倒序取最近 N 条。 */
    public List<ChunkRow> recentChunks(int limit) {
        return JdbcSupport.list(jdbc,
                "SELECT c.id, c.document_id, c.chunk_no, c.content, c.parent_content, c.token_count, c.metadata "
                        + "FROM knowledge_chunk c JOIN knowledge_document d ON d.id = c.document_id "
                        + "WHERE d.deleted_at IS NULL ORDER BY c.id DESC LIMIT ?",
                chunkMapper(), limit);
    }

    public List<ChunkRow> searchByKeyword(String term, int limit) {
        if (term == null || term.isBlank()) {
            return List.of();
        }
        return JdbcSupport.list(jdbc,
                "SELECT c.id, c.document_id, c.chunk_no, c.content, c.parent_content, c.token_count, c.metadata "
                        + "FROM knowledge_chunk c JOIN knowledge_document d ON d.id = c.document_id "
                        + "WHERE d.deleted_at IS NULL AND c.content LIKE ? ORDER BY c.id DESC LIMIT ?",
                chunkMapper(), "%" + term.trim() + "%", limit);
    }

    public List<DocumentRow> documentsByIds(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return List.of();
        }
        StringBuilder sql = new StringBuilder("SELECT id, title, doc_type, source, visibility, status, version, "
                + "chunk_count, checksum, created_at, deleted_at FROM knowledge_document WHERE id IN (");
        List<Object> args = new ArrayList<>();
        for (int i = 0; i < ids.size(); i++) {
            sql.append(i == 0 ? "?" : ",?");
            args.add(ids.get(i));
        }
        sql.append(")");
        return JdbcSupport.list(jdbc, sql.toString(), documentMapper(), args.toArray());
    }

    private RowMapper<DocumentRow> documentMapper() {
        return (rs, rowNum) -> new DocumentRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.str(rs, "title"),
                JdbcSupport.str(rs, "doc_type"),
                JdbcSupport.str(rs, "source"),
                JdbcSupport.str(rs, "visibility"),
                JdbcSupport.str(rs, "status"),
                JdbcSupport.intVal(rs, "version"),
                JdbcSupport.intVal(rs, "chunk_count"),
                JdbcSupport.str(rs, "checksum"),
                JdbcSupport.time(rs, "created_at"),
                JdbcSupport.time(rs, "deleted_at"));
    }

    private RowMapper<ChunkRow> chunkMapper() {
        return (rs, rowNum) -> new ChunkRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.lng(rs, "document_id"),
                JdbcSupport.intVal(rs, "chunk_no"),
                JdbcSupport.str(rs, "content"),
                JdbcSupport.str(rs, "parent_content"),
                JdbcSupport.intVal(rs, "token_count"),
                JdbcSupport.str(rs, "metadata"));
    }
}
