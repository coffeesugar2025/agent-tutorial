package com.example.ecom.service;

import com.example.ecom.domain.AuditLog;
import com.example.ecom.domain.Order;
import com.example.ecom.domain.OrderItem;
import com.example.ecom.domain.Product;
import com.example.ecom.observability.Metrics;
import com.example.ecom.observability.TraceContext;
import com.example.ecom.repository.AuditLogRepository;
import com.example.ecom.repository.OrderRepository;
import com.example.ecom.repository.ProductRepository;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 订单履约状态机 + HITL 审批 + 领域事件。
 * created → paid → shipped → delivered；paid/shipped → refund_requested（大额需审批）。
 */
@Service
public class WorkflowService {

    public record ItemReq(String productId, int quantity) {}

    private static final Map<String, List<String>> TRANSITIONS = Map.of(
            "created", List.of("paid", "refund_requested"),
            "paid", List.of("shipped", "refund_requested"),
            "shipped", List.of("delivered", "refund_requested"),
            "refund_requested", List.of("refunded"),
            "delivered", List.of("refund_requested"),
            "refunded", List.of()
    );

    private final OrderRepository orders;
    private final ProductRepository products;
    private final AuditLogRepository auditLogs;
    private final ObjectMapper mapper;
    private final Metrics metrics;
    private final ObjectProvider<RabbitTemplate> rabbit;
    private final boolean publishEnabled;
    private final double refundThreshold;

    /** 待人工审批的退款（HITL），threadId → 审批上下文 */
    private final ConcurrentHashMap<String, Map<String, Object>> pending = new ConcurrentHashMap<>();
    private final List<String> inMemoryEvents = new ArrayList<>();

    public WorkflowService(OrderRepository orders, ProductRepository products,
                           AuditLogRepository auditLogs, ObjectMapper mapper, Metrics metrics,
                           ObjectProvider<RabbitTemplate> rabbit,
                           @Value("${app.event.publish-enabled:false}") boolean publishEnabled,
                           @Value("${app.agent.refund-threshold:500}") double refundThreshold) {
        this.orders = orders;
        this.products = products;
        this.auditLogs = auditLogs;
        this.mapper = mapper;
        this.metrics = metrics;
        this.rabbit = rabbit;
        this.publishEnabled = publishEnabled;
        this.refundThreshold = refundThreshold;
    }

    public static boolean canTransition(String from, String to) {
        return TRANSITIONS.getOrDefault(from, List.of()).contains(to);
    }

    public List<String> nextStates(String status) {
        return TRANSITIONS.getOrDefault(status, List.of());
    }

    @Transactional
    public Order placeOrder(String customerId, List<ItemReq> items) {
        if (items == null || items.isEmpty()) throw new IllegalArgumentException("订单明细不能为空");
        Order order = new Order("o-" + UUID.randomUUID().toString().substring(0, 10), customerId);
        double total = 0;
        for (ItemReq req : items) {
            if (req.quantity() <= 0) throw new IllegalArgumentException("数量必须为正数");
            Product product = products.findById(req.productId())
                    .orElseThrow(() -> new IllegalArgumentException("商品不存在: " + req.productId()));
            if (product.getStock() < req.quantity()) {
                throw new IllegalArgumentException("库存不足: " + product.getName());
            }
            product.setStock(product.getStock() - req.quantity());
            products.save(product);
            OrderItem item = new OrderItem(req.productId(), req.quantity(), product.getPrice());
            order.addItem(item);
            total += product.getPrice() * req.quantity();
        }
        order.setTotal(Math.round(total * 100.0) / 100.0);
        order.setStatus("created");
        Order saved = orders.save(order);
        publish("order.created", "{\"orderId\":\"" + saved.getId() + "\",\"total\":" + saved.getTotal() + "}");
        audit("api.create_order", saved.getId(), "allow", "total=" + saved.getTotal());
        metrics.increment("order.created");
        return saved;
    }

