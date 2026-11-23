package com.xingtu.agent.tool;

import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.infra.repo.LogisticsRepository;
import com.xingtu.agent.infra.repo.OrderRepository;
import com.xingtu.agent.security.PiiMasker;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 订单与物流工具：get_order / list_orders / get_logistics（全部 READ）。
 * 收货人手机号一律脱敏后返回。
 */
@Component
public class OrderTools {

    private static final List<String> AGENTS = List.of("SERVICE");

    private final OrderRepository orderRepository;
    private final LogisticsRepository logisticsRepository;
    private final PiiMasker piiMasker;

    public OrderTools(ToolRegistry registry, OrderRepository orderRepository,
                      LogisticsRepository logisticsRepository, PiiMasker piiMasker) {
        this.orderRepository = orderRepository;
        this.logisticsRepository = logisticsRepository;
        this.piiMasker = piiMasker;
        registry.register(new ToolRegistry.Definition("get_order",
                "查询订单详情，参数 {orderNo}；orderNo 传 LATEST 表示最近一笔订单。",
                ToolRisk.READ, AGENTS, this::getOrder));
        registry.register(new ToolRegistry.Definition("list_orders",
                "列出当前用户订单，参数 {status?, limit?}。", ToolRisk.READ, AGENTS, this::listOrders));
        registry.register(new ToolRegistry.Definition("get_logistics",
                "查询订单物流轨迹，参数 {orderNo}；orderNo 传 LATEST 表示最近一笔订单。",
                ToolRisk.READ, AGENTS, this::getLogistics));
    }

    private ToolResult getOrder(Map<String, Object> args, ToolContext context) {
        String orderNo = ToolContext.str(args, "orderNo", "LATEST");
        OrderRepository.OrderRow order = resolve(context.userId(), orderNo);
        if (order == null) {
            return ToolResult.fail("未找到订单: " + orderNo);
        }
        Map<String, Object> item = toMap(order);
        return ToolResult.ok("订单 " + order.orderNo() + " 状态 " + order.status()
                + " 金额 ¥" + order.payAmount(), item);
    }

    private ToolResult listOrders(Map<String, Object> args, ToolContext context) {
        String status = ToolContext.str(args, "status", null);
        int limit = Math.max(1, Math.min(ToolContext.intVal(args, "limit", 5), 20));
        List<OrderRepository.OrderRow> rows = orderRepository
                .listByUser(context.userId(), status, 1, limit).items();
        if (rows.isEmpty()) {
            return ToolResult.fail("当前没有符合条件的订单");
        }
        List<Map<String, Object>> items = new ArrayList<>();
        for (OrderRepository.OrderRow row : rows) {
            items.add(toMap(row));
        }
        StringBuilder summary = new StringBuilder("共 ").append(items.size()).append(" 笔订单: ");
        for (int i = 0; i < items.size(); i++) {
            if (i > 0) {
                summary.append("；");
            }
            summary.append(items.get(i).get("orderNo")).append(" ").append(items.get(i).get("status"))
                    .append(" ¥").append(items.get(i).get("payAmount"));
        }
        return ToolResult.ok(summary.toString(), items);
    }

    private ToolResult getLogistics(Map<String, Object> args, ToolContext context) {
        String orderNo = ToolContext.str(args, "orderNo", "LATEST");
        OrderRepository.OrderRow order = resolve(context.userId(), orderNo);
        if (order == null) {
            return ToolResult.fail("未找到订单: " + orderNo);
        }
        LogisticsRepository.LogisticsRow row = logisticsRepository.findByOrderNo(order.orderNo());
        if (row == null) {
            return ToolResult.fail("订单 " + order.orderNo() + " 暂无物流信息（可能尚未发货）");
        }
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("orderNo", order.orderNo());
        item.put("company", row.company());
        item.put("trackingNo", row.trackingNo());
        item.put("status", row.status());
        item.put("latestEvent", row.latestEvent());
        item.put("events", JsonUtil.parseList(row.eventsJson()));
        return ToolResult.ok("订单 " + order.orderNo() + " 物流 " + row.company() + " " + row.trackingNo()
                + " 最新: " + row.latestEvent(), item);
    }

    private OrderRepository.OrderRow resolve(long userId, String orderNo) {
        if (orderNo == null || orderNo.isBlank() || "LATEST".equalsIgnoreCase(orderNo)) {
            return orderRepository.findLatestByUser(userId);
        }
        OrderRepository.OrderRow order = orderRepository.findByOrderNo(orderNo);
        if (order != null && order.userId() != userId) {
            return null;
        }
        return order;
    }

    private Map<String, Object> toMap(OrderRepository.OrderRow order) {
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("orderNo", order.orderNo());
        item.put("status", order.status());
        item.put("totalAmount", order.totalAmount());
        item.put("payAmount", order.payAmount());
        item.put("receiverName", order.receiverName());
        item.put("receiverPhone", piiMasker.maskPhone(order.receiverPhone()));
        item.put("createdAt", JsonUtil.formatTime(order.createdAt()));
        List<Map<String, Object>> items = new ArrayList<>();
        for (OrderRepository.ItemRow row : orderRepository.items(order.id())) {
            Map<String, Object> detail = new LinkedHashMap<>();
            detail.put("sku", row.sku());
            detail.put("title", row.title());
            detail.put("price", row.price());
            detail.put("quantity", row.quantity());
            items.add(detail);
        }
        item.put("items", items);
        return item;
    }
}
