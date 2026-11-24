package com.xingtu.agent.infra.repo;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-12] 检索增强 RAG  （支撑）
// 职责：长任务检查点访问（agent_checkpoint）：按 (trace_id, step_no) 唯一，可重放
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 长任务检查点访问（agent_checkpoint）：按 (trace_id, step_no) 唯一，可重放。
 */
@Repository
public class CheckpointRepository {

    public record CheckpointRow(long id, long sessionId, String traceId, int stepNo, String stateJson,
                                LocalDateTime createdAt) {
    }

    private final JdbcTemplate jdbc;

    public CheckpointRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void save(long sessionId, String traceId, int stepNo, String stateJson) {
        JdbcSupport.update(jdbc,
                "INSERT INTO agent_checkpoint (session_id, trace_id, step_no, state) VALUES (?, ?, ?, ?) "
                        + "ON DUPLICATE KEY UPDATE state = VALUES(state)",
                sessionId, traceId, stepNo, stateJson);
    }

    public List<CheckpointRow> listByTrace(String traceId) {
        return JdbcSupport.list(jdbc,
                "SELECT id, session_id, trace_id, step_no, state, created_at FROM agent_checkpoint "
                        + "WHERE trace_id = ? ORDER BY step_no",
                mapper(), traceId);
    }

    public CheckpointRow latest(String traceId) {
        return JdbcSupport.one(jdbc,
                "SELECT id, session_id, trace_id, step_no, state, created_at FROM agent_checkpoint "
                        + "WHERE trace_id = ? ORDER BY step_no DESC LIMIT 1",
                mapper(), traceId);
    }

    private RowMapper<CheckpointRow> mapper() {
        return (rs, rowNum) -> new CheckpointRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.lng(rs, "session_id"),
                JdbcSupport.str(rs, "trace_id"),
                JdbcSupport.intVal(rs, "step_no"),
                JdbcSupport.str(rs, "state"),
                JdbcSupport.time(rs, "created_at"));
    }
}