    @Transactional
    public Order transition(String orderId, String target) {
        Order order = orders.findById(orderId).orElseThrow(() -> new IllegalArgumentException("订单不存在"));
        if (!canTransition(order.getStatus(), target)) {
            throw new IllegalArgumentException("非法状态迁移: " + order.getStatus() + " → " + target);
        }
        order.setStatus(target);
        Order saved = orders.save(order);
        publish("order." + target, "{\"orderId\":\"" + orderId + "\"}");
        metrics.increment("order.transition");
        return saved;
    }

    /** 退款：大额且未确认时进入 HITL 审批流程。 */
    @Transactional
    public Map<String, Object> requestRefund(String orderId, String reason, boolean confirm) {
        Order order = orders.findById(orderId).orElseThrow(() -> new IllegalArgumentException("订单不存在"));
        boolean large = order.getTotal() >= refundThreshold;
        if (large && !confirm) {
            String threadId = "approval-" + UUID.randomUUID().toString().substring(0, 12);
            pending.put(threadId, Map.of("orderId", orderId, "reason", reason, "amount", order.getTotal()));
            publish("order.refund.pending", "{\"threadId\":\"" + threadId + "\",\"amount\":" + order.getTotal() + "}");
            audit("order.refund", orderId, "pending", "amount=" + order.getTotal());
            metrics.increment("hitl.pending");
            return Map.of("orderId", orderId, "status", "pending_approval",
                    "approvalRequired", true, "threadId", threadId, "amount", order.getTotal());
        }
        if (!canTransition(order.getStatus(), "refund_requested")) {
            throw new IllegalArgumentException("当前状态不允许退款: " + order.getStatus());
        }
        order.setStatus("refund_requested");
        orders.save(order);
        publish("order.refund_requested", "{\"orderId\":\"" + orderId + "\"}");
        audit("order.refund", orderId, "allow", reason == null ? "" : reason);
        metrics.increment("order.refund");
        return Map.of("orderId", orderId, "status", "refund_requested", "approvalRequired", false);
    }

    /** HITL 审批端点：批准则提交退款，拒绝则保持原状态。 */
    @Transactional
    public Map<String, Object> approve(String threadId, boolean approved) {
        Map<String, Object> ctx = pending.remove(threadId);
        if (ctx == null) throw new IllegalArgumentException("审批单不存在或已处理: " + threadId);
        String orderId = String.valueOf(ctx.get("orderId"));
        if (approved) {
            Order order = orders.findById(orderId).orElseThrow(() -> new IllegalArgumentException("订单不存在"));
            String target = canTransition(order.getStatus(), "refund_requested") ? "refund_requested" : order.getStatus();
            order.setStatus(target);
            orders.save(order);
            publish("order.refund.approved", "{\"threadId\":\"" + threadId + "\"}");
        }
        audit("workflow.approve", threadId, approved ? "allow" : "deny", "approved=" + approved);
        metrics.increment(approved ? "hitl.approved" : "hitl.rejected");
        return Map.of("threadId", threadId, "approved", approved,
                "status", approved ? "refund_requested" : "rejected");
    }

    public List<ItemReq> parseItems(String itemsJson) {
        if (itemsJson == null || itemsJson.isBlank()) return List.of();
        try {
            return mapper.readValue(itemsJson, new TypeReference<List<ItemReq>>() {});
        } catch (Exception e) {
            throw new IllegalArgumentException("订单明细 JSON 非法", e);
        }
    }

    private void publish(String type, String payload) {
        inMemoryEvents.add(type + " " + payload);
        if (publishEnabled) {
            try {
                rabbit.getIfAvailable().convertAndSend("ecom.events", type, payload);
                metrics.increment("rabbitmq.published");
            } catch (Exception e) {
                metrics.increment("rabbitmq.failed");
            }
        }
    }

    public List<String> drainEvents() {
        return List.copyOf(inMemoryEvents);
    }

    private void audit(String action, String target, String decision, String detail) {
        try {
            String actor = TraceContext.user() == null ? "system" : TraceContext.user().getId();
            auditLogs.save(new AuditLog(actor, action, target, decision, detail));
        } catch (Exception ignored) {
            // 审计失败不应阻断主流程
        }
    }
}
