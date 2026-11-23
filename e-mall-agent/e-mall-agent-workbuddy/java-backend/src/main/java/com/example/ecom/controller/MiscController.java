package com.example.ecom.controller;

import com.example.ecom.agent.ContextBuilder;
import com.example.ecom.domain.AuditLog;
import com.example.ecom.domain.Order;
import com.example.ecom.observability.Metrics;
import com.example.ecom.observability.TraceContext;
import com.example.ecom.rag.RagHit;
import com.example.ecom.rag.RetrievalService;
import com.example.ecom.repository.AuditLogRepository;
import com.example.ecom.repository.OrderRepository;
import com.example.ecom.security.RbacGuard;
import com.example.ecom.service.WorkflowService;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 前端兼容端点：graphs / traces / audit / context / rag / metrics / fulfillment。 */
@RestController
@RequestMapping("/api")
public class MiscController {

    private final RetrievalService retrieval;
    private final ContextBuilder contextBuilder;
    private final AuditLogRepository auditLogs;
    private final OrderRepository orders;
    private final WorkflowService workflow;
    private final Metrics metrics;
    private final RbacGuard rbac;

    public MiscController(RetrievalService retrieval, ContextBuilder contextBuilder,
                          AuditLogRepository auditLogs, OrderRepository orders,
                          WorkflowService workflow, Metrics metrics, RbacGuard rbac) {
        this.retrieval = retrieval;
        this.contextBuilder = contextBuilder;
        this.auditLogs = auditLogs;
        this.orders = orders;
        this.workflow = workflow;
        this.metrics = metrics;
        this.rbac = rbac;
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record FulfillmentRequest(String order_id, String thread_id) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record ApprovalRequest(String thread_id, boolean approved) {}

    @GetMapping("/graphs")
    public Map<String, Object> graphs() {
        rbac.require(TraceContext.user(), "chat:use");
        Map<String, Object> supervisor = new LinkedHashMap<>();
        supervisor.put("title", "Supervisor 路由");
        supervisor.put("nodes", List.of(
                Map.of("id", "input", "label", "用户输入", "kind", "start"),
                Map.of("id", "route", "label", "Supervisor", "kind", "router"),
                Map.of("id", "product", "label", "商品专家", "kind", "agent"),
                Map.of("id", "order", "label", "订单专家", "kind", "agent"),
                Map.of("id", "service", "label", "客服专家", "kind", "agent")));
        supervisor.put("edges", List.of(
                Map.of("source", "input", "target", "route"),
                Map.of("source", "route", "target", "product"),
                Map.of("source", "route", "target", "order"),
                Map.of("source", "route", "target", "service")));
        Map<String, Object> fulfillment = new LinkedHashMap<>();
        fulfillment.put("title", "订单履约状态机");
        fulfillment.put("nodes", List.of("created", "paid", "shipped", "delivered", "refund_requested")
                .stream().map(s -> Map.of("id", s, "label", s, "kind", "state")).toList());
        fulfillment.put("edges", List.of(
                Map.of("source", "created", "target", "paid"),
                Map.of("source", "paid", "target", "shipped"),
                Map.of("source", "shipped", "target", "delivered"),
                Map.of("source", "paid", "target", "refund_requested")));
        return Map.of("supervisor", supervisor, "fulfillment", fulfillment);
    }

    @GetMapping("/traces")
    public List<Map<String, Object>> traces(@RequestParam(defaultValue = "50") int limit) {
        rbac.require(TraceContext.user(), "trace:read");
        return List.of(Map.of("traceId", TraceContext.traceId(), "event", "chat",
                "metrics", metrics.snapshot()));
    }

    @GetMapping("/audit")
    public List<AuditLog> audit(@RequestParam(defaultValue = "50") int limit) {
        rbac.require(TraceContext.user(), "audit:read");
        return auditLogs.findTop50ByOrderByCreatedAtDesc();
    }

    @GetMapping("/context/preview")
    public Map<String, Object> contextPreview(@RequestParam(defaultValue = "我想买降噪耳机") String message) {
        rbac.require(TraceContext.user(), "chat:use");
        List<RagHit> hits = retrieval.retrieve(message);
        var built = contextBuilder.build("你是电商智能助手，只基于事实回答。", List.of(), message, hits, "");
        return Map.of("snapshot", built.snapshot(), "messages",
                built.messages().stream().map(m -> Map.of("role", m.type().name(),
                        "content", String.valueOf(m))).toList());
    }

    @GetMapping("/rag/search")
    public List<RagHit> ragSearch(@RequestParam(defaultValue = "退货政策") String q) {
        rbac.require(TraceContext.user(), "chat:use");
        return retrieval.retrieve(q);
    }

    @GetMapping("/capabilities/metrics")
    public Map<String, Object> metrics() {
        rbac.require(TraceContext.user(), "chat:use");
        return Map.of("counters", metrics.snapshot());
    }

    /** 履约推进：自动执行可用迁移直到 delivered。 */
    @PostMapping("/workflows/fulfillment/run")
    public Map<String, Object> fulfillmentRun(@RequestBody FulfillmentRequest request) {
        rbac.require(TraceContext.user(), "order:manage");
        Order order = orders.findById(request.order_id()).orElseThrow();
        rbac.requireCustomerScope(TraceContext.user(), order.getCustomerId());
        String status = order.getStatus();
        while (!"delivered".equals(status)) {
            List<String> next = workflow.nextStates(status).stream()
                    .filter(s -> !s.startsWith("refund")).limit(1).toList();
            if (next.isEmpty()) break;
            status = workflow.transition(order.getId(), next.get(0)).getStatus();
        }
        return Map.of("order_id", order.getId(), "status", status,
                "thread_id", request.thread_id() == null ? "" : request.thread_id());
    }

    @PostMapping("/workflows/fulfillment/resume")
    public Map<String, Object> fulfillmentResume(@RequestBody ApprovalRequest request) {
        rbac.require(TraceContext.user(), "order:manage");
        return workflow.approve(request.thread_id(), request.approved());
    }
}
