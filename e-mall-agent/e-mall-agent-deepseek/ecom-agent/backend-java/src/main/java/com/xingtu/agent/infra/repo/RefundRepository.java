package com.xingtu.agent.infra.repo;

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 退款申请访问（refund_request）。idempotency_key 上有唯一索引。
 */
@Repository
public class RefundRepository {

    public record RefundRow(long id, String refundNo, long orderId, long userId, String reason,
                            BigDecimal amount, String status, String idempotencyKey, Long approvalId,
                            LocalDateTime createdAt, LocalDateTime updatedAt) {
    }

    private static final String SELECT = "SELECT id, refund_no, order_id, user_id, reason, amount, status, "
            + "idempotency_key, approval_id, created_at, updated_at FROM refund_request ";

    private final JdbcTemplate jdbc;

    public RefundRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public RefundRow findByIdempotencyKey(String idempotencyKey) {
        return JdbcSupport.one(jdbc, SELECT + " WHERE idempotency_key = ?", mapper(), idempotencyKey);
    }

    public RefundRow findById(long id) {
        return JdbcSupport.one(jdbc, SELECT + " WHERE id = ?", mapper(), id);
    }

    public RefundRow findByRefundNo(String refundNo) {
        return JdbcSupport.one(jdbc, SELECT + " WHERE refund_no = ?", mapper(), refundNo);
    }

    public long insert(String refundNo, long orderId, long userId, String reason, BigDecimal amount,
                       String status, String idempotencyKey, Long approvalId) {
        return JdbcSupport.insertAndReturnKey(jdbc,
                "INSERT INTO refund_request (refund_no, order_id, user_id, reason, amount, status, "
                        + "idempotency_key, approval_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                refundNo, orderId, userId, reason, amount, status, idempotencyKey, approvalId);
    }

    public boolean updateStatus(long id, String status) {
        return JdbcSupport.update(jdbc, "UPDATE refund_request SET status = ? WHERE id = ?", status, id) > 0;
    }

    public boolean bindApproval(long id, long approvalId) {
        return JdbcSupport.update(jdbc, "UPDATE refund_request SET approval_id = ? WHERE id = ?",
                approvalId, id) > 0;
    }

    public List<RefundRow> listByUser(long userId, int limit) {
        return JdbcSupport.list(jdbc, SELECT + " WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                mapper(), userId, limit);
    }

    private RowMapper<RefundRow> mapper() {
        return (rs, rowNum) -> new RefundRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.str(rs, "refund_no"),
                JdbcSupport.lng(rs, "order_id"),
                JdbcSupport.lng(rs, "user_id"),
                JdbcSupport.str(rs, "reason"),
                JdbcSupport.dec(rs, "amount"),
                JdbcSupport.str(rs, "status"),
                JdbcSupport.str(rs, "idempotency_key"),
                rs.getObject("approval_id") == null ? null : JdbcSupport.lng(rs, "approval_id"),
                JdbcSupport.time(rs, "created_at"),
                JdbcSupport.time(rs, "updated_at"));
    }
}
