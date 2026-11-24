package com.xingtu.agent.infra.repo;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-12] 检索增强 RAG  （支撑）
// 职责：链路追踪根节点访问（agent_trace），同时提供运营大盘的聚合查询
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 链路追踪根节点访问（agent_trace），同时提供运营大盘的聚合查询。
 */
@Repository
public class TraceRepository {

    public record TraceRow(long id, String traceId, long sessionId, long userId, String agentType,
                           String question, String answer, String status, int totalLatencyMs,
                           int totalCostCents, int stepCount, LocalDateTime createdAt) {
    }

    private static final String SELECT = "SELECT id, trace_id, session_id, user_id, agent_type, question, "
            + "answer, status, total_latency_ms, total_cost_cents, step_count, created_at FROM agent_trace ";

    private final JdbcTemplate jdbc;

    public TraceRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void insert(String traceId, long sessionId, long userId, String agentType, String question) {
        JdbcSupport.update(jdbc,
                "INSERT INTO agent_trace (trace_id, session_id, user_id, agent_type, question, status) "
                        + "VALUES (?, ?, ?, ?, ?, 'RUNNING')",
                traceId, sessionId, userId, agentType, question);
    }

    public void finish(String traceId, String status, int latencyMs, int costCents, int stepCount,
                       String answer) {
        JdbcSupport.update(jdbc,
                "UPDATE agent_trace SET status = ?, total_latency_ms = ?, total_cost_cents = ?, "
                        + "step_count = ?, answer = ? WHERE trace_id = ?",
                status, latencyMs, costCents, stepCount, answer, traceId);
    }

    public TraceRow findByTraceId(String traceId) {
        return JdbcSupport.one(jdbc, SELECT + " WHERE trace_id = ?", mapper(), traceId);
    }

    public List<TraceRow> list(Long sessionId, String status, int limit) {
        if (sessionId != null && sessionId > 0 && status != null && !status.isBlank()) {
            return JdbcSupport.list(jdbc,
                    SELECT + " WHERE session_id = ? AND status = ? ORDER BY id DESC LIMIT ?",
                    mapper(), sessionId, status, limit);
        }
        if (sessionId != null && sessionId > 0) {
            return JdbcSupport.list(jdbc, SELECT + " WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                    mapper(), sessionId, limit);
        }
        if (status != null && !status.isBlank()) {
            return JdbcSupport.list(jdbc, SELECT + " WHERE status = ? ORDER BY id DESC LIMIT ?",
                    mapper(), status, limit);
        }
        return JdbcSupport.list(jdbc, SELECT + " ORDER BY id DESC LIMIT ?", mapper(), limit);
    }

    public long countSince(LocalDateTime since) {
        return JdbcSupport.count(jdbc, "SELECT COUNT(*) FROM agent_trace WHERE created_at >= ?", since);
    }

    public long countSuccessSince(LocalDateTime since) {
        return JdbcSupport.count(jdbc,
                "SELECT COUNT(*) FROM agent_trace WHERE created_at >= ? AND status = 'SUCCESS'", since);
    }

    public List<Integer> latenciesSince(LocalDateTime since, int limit) {
        return jdbc.queryForList(
                "SELECT total_latency_ms FROM agent_trace WHERE created_at >= ? AND status IN ('SUCCESS','FAILED') "
                        + "ORDER BY id DESC LIMIT ?",
                Integer.class, since, limit);
    }

    private RowMapper<TraceRow> mapper() {
        return (rs, rowNum) -> new TraceRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.str(rs, "trace_id"),
                JdbcSupport.lng(rs, "session_id"),
                JdbcSupport.lng(rs, "user_id"),
                JdbcSupport.str(rs, "agent_type"),
                JdbcSupport.str(rs, "question"),
                JdbcSupport.str(rs, "answer"),
                JdbcSupport.str(rs, "status"),
                JdbcSupport.intVal(rs, "total_latency_ms"),
                JdbcSupport.intVal(rs, "total_cost_cents"),
                JdbcSupport.intVal(rs, "step_count"),
                JdbcSupport.time(rs, "created_at"));
    }
}
