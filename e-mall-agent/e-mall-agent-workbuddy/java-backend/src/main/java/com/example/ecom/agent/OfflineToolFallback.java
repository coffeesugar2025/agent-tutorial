package com.example.ecom.agent;

import com.example.ecom.domain.ChatResponse.ToolCall;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.langchain4j.agent.tool.ToolExecutionRequest;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 离线规则工具路由：LLM 未配置密钥时，RuleBasedChatModel 不会产出 tool_call，
 * 这里按与 Python 后端一致的关键字规则直接调用 @Tool 工具，保证共用前端在
 * Java 引擎下同样完成“推荐商品 / 查订单 / 退款 / 下单 / 查库存”等真实动作。
 */
@Component
public class OfflineToolFallback {

    private static final Pattern ORDER_ID = Pattern.compile("O\\d{3,5}", Pattern.CASE_INSENSITIVE);
    private static final Pattern PRODUCT_ID = Pattern.compile("P\\d{3,5}", Pattern.CASE_INSENSITIVE);

    private final Tools tools;
    private final ObjectMapper mapper;

    public OfflineToolFallback(Tools tools, ObjectMapper mapper) {
        this.tools = tools;
        this.mapper = mapper;
    }

    /** 命中规则时返回带工具调用的 Result；未命中返回 null 交给原规则答案。 */
    public ReActRunner.Result answer(String message) {
        if (message == null || message.isBlank()) return null;
        String text = message.toLowerCase(Locale.ROOT);
        String orderId = extract(ORDER_ID, message, "O1001");
        String productId = extract(PRODUCT_ID, message, "P001");

        String tool;
        String args;
        try {
            if (contains(text, "退款", "退货", "售后", "投诉", "换货")) {
                tool = "requestRefund";
                args = mapper.writeValueAsString(java.util.Map.of(
                        "orderId", orderId, "reason", message, "confirm", true));
            } else if (contains(text, "我的订单", "订单状态", "物流", "发货", "查订单", "订单")) {
                // 显式给出订单号时必须走带归属校验的 getOrder，否则只列自己的订单会掩盖越权访问
                boolean explicit = Pattern.compile("O\\d{3,5}", Pattern.CASE_INSENSITIVE)
                        .matcher(message).find();
                tool = explicit ? "getOrder" : "listOrders";
                args = explicit
                        ? mapper.writeValueAsString(java.util.Map.of("orderId", orderId))
                        : "{\"customerId\":\"\"}";
            } else if (contains(text, "下单", "购买", "我要买", "来一", "来个")) {
                tool = "createOrder";
                int qty = quantityOf(text);
                args = mapper.writeValueAsString(java.util.Map.of(
                        "customerId", "",
                        "itemsJson", "[{\"productId\":\"" + productId + "\",\"quantity\":" + qty + "}]"));
            } else if (contains(text, "库存", "有货", "还有吗", "剩多少")) {
                tool = "checkStock";
                args = mapper.writeValueAsString(java.util.Map.of("productId", productId));
            } else if (contains(text, "商品", "推荐", "价格", "多少钱", "便宜", "搜索", "找",
                    "耳机", "键盘", "椅子", "手表", "咖啡", "水杯", "充电")) {
                tool = "searchProducts";
                args = mapper.writeValueAsString(java.util.Map.of(
                        "query", cleanQuery(text), "category", ""));
            } else {
                return null;
            }
        } catch (Exception e) {
            return null;
        }

        ToolExecutionRequest request = ToolExecutionRequest.builder()
                .id("offline-" + tool)
                .name(tool)
                .arguments(args)
                .build();
        Tools.ToolResult executed = tools.invoke(request);
        // 清洗后仍无命中时退回全量目录，保证“推荐商品”类问题总能给出真实商品
        if ("searchProducts".equals(tool) && executed.ok() && "[]".equals(executed.content().trim())) {
            ToolExecutionRequest all = ToolExecutionRequest.builder()
                    .id("offline-search-all").name(tool)
                    .arguments("{\"query\":\"\",\"category\":\"\"}").build();
            Tools.ToolResult retryResult = tools.invoke(all);
            if (retryResult.ok()) executed = retryResult;
        }
        String answer = format(tool, executed, orderId);
        List<ToolCall> calls = new ArrayList<>();
        calls.add(new ToolCall(tool, executed.content()));
        return new ReActRunner.Result(answer, calls, List.of("tool"), !executed.ok());
    }

