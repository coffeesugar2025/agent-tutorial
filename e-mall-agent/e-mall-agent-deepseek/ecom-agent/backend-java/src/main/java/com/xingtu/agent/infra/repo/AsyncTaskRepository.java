package com.xingtu.agent.infra.repo;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-12] 检索增强 RAG  （支撑）
// 职责：异步任务访问（async_task）：MQ 消费失败落库兜底，3 次重试后 DEAD
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 异步任务访问（async_task）：MQ 消费失败落库兜底，3 次重试后 DEAD。
 */
@Repository
public class AsyncTaskRepository {

    public record TaskRow(long id, String taskType, String payloadJson, String status, int retry,
                          int maxRetry, String error, LocalDateTime createdAt, LocalDateTime updatedAt) {
    }

    private static final String SELECT = "SELECT id, task_type, payload, status, retry, max_retry, error, "
            + "created_at, updated_at FROM async_task ";

    private final JdbcTemplate jdbc;

    public AsyncTaskRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public long insert(String taskType, String payloadJson, int maxRetry) {
        return JdbcSupport.insertAndReturnKey(jdbc,
                "INSERT INTO async_task (task_type, payload, status, retry, max_retry) "
                        + "VALUES (?, ?, 'QUEUED', 0, ?)",
                taskType, payloadJson, maxRetry);
    }

    public boolean updateStatus(long id, String status, String error) {
        return JdbcSupport.update(jdbc,
                "UPDATE async_task SET status = ?, error = ? WHERE id = ?", status, error, id) > 0;
    }

    public boolean markRunning(long id) {
        return JdbcSupport.update(jdbc, "UPDATE async_task SET status = 'RUNNING' WHERE id = ?", id) > 0;
    }

    /**
     * 记录一次失败：retry+1，达到 max_retry 直接置 DEAD，否则置 FAILED 等待重投。
     */
    public String recordFailure(long id, String error) {
        TaskRow row = findById(id);
        int maxRetry = row == null ? 3 : row.maxRetry();
        int retry = (row == null ? 0 : row.retry()) + 1;
        String status = retry >= maxRetry ? "DEAD" : "FAILED";
        JdbcSupport.update(jdbc,
                "UPDATE async_task SET retry = ?, status = ?, error = ? WHERE id = ?",
                retry, status, error, id);
        return status;
    }

    public TaskRow findById(long id) {
        return JdbcSupport.one(jdbc, SELECT + " WHERE id = ?", mapper(), id);
    }

    public List<TaskRow> listRecent(int limit) {
        return JdbcSupport.list(jdbc, SELECT + " ORDER BY id DESC LIMIT ?", mapper(), limit);
    }

    private RowMapper<TaskRow> mapper() {
        return (rs, rowNum) -> new TaskRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.str(rs, "task_type"),
                JdbcSupport.str(rs, "payload"),
                JdbcSupport.str(rs, "status"),
                JdbcSupport.intVal(rs, "retry"),
                JdbcSupport.intVal(rs, "max_retry"),
                JdbcSupport.str(rs, "error"),
                JdbcSupport.time(rs, "created_at"),
                JdbcSupport.time(rs, "updated_at"));
    }
}
