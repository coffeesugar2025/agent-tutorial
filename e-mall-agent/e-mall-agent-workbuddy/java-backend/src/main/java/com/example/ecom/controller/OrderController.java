package com.example.ecom.controller;

import com.example.ecom.domain.Order;
import com.example.ecom.domain.User;
import com.example.ecom.observability.TraceContext;
import com.example.ecom.reliability.IdempotencyGuard;
import com.example.ecom.repository.OrderRepository;
import com.example.ecom.security.ApiException;
import com.example.ecom.security.RbacGuard;
import com.example.ecom.service.WorkflowService;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/orders")
public class OrderController {

    private final OrderRepository orders;
    private final WorkflowService workflow;
    private final RbacGuard rbac;
    private final IdempotencyGuard idempotency;

    public OrderController(OrderRepository orders, WorkflowService workflow, RbacGuard rbac,
                           IdempotencyGuard idempotency) {
        this.orders = orders;
        this.workflow = workflow;
        this.rbac = rbac;
        this.idempotency = idempotency;
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record OrderCreateRequest(List<WorkflowService.ItemReq> items) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record RefundRequest(String reason, boolean confirm) {}

    @GetMapping
    public List<Order> orders(@RequestParam(required = false) String customerId) {
        User user = TraceContext.user();
        rbac.require(user, "order:read");
        String target = customerId == null || customerId.isBlank() ? user.getId() : customerId;
        rbac.requireCustomerScope(user, target);
        return orders.findByCustomerId(target);
    }

    @PostMapping
    public Order create(@RequestBody OrderCreateRequest request,
                        @RequestHeader(value = "Idempotency-Key", required = false) String key) {
        User user = TraceContext.user();
        rbac.require(user, "order:create");
        idempotency.requireNew(key, String.valueOf(request.items()));
        return workflow.placeOrder(user.getId(), request.items());
    }

    @GetMapping("/{id}")
    public Order order(@PathVariable String id) {
        User user = TraceContext.user();
        rbac.require(user, "order:read");
        Order order = orders.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "订单不存在"));
        rbac.requireCustomerScope(user, order.getCustomerId());
        return order;
    }

    @PostMapping("/{id}/refund")
    public Map<String, Object> refund(@PathVariable String id, @RequestBody(required = false) RefundRequest request) {
        User user = TraceContext.user();
        rbac.require(user, "order:refund");
        Order order = orders.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "订单不存在"));
        rbac.requireCustomerScope(user, order.getCustomerId());
        boolean confirm = request != null && request.confirm();
        String reason = request == null || request.reason() == null ? "用户申请" : request.reason();
        return workflow.requestRefund(id, reason, confirm);
    }
}
