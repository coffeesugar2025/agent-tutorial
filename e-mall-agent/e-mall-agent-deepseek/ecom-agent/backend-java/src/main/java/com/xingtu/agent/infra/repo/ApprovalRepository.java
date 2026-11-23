package com.xingtu.agent.infra.repo;

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 人工审批任务访问（approval_task）。
 */
@Repository
public class ApprovalRepository {

    public record ApprovalRow(long id, long sessionId, Long messageId, long userId, String actionType,
                              String title, String detailJson, String risk, String status,
                              String decisionComment, Long decidedBy, LocalDateTime createdAt,
                              LocalDateTime expiresAt, LocalDateTime decidedAt) {
    }

    private static final String SELECT = "SELECT id, session_id, message_id, user_id, action_type, title, "
            + "detail, risk, status, decision_comment, decided_by, created_at, expires_at, decided_at "
            + "FROM approval_task ";

    private final JdbcTemplate jdbc;

    public ApprovalRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public long insert(long sessionId, Long messageId, long userId, String actionType, String title,
                       String detailJson, String risk, String status, LocalDateTime expiresAt) {
        return JdbcSupport.insertAndReturnKey(jdbc,
                "INSERT INTO approval_task (session_id, message_id, user_id, action_type, title, detail, "
                        + "risk, status, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                sessionId, messageId, userId, actionType, title, detailJson, risk, status, expiresAt);
    }

    public ApprovalRow findById(long id) {
        return JdbcSupport.one(jdbc, SELECT + " WHERE id = ?", mapper(), id);
    }

    public List<ApprovalRow> listByUser(long userId, String status, int limit) {
        Object[] args;
        String sql = SELECT;
        if (status == null || status.isBlank()) {
            sql = sql + " WHERE user_id = ? ORDER BY id DESC LIMIT ?";
            args = new Object[]{userId, limit};
        } else {
            sql = sql + " WHERE user_id = ? AND status = ? ORDER BY id DESC LIMIT ?";
            args = new Object[]{userId, status, limit};
        }
        return JdbcSupport.list(jdbc, sql, mapper(), args);
    }

    public List<ApprovalRow> listBySession(long sessionId, String status, int limit) {
        if (status == null || status.isBlank()) {
            return JdbcSupport.list(jdbc, SELECT + " WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                    mapper(), sessionId, limit);
        }
        return JdbcSupport.list(jdbc,
                SELECT + " WHERE session_id = ? AND status = ? ORDER BY id DESC LIMIT ?",
                mapper(), sessionId, status, limit);
    }

    public boolean decide(long id, String fromStatus, String toStatus, String comment, long decidedBy) {
        return JdbcSupport.update(jdbc,
                "UPDATE approval_task SET status = ?, decision_comment = ?, decided_by = ?, decided_at = ? "
                        + "WHERE id = ? AND status = ?",
                toStatus, comment, decidedBy, LocalDateTime.now(), id, fromStatus) > 0;
    }

    public long countPending() {
        return JdbcSupport.count(jdbc, "SELECT COUNT(*) FROM approval_task WHERE status = 'PENDING'");
    }

    public long countPendingByUser(long userId) {
        return JdbcSupport.count(jdbc,
                "SELECT COUNT(*) FROM approval_task WHERE user_id = ? AND status = 'PENDING'", userId);
    }

    public int expireStale(LocalDateTime now) {
        return JdbcSupport.update(jdbc,
                "UPDATE approval_task SET status = 'EXPIRED' WHERE status = 'PENDING' AND expires_at IS NOT NULL "
                        + "AND expires_at < ?", now);
    }

    private RowMapper<ApprovalRow> mapper() {
        return (rs, rowNum) -> new ApprovalRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.lng(rs, "session_id"),
                rs.getObject("message_id") == null ? null : JdbcSupport.lng(rs, "message_id"),
                JdbcSupport.lng(rs, "user_id"),
                JdbcSupport.str(rs, "action_type"),
                JdbcSupport.str(rs, "title"),
                JdbcSupport.str(rs, "detail"),
                JdbcSupport.str(rs, "risk"),
                JdbcSupport.str(rs, "status"),
                JdbcSupport.str(rs, "decision_comment"),
                rs.getObject("decided_by") == null ? null : JdbcSupport.lng(rs, "decided_by"),
                JdbcSupport.time(rs, "created_at"),
                JdbcSupport.time(rs, "expires_at"),
                JdbcSupport.time(rs, "decided_at"));
    }
}
