package com.xingtu.agent.infra.repo;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-12] 检索增强 RAG  （支撑）
// 职责：评测批次与用例结果访问（eval_run / eval_case_result）
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 评测批次与用例结果访问（eval_run / eval_case_result）。
 */
@Repository
public class EvalRepository {

    public record EvalRunRow(long id, String suite, String status, int total, int passed,
                             BigDecimal passRate, BigDecimal passK, int repeatTimes, int avgCostCents,
                             int avgLatencyMs, LocalDateTime startedAt, LocalDateTime finishedAt) {
    }

    public record EvalCaseRow(long id, long runId, String caseId, String question, String expected,
                              String actual, boolean passed, BigDecimal score, int attempts,
                              String detailJson) {
    }

    private final JdbcTemplate jdbc;

    public EvalRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public long insertRun(String suite, int repeatTimes) {
        return JdbcSupport.insertAndReturnKey(jdbc,
                "INSERT INTO eval_run (suite, status, repeat_times) VALUES (?, 'RUNNING', ?)",
                suite, repeatTimes);
    }

    public boolean finishRun(long id, String status, int total, int passed, double passRate, double passK,
                             int avgCostCents, int avgLatencyMs, String reportJson) {
        return JdbcSupport.update(jdbc,
                "UPDATE eval_run SET status = ?, total = ?, passed = ?, pass_rate = ?, pass_k = ?, "
                        + "avg_cost_cents = ?, avg_latency_ms = ?, report = ?, finished_at = ? WHERE id = ?",
                status, total, passed, BigDecimal.valueOf(passRate), BigDecimal.valueOf(passK),
                avgCostCents, avgLatencyMs, reportJson, LocalDateTime.now(), id) > 0;
    }

    public EvalRunRow findRun(long id) {
        return JdbcSupport.one(jdbc,
                "SELECT id, suite, status, total, passed, pass_rate, pass_k, repeat_times, avg_cost_cents, "
                        + "avg_latency_ms, started_at, finished_at FROM eval_run WHERE id = ?",
                runMapper(), id);
    }

    public List<EvalRunRow> listRuns(int limit) {
        return JdbcSupport.list(jdbc,
                "SELECT id, suite, status, total, passed, pass_rate, pass_k, repeat_times, avg_cost_cents, "
                        + "avg_latency_ms, started_at, finished_at FROM eval_run ORDER BY id DESC LIMIT ?",
                runMapper(), limit);
    }

    public long insertCase(long runId, String caseId, String question, String expected, String actual,
                           boolean passed, double score, int attempts, String detailJson) {
        return JdbcSupport.insertAndReturnKey(jdbc,
                "INSERT INTO eval_case_result (run_id, case_id, question, expected, actual, passed, score, "
                        + "attempts, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                runId, caseId, question, expected, actual, passed ? 1 : 0,
                BigDecimal.valueOf(score), attempts, detailJson);
    }

    public List<EvalCaseRow> cases(long runId) {
        return JdbcSupport.list(jdbc,
                "SELECT id, run_id, case_id, question, expected, actual, passed, score, attempts, detail "
                        + "FROM eval_case_result WHERE run_id = ? ORDER BY id",
                caseMapper(), runId);
    }

    private RowMapper<EvalRunRow> runMapper() {
        return (rs, rowNum) -> new EvalRunRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.str(rs, "suite"),
                JdbcSupport.str(rs, "status"),
                JdbcSupport.intVal(rs, "total"),
                JdbcSupport.intVal(rs, "passed"),
                JdbcSupport.dec(rs, "pass_rate"),
                JdbcSupport.dec(rs, "pass_k"),
                JdbcSupport.intVal(rs, "repeat_times"),
                JdbcSupport.intVal(rs, "avg_cost_cents"),
                JdbcSupport.intVal(rs, "avg_latency_ms"),
                JdbcSupport.time(rs, "started_at"),
                JdbcSupport.time(rs, "finished_at"));
    }

    private RowMapper<EvalCaseRow> caseMapper() {
        return (rs, rowNum) -> new EvalCaseRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.lng(rs, "run_id"),
                JdbcSupport.str(rs, "case_id"),
                JdbcSupport.str(rs, "question"),
                JdbcSupport.str(rs, "expected"),
                JdbcSupport.str(rs, "actual"),
                JdbcSupport.intVal(rs, "passed") == 1,
                JdbcSupport.dec(rs, "score"),
                JdbcSupport.intVal(rs, "attempts"),
                JdbcSupport.str(rs, "detail"));
    }
}
