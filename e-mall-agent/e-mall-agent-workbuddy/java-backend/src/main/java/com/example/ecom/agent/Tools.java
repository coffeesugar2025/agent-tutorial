package com.example.ecom.agent;

import com.example.ecom.domain.Order;
import com.example.ecom.domain.Product;
import com.example.ecom.domain.User;
import com.example.ecom.observability.Metrics;
import com.example.ecom.observability.TraceContext;
import com.example.ecom.repository.OrderRepository;
import com.example.ecom.repository.ProductRepository;
import com.example.ecom.security.RbacGuard;
import com.example.ecom.service.WorkflowService;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.langchain4j.agent.tool.P;
import dev.langchain4j.agent.tool.Tool;
import dev.langchain4j.agent.tool.ToolExecutionRequest;
import org.springframework.stereotype.Component;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * LangChain4j @Tool 工具集：商品搜索 / 查库存 / 下单 / 查订单 / 退款。
 * ToolSpecifications 由这些注解自动生成；invoke() 按白名单执行 LLM 返回的 ToolExecutionRequest。
 */
@Component
public class Tools {

    public record ToolResult(boolean ok, String content) {}

    private final ProductRepository products;
    private final OrderRepository orders;
    private final WorkflowService workflow;
    private final RbacGuard rbac;
    private final ObjectMapper mapper;
    private final Metrics metrics;

    public Tools(ProductRepository products, OrderRepository orders, WorkflowService workflow,
                 RbacGuard rbac, ObjectMapper mapper, Metrics metrics) {
        this.products = products;
        this.orders = orders;
        this.workflow = workflow;
        this.rbac = rbac;
        this.mapper = mapper;
        this.metrics = metrics;
    }

    @Tool("按关键词或分类搜索商品，返回商品列表（最多 10 条）")
    public List<Map<String, Object>> searchProducts(
            @P("搜索关键词，可为空") String query,
            @P("商品分类，可为空") String category) {
        metrics.increment("tool.searchProducts");
        List<Product> found;
        if (query != null && !query.isBlank()) {
            found = products.search(query.trim());
        } else if (category != null && !category.isBlank()) {
            found = products.findByCategory(category.trim());
        } else {
            found = products.findAll();
        }
        List<Map<String, Object>> out = new ArrayList<>();
        for (Product p : found.stream().limit(10).toList()) {
            out.add(productMap(p));
        }
        return out;
    }

    @Tool("查询指定商品的实时库存")
    public Map<String, Object> checkStock(@P("商品 ID，例如 P001") String productId) {
        metrics.increment("tool.checkStock");
        return products.findById(productId)
                .map(p -> Map.<String, Object>of("productId", p.getId(), "name", p.getName(),
                        "stock", p.getStock(), "available", p.getStock() > 0))
                .orElse(Map.of("productId", productId, "error", "商品不存在"));
    }

    @Tool("为当前客户下单，itemsJson 为 [{\"productId\":\"P001\",\"quantity\":1}] 格式")
    public Map<String, Object> createOrder(
            @P("客户 ID，为空时使用当前登录用户") String customerId,
            @P("商品明细 JSON 数组") String itemsJson) {
        metrics.increment("tool.createOrder");
        String cid = (customerId == null || customerId.isBlank()) ? currentUserId() : customerId;
        Order order = workflow.placeOrder(cid, workflow.parseItems(itemsJson));
        return Map.of("orderId", order.getId(), "status", order.getStatus(), "total", order.getTotal());
    }

