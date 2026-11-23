package com.xingtu.agent.infra.repo;

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 索引作业访问（knowledge_job）。
 */
@Repository
public class JobRepository {

    public record JobRow(long id, long documentId, String jobType, String status, int progress,
                         String error, LocalDateTime createdAt, LocalDateTime updatedAt) {
    }

    private static final String SELECT = "SELECT id, document_id, job_type, status, progress, error, "
            + "created_at, updated_at FROM knowledge_job ";

    private final JdbcTemplate jdbc;

    public JobRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public long insert(long documentId, String jobType, String status) {
        return JdbcSupport.insertAndReturnKey(jdbc,
                "INSERT INTO knowledge_job (document_id, job_type, status, progress) VALUES (?, ?, ?, 0)",
                documentId, jobType, status);
    }

    public JobRow findById(long id) {
        return JdbcSupport.one(jdbc, SELECT + " WHERE id = ?", mapper(), id);
    }

    public boolean update(long id, String status, int progress, String error) {
        return JdbcSupport.update(jdbc,
                "UPDATE knowledge_job SET status = ?, progress = ?, error = ? WHERE id = ?",
                status, progress, error, id) > 0;
    }

    public List<JobRow> listByDocument(long documentId) {
        return JdbcSupport.list(jdbc, SELECT + " WHERE document_id = ? ORDER BY id DESC",
                mapper(), documentId);
    }

    private RowMapper<JobRow> mapper() {
        return (rs, rowNum) -> new JobRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.lng(rs, "document_id"),
                JdbcSupport.str(rs, "job_type"),
                JdbcSupport.str(rs, "status"),
                JdbcSupport.intVal(rs, "progress"),
                JdbcSupport.str(rs, "error"),
                JdbcSupport.time(rs, "created_at"),
                JdbcSupport.time(rs, "updated_at"));
    }
}
