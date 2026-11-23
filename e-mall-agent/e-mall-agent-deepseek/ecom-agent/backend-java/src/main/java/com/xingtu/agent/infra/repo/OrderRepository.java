package com.xingtu.agent.infra.repo;

import com.xingtu.agent.common.PageResult;
import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 订单表访问（order_info / order_item）。
 */
@Repository
public class OrderRepository {

    public record OrderRow(long id, String orderNo, long userId, String status, BigDecimal totalAmount,
                           BigDecimal payAmount, String receiverName, String receiverPhone,
                           String receiverAddress, LocalDateTime createdAt, LocalDateTime paidAt,
                           LocalDateTime shippedAt, LocalDateTime finishedAt) {
    }

    public record ItemRow(long id, long orderId, long productId, String sku, String title,
                          BigDecimal price, int quantity) {
    }

    private static final String SELECT = "SELECT id, order_no, user_id, status, total_amount, pay_amount, "
            + "receiver_name, receiver_phone, receiver_address, created_at, paid_at, shipped_at, finished_at "
            + "FROM order_info ";

    private final JdbcTemplate jdbc;

    public OrderRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public PageResult<OrderRow> listByUser(long userId, String status, int page, int size) {
        String where = " WHERE user_id = ?";
        Object[] args;
        if (status == null || status.isBlank()) {
            args = new Object[]{userId};
        } else {
            where = where + " AND status = ?";
            args = new Object[]{userId, status};
        }
        long total = JdbcSupport.count(jdbc, "SELECT COUNT(*) FROM order_info" + where, args);
        Object[] pageArgs = new Object[args.length + 2];
        System.arraycopy(args, 0, pageArgs, 0, args.length);
        pageArgs[args.length] = size;
        pageArgs[args.length + 1] = (page - 1) * size;
        List<OrderRow> rows = JdbcSupport.list(jdbc,
                SELECT + where + " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?", mapper(), pageArgs);
        return PageResult.of(rows, total, page, size);
    }

    public OrderRow findByOrderNo(String orderNo) {
        return JdbcSupport.one(jdbc, SELECT + " WHERE order_no = ?", mapper(), orderNo);
    }

    public OrderRow findById(long id) {
        return JdbcSupport.one(jdbc, SELECT + " WHERE id = ?", mapper(), id);
    }

    public OrderRow findLatestByUser(long userId) {
        return JdbcSupport.one(jdbc, SELECT + " WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                mapper(), userId);
    }

    public List<ItemRow> items(long orderId) {
        return JdbcSupport.list(jdbc,
                "SELECT id, order_id, product_id, sku, title, price, quantity FROM order_item "
                        + "WHERE order_id = ? ORDER BY id",
                (rs, rowNum) -> new ItemRow(
                        JdbcSupport.lng(rs, "id"),
                        JdbcSupport.lng(rs, "order_id"),
                        JdbcSupport.lng(rs, "product_id"),
                        JdbcSupport.str(rs, "sku"),
                        JdbcSupport.str(rs, "title"),
                        JdbcSupport.dec(rs, "price"),
                        JdbcSupport.intVal(rs, "quantity")),
                orderId);
    }

    public boolean updateStatus(long orderId, String expectedStatus, String newStatus) {
        int updated;
        if (expectedStatus == null) {
            updated = JdbcSupport.update(jdbc, "UPDATE order_info SET status = ? WHERE id = ?", newStatus, orderId);
        } else {
            updated = JdbcSupport.update(jdbc,
                    "UPDATE order_info SET status = ? WHERE id = ? AND status = ?",
                    newStatus, orderId, expectedStatus);
        }
        return updated > 0;
    }

    private RowMapper<OrderRow> mapper() {
        return (rs, rowNum) -> new OrderRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.str(rs, "order_no"),
                JdbcSupport.lng(rs, "user_id"),
                JdbcSupport.str(rs, "status"),
                JdbcSupport.dec(rs, "total_amount"),
                JdbcSupport.dec(rs, "pay_amount"),
                JdbcSupport.str(rs, "receiver_name"),
                JdbcSupport.str(rs, "receiver_phone"),
                JdbcSupport.str(rs, "receiver_address"),
                JdbcSupport.time(rs, "created_at"),
                JdbcSupport.time(rs, "paid_at"),
                JdbcSupport.time(rs, "shipped_at"),
                JdbcSupport.time(rs, "finished_at"));
    }
}