    @Tool("查询指定客户的订单列表，客服/管理员可查询任意客户")
    public List<Map<String, Object>> listOrders(@P("客户 ID，为空时查询当前登录用户") String customerId) {
        metrics.increment("tool.listOrders");
        String cid = (customerId == null || customerId.isBlank()) ? currentUserId() : customerId;
        requireScope(cid);
        List<Map<String, Object>> out = new ArrayList<>();
        for (Order o : orders.findByCustomerId(cid)) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", o.getId());
            m.put("customer_id", o.getCustomerId());
            m.put("status", o.getStatus());
            m.put("total", o.getTotal());
            m.put("items", o.getItems().size());
            out.add(m);
        }
        return out;
    }

    @Tool("按订单号查询订单详情，自动校验当前用户的归属权限")
    public Map<String, Object> getOrder(@P("订单号，例如 O1001") String orderId) {
        metrics.increment("tool.getOrder");
        Order order = orders.findById(orderId)
                .orElseThrow(() -> new IllegalArgumentException("订单不存在: " + orderId));
        requireScope(order.getCustomerId());
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", order.getId());
        m.put("customer_id", order.getCustomerId());
        m.put("status", order.getStatus());
        m.put("total", order.getTotal());
        m.put("items", order.getItems().stream()
                .map(i -> Map.of("product_id", i.getProductId(), "quantity", i.getQuantity()))
                .toList());
        return m;
    }

    @Tool("申请退款；金额超过阈值时必须 confirm=true，否则返回待审批单")
    public Map<String, Object> requestRefund(
            @P("订单 ID") String orderId,
            @P("退款原因") String reason,
            @P("是否确认退款（大额必填 true）") boolean confirm) {
        metrics.increment("tool.requestRefund");
        Order order = orders.findById(orderId).orElseThrow(() -> new IllegalArgumentException("订单不存在"));
        requireScope(order.getCustomerId());
        return workflow.requestRefund(orderId, reason, confirm);
    }

    /** 按工具名反射执行，含 RBAC 白名单与参数类型转换。 */
    public ToolResult invoke(ToolExecutionRequest request) {
        String name = request.name();
        User user = TraceContext.user();
        String role = user == null ? "guest" : user.getRole();
        if (!rbac.toolAllowed(role, name)) {
            metrics.increment("tool.denied");
            return new ToolResult(false, "权限不足：角色 " + role + " 不允许调用工具 " + name);
        }
        try {
            Method method = findToolMethod(name);
            if (method == null) return new ToolResult(false, "未知工具: " + name);
            Map<String, Object> args = (request.arguments() == null || request.arguments().isBlank())
                    ? Map.of()
                    : mapper.readValue(request.arguments(), new TypeReference<Map<String, Object>>() {});
            java.lang.reflect.Parameter[] params = method.getParameters();
            Object[] values = new Object[params.length];
            for (int i = 0; i < params.length; i++) {
                Object raw = args.get(params[i].getName());
                values[i] = raw == null ? defaultValue(params[i].getType())
                        : mapper.convertValue(raw, params[i].getType());
            }
            Object result = method.invoke(this, values);
            return new ToolResult(true, mapper.writeValueAsString(result));
        } catch (Exception e) {
            metrics.increment("tool.failed");
            return new ToolResult(false, "工具执行失败: " + e.getMessage());
        }
    }

    private Method findToolMethod(String name) {
        for (Method m : Tools.class.getDeclaredMethods()) {
            if (m.isAnnotationPresent(Tool.class) && m.getName().equals(name)) return m;
        }
        return null;
    }

    private static Object defaultValue(Class<?> type) {
        if (type == boolean.class) return false;
        if (type == int.class) return 0;
        if (type == double.class) return 0.0;
        if (type == long.class) return 0L;
        return null;
    }

    private String currentUserId() {
        User user = TraceContext.user();
        return user == null ? "anonymous" : user.getId();
    }

    private void requireScope(String customerId) {
        rbac.requireCustomerScope(TraceContext.user(), customerId);
    }

    private static Map<String, Object> productMap(Product p) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", p.getId());
        m.put("name", p.getName());
        m.put("category", p.getCategory());
        m.put("price", p.getPrice());
        m.put("stock", p.getStock());
        m.put("tags", p.tagList());
        m.put("description", p.getDescription());
        return m;
    }
}
