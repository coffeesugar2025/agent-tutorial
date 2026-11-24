package com.xiaozhan.agent.ai;

import dev.langchain4j.agent.tool.P;
import dev.langchain4j.agent.tool.Tool;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 工具设计学（总纲 2.3）：@Tool 描述写清「何时用/何时不用」，@P 写清参数语义；
 * 返回值是结构化 Map + 稳定错误码，绝不返回 50K token 的原始数据。
 */
@Component("orderTools")
public class OrderTools {

    @Tool("按订单号查询订单状态与物流节点。仅当用户提供了明确订单号时使用；"
            + "没有订单号不要猜，绝不返回其他用户的订单；不要用它查商品或售后政策。")
    public Map<String, Object> getOrder(@P("订单号，例如 EC20261118001") String orderId,
                                        @P("归属用户，由网关注入，不由模型填写") String userId) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (orderId == null || !orderId.startsWith("EC")) {
            out.put("ok", false); out.put("error_code", "E_INVALID_ARG");
            out.put("message", "订单号格式不对；请核对后重试（分类=validation，不重试）");
            return out;
        }
        if (!"u_1001".equals(userId)) {
            out.put("ok", false); out.put("error_code", "E_FORBIDDEN");
            out.put("message", "无权访问该订单；不要改 user_id，转人工");
            return out;
        }
        out.put("ok", true);
        out.put("order", Map.of("order_id", orderId, "status", "运输中",
                "total", 799.00, "logistics_node", "已到达苏州转运中心"));
        return out;
    }

    @Tool("按 SKU、数量、券码计算到手价。仅在 SKU 已确认时使用；不要用于订单历史金额。")
    public Map<String, Object> calculatePrice(@P("商品 SKU") String sku,
                                              @P("数量，必须 > 0") int quantity,
                                              @P("券码，可为空") String couponCode) {
        Map<String, Object> out = new LinkedHashMap<>();
        if (quantity <= 0) {
            out.put("ok", false); out.put("error_code", "E_INVALID_ARG"); return out;
        }
        double subtotal = 899.00 * quantity;
        double discount = "FULL100".equals(couponCode) && subtotal >= 500 ? 100.0 : 0.0;
        out.put("ok", true); out.put("subtotal", subtotal);
        out.put("discount", discount); out.put("payable", subtotal - discount);
        return out;
    }

    @Tool("按关键词检索商品，最多返回 10 条。不要传空关键词全表拖库。")
    public Map<String, Object> searchProducts(@P("关键词") String keyword,
                                              @P("返回条数 <=10") int limit) {
        Map<String, Object> out = new LinkedHashMap<>();
        int n = Math.min(Math.max(limit, 1), 10);
        out.put("ok", true); out.put("total", 1);
        out.put("products", List.of(Map.of("sku", "SKU-1001", "name", "星野 Pro 降噪耳机",
                "price", 899.00, "stock", 12)));
        out.put("keyword", keyword); out.put("limit", n);
        return out;
    }
}
