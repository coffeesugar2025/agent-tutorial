package com.xingtu.agent.infra.repo;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-12] 检索增强 RAG  （支撑）
// 职责：物流表访问（logistics）
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;

/**
 * 物流表访问（logistics）。
 */
@Repository
public class LogisticsRepository {

    public record LogisticsRow(long id, long orderId, String orderNo, String company, String trackingNo,
                               String status, String latestEvent, String eventsJson, LocalDateTime updatedAt) {
    }

    private final JdbcTemplate jdbc;

    public LogisticsRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public LogisticsRow findByOrderNo(String orderNo) {
        return JdbcSupport.one(jdbc,
                "SELECT id, order_id, order_no, company, tracking_no, status, latest_event, events, updated_at "
                        + "FROM logistics WHERE order_no = ? ORDER BY id DESC LIMIT 1",
                mapper(), orderNo);
    }

    public LogisticsRow findByOrderId(long orderId) {
        return JdbcSupport.one(jdbc,
                "SELECT id, order_id, order_no, company, tracking_no, status, latest_event, events, updated_at "
                        + "FROM logistics WHERE order_id = ?",
                mapper(), orderId);
    }

    public void save(long orderId, String orderNo, String company, String trackingNo, String status,
                     String latestEvent, String eventsJson) {
        int updated = JdbcSupport.update(jdbc,
                "UPDATE logistics SET company = ?, tracking_no = ?, status = ?, latest_event = ?, events = ? "
                        + "WHERE order_id = ?",
                company, trackingNo, status, latestEvent, eventsJson, orderId);
        if (updated == 0) {
            JdbcSupport.update(jdbc,
                    "INSERT INTO logistics (order_id, order_no, company, tracking_no, status, latest_event, events) "
                            + "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    orderId, orderNo, company, trackingNo, status, latestEvent, eventsJson);
        }
    }

    private RowMapper<LogisticsRow> mapper() {
        return (rs, rowNum) -> new LogisticsRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.lng(rs, "order_id"),
                JdbcSupport.str(rs, "order_no"),
                JdbcSupport.str(rs, "company"),
                JdbcSupport.str(rs, "tracking_no"),
                JdbcSupport.str(rs, "status"),
                JdbcSupport.str(rs, "latest_event"),
                JdbcSupport.str(rs, "events"),
                JdbcSupport.time(rs, "updated_at"));
    }
}
