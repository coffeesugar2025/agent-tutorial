package com.xingtu.agent.infra.repo;

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 会话表访问（chat_session）。
 */
@Repository
public class SessionRepository {

    public record SessionRow(long id, long userId, String title, String agentType, String status,
                             String summary, LocalDateTime lastMessageAt, LocalDateTime createdAt) {
    }

    private static final String SELECT = "SELECT id, user_id, title, agent_type, status, summary, "
            + "last_message_at, created_at FROM chat_session ";

    private final JdbcTemplate jdbc;

    public SessionRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public long insert(long userId, String title, String agentType) {
        return JdbcSupport.insertAndReturnKey(jdbc,
                "INSERT INTO chat_session (user_id, title, agent_type, status, last_message_at) "
                        + "VALUES (?, ?, ?, 'ACTIVE', CURRENT_TIMESTAMP(3))",
                userId, title == null || title.isBlank() ? "新会话" : title.trim(), agentType);
    }

    public SessionRow findById(long id) {
        return JdbcSupport.one(jdbc, SELECT + " WHERE id = ?", mapper(), id);
    }

    public List<SessionRow> listByUser(long userId, int limit) {
        return JdbcSupport.list(jdbc,
                SELECT + " WHERE user_id = ? AND status <> 'DELETED' "
                        + "ORDER BY COALESCE(last_message_at, created_at) DESC LIMIT ?",
                mapper(), userId, limit);
    }

    public boolean touch(long id, LocalDateTime at) {
        return JdbcSupport.update(jdbc,
                "UPDATE chat_session SET last_message_at = ? WHERE id = ?", at, id) > 0;
    }

    public boolean updateTitle(long id, String title) {
        return JdbcSupport.update(jdbc, "UPDATE chat_session SET title = ? WHERE id = ?", title, id) > 0;
    }

    public boolean updateSummary(long id, String summary) {
        return JdbcSupport.update(jdbc, "UPDATE chat_session SET summary = ? WHERE id = ?", summary, id) > 0;
    }

    public boolean updateAgentType(long id, String agentType) {
        return JdbcSupport.update(jdbc, "UPDATE chat_session SET agent_type = ? WHERE id = ?",
                agentType, id) > 0;
    }

    public boolean softDelete(long id, long userId) {
        return JdbcSupport.update(jdbc,
                "UPDATE chat_session SET status = 'DELETED' WHERE id = ? AND user_id = ?", id, userId) > 0;
    }

    public long countAll() {
        return JdbcSupport.count(jdbc, "SELECT COUNT(*) FROM chat_session WHERE status <> 'DELETED'");
    }

    public long countSince(LocalDateTime since) {
        return JdbcSupport.count(jdbc,
                "SELECT COUNT(*) FROM chat_session WHERE created_at >= ? AND status <> 'DELETED'", since);
    }

    private RowMapper<SessionRow> mapper() {
        return (rs, rowNum) -> new SessionRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.lng(rs, "user_id"),
                JdbcSupport.str(rs, "title"),
                JdbcSupport.str(rs, "agent_type"),
                JdbcSupport.str(rs, "status"),
                JdbcSupport.str(rs, "summary"),
                JdbcSupport.time(rs, "last_message_at"),
                JdbcSupport.time(rs, "created_at"));
    }
}