    private String format(String tool, Tools.ToolResult result, String orderId) {
        if (!result.ok()) {
            return "查询失败：" + result.content();
        }
        try {
            JsonNode node = mapper.readTree(result.content());
            switch (tool) {
                case "searchProducts" -> {
                    if (!node.isArray() || node.isEmpty()) return "没有找到匹配的商品，试试其他关键词。";
                    List<String> lines = new ArrayList<>();
                    lines.add("为你找到 " + node.size() + " 件相关商品：");
                    for (JsonNode p : node) {
                        lines.add("- " + p.path("id").asText() + " " + p.path("name").asText()
                                + " ¥" + p.path("price").asDouble() + "，库存 " + p.path("stock").asInt());
                    }
                    return String.join("\n", lines);
                }
                case "listOrders" -> {
                    if (!node.isArray() || node.isEmpty()) return "你目前没有订单。";
                    List<String> lines = new ArrayList<>();
                    lines.add("你共有 " + node.size() + " 笔订单：");
                    for (JsonNode o : node) {
                        lines.add("- " + o.path("id").asText() + " 金额 ¥" + o.path("total").asDouble()
                                + " 状态 " + o.path("status").asText());
                    }
                    return String.join("\n", lines);
                }
                case "getOrder" -> {
                    return "订单 " + node.path("id").asText() + "：状态 "
                            + node.path("status").asText() + "，金额 ¥" + node.path("total").asDouble() + "。";
                }
                case "requestRefund" -> {
                    String status = node.path("status").asText("");
                    if (node.hasNonNull("error")) return "退款申请未通过：" + node.path("error").asText();
                    return "退款申请已提交，单号 " + node.path("orderId").asText(orderId)
                            + "，状态 " + status + "。";
                }
                case "checkStock" -> {
                    if (node.path("available").asBoolean(false)) {
                        return node.path("name").asText() + "（" + node.path("productId").asText()
                                + "）当前库存 " + node.path("stock").asInt() + " 件，可以下单。";
                    }
                    return node.path("name").asText() + " 暂时缺货，可以看看其他商品。";
                }
                case "createOrder" -> {
                    return "下单成功！订单号 " + node.path("orderId").asText()
                            + "，合计 ¥" + node.path("total").asDouble() + "。";
                }
                default -> { return result.content(); }
            }
        } catch (Exception e) {
            return result.content();
        }
    }

    /** 去掉口语填充词，避免把“推荐降噪耳机”整句当作 LIKE 关键词而召回为空。 */
    private static String cleanQuery(String text) {
        String q = text;
        for (String filler : new String[]{"请", "帮我", "我想", "一下", "请问", "给我", "我要",
                "推荐", "搜索", "找一下", "找", "商品", "价格", "多少钱", "便宜", "有什么", "看看"}) {
            q = q.replace(filler, " ");
        }
        q = q.trim();
        return q.isEmpty() ? "" : q;
    }

    private static boolean contains(String text, String... words) {
        for (String w : words) if (text.contains(w)) return true;
        return false;
    }

    private static String extract(Pattern pattern, String text, String fallback) {
        Matcher m = pattern.matcher(text == null ? "" : text);
        return m.find() ? m.group().toUpperCase(Locale.ROOT) : fallback;
    }

    private static int quantityOf(String text) {
        Matcher m = Pattern.compile("(\\d+)\\s*(件|个|台|把)").matcher(text);
        return m.find() ? Integer.parseInt(m.group(1)) : 1;
    }
}
