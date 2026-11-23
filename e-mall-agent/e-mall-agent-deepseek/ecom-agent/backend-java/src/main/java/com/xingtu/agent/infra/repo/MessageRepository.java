package com.xingtu.agent.infra.repo;

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 消息表访问（chat_message）。
 */
@Repository
public class MessageRepository {

    public record MessageRow(long id, long sessionId, String role, String content, String agentType,
                             String toolCalls, String citations, int tokenIn, int tokenOut, int costCents,
                             String traceId, LocalDateTime createdAt) {
    }

    /** 插入参数集中封装，避免长参数列表。 */
    public record MessageInsert(long sessionId, String role, String content, String agentType,
                                String toolCallsJson, String citationsJson, int tokenIn, int tokenOut,
                                int costCents, String traceId) {
    }

    private static final String SELECT = "SELECT id, session_id, role, content, agent_type, tool_calls, "
            + "citations, token_in, token_out, cost_cents, trace_id, created_at FROM chat_message ";

    private final JdbcTemplate jdbc;

    public MessageRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public long insert(MessageInsert message) {
        return JdbcSupport.insertAndReturnKey(jdbc,
                "INSERT INTO chat_message (session_id, role, content, agent_type, tool_calls, citations, "
                        + "token_in, token_out, cost_cents, trace_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                message.sessionId(), message.role(), message.content(), message.agentType(),
                message.toolCallsJson(), message.citationsJson(), message.tokenIn(), message.tokenOut(),
                message.costCents(), message.traceId());
    }

    /** 最近 N 条，按时间正序返回（便于拼 prompt）。 */
    public List<MessageRow> recent(long sessionId, int limit) {
        return JdbcSupport.list(jdbc,
                "SELECT * FROM (SELECT " + SELECT.substring("SELECT ".length())
                        + " WHERE session_id = ? ORDER BY id DESC LIMIT ?) t ORDER BY id ASC",
                mapper(), sessionId, limit);
    }

    /** 展示用：最近 N 条，正序。 */
    public List<MessageRow> list(long sessionId, int limit) {
        return recent(sessionId, limit);
    }

    public MessageRow findById(long id) {
        return JdbcSupport.one(jdbc, SELECT + " WHERE id = ?", mapper(), id);
    }

    public long countBySession(long sessionId) {
        return JdbcSupport.count(jdbc, "SELECT COUNT(*) FROM chat_message WHERE session_id = ?", sessionId);
    }

    public long countSince(LocalDateTime since) {
        return JdbcSupport.count(jdbc, "SELECT COUNT(*) FROM chat_message WHERE created_at >= ?", since);
    }

    private RowMapper<MessageRow> mapper() {
        return (rs, rowNum) -> new MessageRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.lng(rs, "session_id"),
                JdbcSupport.str(rs, "role"),
                JdbcSupport.str(rs, "content"),
                JdbcSupport.str(rs, "agent_type"),
                JdbcSupport.str(rs, "tool_calls"),
                JdbcSupport.str(rs, "citations"),
                JdbcSupport.intVal(rs, "token_in"),
                JdbcSupport.intVal(rs, "token_out"),
                JdbcSupport.intVal(rs, "cost_cents"),
                JdbcSupport.str(rs, "trace_id"),
                JdbcSupport.time(rs, "created_at"));
    }
}
