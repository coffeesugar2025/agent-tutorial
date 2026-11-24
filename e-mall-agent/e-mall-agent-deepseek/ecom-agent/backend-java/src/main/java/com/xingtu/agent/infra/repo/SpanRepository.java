package com.xingtu.agent.infra.repo;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-12] 检索增强 RAG  （支撑）
// 职责：链路 span 访问（agent_span），同时提供工具调用统计
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 链路 span 访问（agent_span），同时提供工具调用统计。
 */
@Repository
public class SpanRepository {

    public record SpanRow(long id, String traceId, String spanId, String parentSpanId, String name,
                          String spanType, int seq, String inputJson, String outputJson, int latencyMs,
                          String status, String error, LocalDateTime startedAt) {
    }

    public record ToolCount(String name, long count) {
    }

    private static final String SELECT = "SELECT id, trace_id, span_id, parent_span_id, name, span_type, seq, "
            + "input, output, latency_ms, status, error, started_at FROM agent_span ";

    private final JdbcTemplate jdbc;

    public SpanRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void insert(String traceId, String spanId, String parentSpanId, String name, String spanType,
                       int seq, String inputJson, String outputJson, int latencyMs, String status,
                       String error) {
        JdbcSupport.update(jdbc,
                "INSERT INTO agent_span (trace_id, span_id, parent_span_id, name, span_type, seq, input, "
                        + "output, latency_ms, status, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                traceId, spanId, parentSpanId, name, spanType, seq, inputJson, outputJson, latencyMs,
                status, error);
    }

    public List<SpanRow> listByTrace(String traceId) {
        return JdbcSupport.list(jdbc, SELECT + " WHERE trace_id = ? ORDER BY seq, id", mapper(), traceId);
    }

    public long countToolCallsSince(LocalDateTime since) {
        return JdbcSupport.count(jdbc,
                "SELECT COUNT(*) FROM agent_span WHERE span_type = 'TOOL' AND started_at >= ?", since);
    }

    public long countToolErrorsSince(LocalDateTime since) {
        return JdbcSupport.count(jdbc,
                "SELECT COUNT(*) FROM agent_span WHERE span_type = 'TOOL' AND started_at >= ? "
                        + "AND status <> 'OK'", since);
    }

    public List<ToolCount> topToolsSince(LocalDateTime since, int limit) {
        return JdbcSupport.list(jdbc,
                "SELECT name, COUNT(*) AS cnt FROM agent_span WHERE span_type = 'TOOL' AND started_at >= ? "
                        + "GROUP BY name ORDER BY cnt DESC LIMIT ?",
                (rs, rowNum) -> new ToolCount(JdbcSupport.str(rs, "name"), JdbcSupport.lng(rs, "cnt")),
                since, limit);
    }

    private RowMapper<SpanRow> mapper() {
        return (rs, rowNum) -> new SpanRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.str(rs, "trace_id"),
                JdbcSupport.str(rs, "span_id"),
                JdbcSupport.str(rs, "parent_span_id"),
                JdbcSupport.str(rs, "name"),
                JdbcSupport.str(rs, "span_type"),
                JdbcSupport.intVal(rs, "seq"),
                JdbcSupport.str(rs, "input"),
                JdbcSupport.str(rs, "output"),
                JdbcSupport.intVal(rs, "latency_ms"),
                JdbcSupport.str(rs, "status"),
                JdbcSupport.str(rs, "error"),
                JdbcSupport.time(rs, "started_at"));
    }
}
