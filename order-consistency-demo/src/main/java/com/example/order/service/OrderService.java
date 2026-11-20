package com.example.order.service;

import com.example.order.idem.IdempotencyGuard;
import com.example.order.model.CreateOrderRequest;
import com.example.order.model.OrderCreatedEvent;
import com.example.order.model.OrderPaidEvent;
import com.example.order.model.OrderResponse;
import com.example.order.outbox.OutboxRepository;
import com.example.order.state.OrderStateMachine;
import com.example.order.state.OrderStatus;
import com.example.order.stock.StockRepository;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.sql.PreparedStatement;
import java.sql.Statement;

@Service
public class OrderService {

    private final IdempotencyGuard idem;
    private final StockRepository stock;
    private final OutboxRepository outbox;
    private final OrderStateMachine sm;
    private final JdbcTemplate jdbc;

    public OrderService(IdempotencyGuard idem, StockRepository stock, OutboxRepository outbox,
                        OrderStateMachine sm, JdbcTemplate jdbc) {
        this.idem = idem;
        this.stock = stock;
        this.outbox = outbox;
        this.sm = sm;
        this.jdbc = jdbc;
    }

    /**
     * 不标 @Transactional：由 IdempotencyGuard 的 TransactionTemplate 统一包裹，
     * 保证「幂等记录 + 扣库存 + 建单 + Outbox」是一次提交。
     */
    public OrderResponse create(String idemKey, CreateOrderRequest req) {
        return idem.execute(idemKey, req, OrderResponse.class, () -> {
            if (!stock.deduct(req.skuId(), req.qty())) {
                throw new InsufficientStockException(req.skuId());
            }

            KeyHolder kh = new GeneratedKeyHolder();
            jdbc.update(con -> {
                PreparedStatement ps = con.prepareStatement(
                        "INSERT INTO t_order(sku_id, qty, status) VALUES (?, ?, ?)",
                        Statement.RETURN_GENERATED_KEYS);
                ps.setLong(1, req.skuId());
                ps.setInt(2, req.qty());
                ps.setString(3, OrderStatus.CREATED.name());
                return ps;
            }, kh);
            Number key = kh.getKey();
            if (key == null) {
                throw new IllegalStateException("no generated order id");
            }
            long orderId = key.longValue();

            outbox.append("ORDER", String.valueOf(orderId), "ORDER_CREATED",
                    new OrderCreatedEvent(orderId, req.skuId(), req.qty()));
            return new OrderResponse(orderId, OrderStatus.CREATED.name());
        });
    }

    /** 状态机校验合法性 → 行锁 + CAS 更新兜并发 → 再写一条 Outbox */
    @Transactional
    public OrderResponse pay(Long orderId) {
        String cur = jdbc.queryForObject(
                "SELECT status FROM t_order WHERE id=? FOR UPDATE", String.class, orderId);
        OrderStatus from = OrderStatus.valueOf(cur);
        sm.assertTransition(from, OrderStatus.PAID);

        if (!compareAndSet(orderId, from, OrderStatus.PAID)) {
            throw new OrderConcurrentException(orderId);
        }
        outbox.append("ORDER", String.valueOf(orderId), "ORDER_PAID", new OrderPaidEvent(orderId));
        return new OrderResponse(orderId, OrderStatus.PAID.name());
    }

    private boolean compareAndSet(Long orderId, OrderStatus expect, OrderStatus target) {
        return jdbc.update("UPDATE t_order SET status=? WHERE id=? AND status=?",
                target.name(), orderId, expect.name()) == 1;
    }

    public static class InsufficientStockException extends RuntimeException {
        public InsufficientStockException(Long skuId) {
            super("sold out: sku=" + skuId);
        }
    }

    public static class OrderConcurrentException extends RuntimeException {
        public OrderConcurrentException(Long orderId) {
            super("order concurrently modified: " + orderId);
        }
    }
}
