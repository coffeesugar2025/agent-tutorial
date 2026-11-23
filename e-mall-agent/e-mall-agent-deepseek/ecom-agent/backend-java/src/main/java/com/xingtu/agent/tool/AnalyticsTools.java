package com.xingtu.agent.tool;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 经营分析工具（OPS）：text2sql（READ）+ run_python（READ，受限沙箱）。
 *
 * <p>SQL 由确定性模板生成（离线可用），执行前一定经过 Text2SqlGuard 校验。</p>
 */
@Component
public class AnalyticsTools {

    private static final List<String> AGENTS = List.of("OPS");
    private static final int MAX_ROWS = 50;

    private final JdbcTemplate jdbc;
    private final Text2SqlGuard guard;
    private final SandboxRunner sandbox;

    public AnalyticsTools(ToolRegistry registry, JdbcTemplate jdbc, Text2SqlGuard guard,
                          SandboxRunner sandbox) {
        this.jdbc = jdbc;
        this.guard = guard;
        this.sandbox = sandbox;
        registry.register(new ToolRegistry.Definition("text2sql",
                "把经营问题转成只读 SQL 并执行，参数 {question}；返回 sql 与数据行。",
                ToolRisk.READ, AGENTS, this::text2sql));
        registry.register(new ToolRegistry.Definition("run_python",
                "对一批数值做聚合计算（受限沙箱，不执行任意代码），参数 {script}，如 avg(1,2,3)。",
                ToolRisk.READ, AGENTS, this::runPython));
    }

    private ToolResult text2sql(Map<String, Object> args, ToolContext context) {
        String question = ToolContext.str(args, "question", context.question());
        String sql = guard.validate(toSql(question));
        List<Map<String, Object>> rows;
        try {
            rows = jdbc.queryForList(sql);
        } catch (RuntimeException e) {
            return ToolResult.fail("SQL 执行失败: " + e.getMessage());
        }
        List<Map<String, Object>> limited = rows.size() > MAX_ROWS ? rows.subList(0, MAX_ROWS) : rows;
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("sql", sql);
        data.put("rowCount", rows.size());
        data.put("rows", limited);
        String preview = limited.isEmpty() ? "无数据" : limited.get(0).toString();
        return ToolResult.ok("查询返回 " + rows.size() + " 行，首行: " + preview, data);
    }

    private ToolResult runPython(Map<String, Object> args, ToolContext context) {
        String script = ToolContext.str(args, "script", ToolContext.str(args, "expression", ""));
        SandboxRunner.Result result = sandbox.evaluate(script);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("op", result.op());
        data.put("values", result.values());
        data.put("value", result.value());
        return result.ok() ? ToolResult.ok(result.message(), data) : ToolResult.fail(result.message());
    }

    /** 问题 -> SQL 模板（确定性映射，覆盖面优先于灵活性）。 */
    public String toSql(String question) {
        String q = question == null ? "" : question.toLowerCase(Locale.ROOT);
        if (containsAny(q, "热销", "top", "销量", "商品排行", "卖得")) {
            return "SELECT sku, title, SUM(quantity) AS qty, SUM(price * quantity) AS amount "
                    + "FROM order_item GROUP BY sku, title ORDER BY qty DESC";
        }
        if (containsAny(q, "退款", "售后")) {
            return "SELECT status, COUNT(*) AS cnt, SUM(amount) AS amount FROM refund_request "
                    + "GROUP BY status ORDER BY cnt DESC";
        }
        if (containsAny(q, "会话", "对话", "转化率", "咨询量")) {
            return "SELECT DATE(created_at) AS day, COUNT(*) AS sessions FROM chat_session "
                    + "WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY) "
                    + "GROUP BY DATE(created_at) ORDER BY day";
        }
        if (containsAny(q, "成本", "token", "模型调用")) {
            return "SELECT model, COUNT(*) AS calls, SUM(cost_cents) AS cost_cents FROM llm_call "
                    + "WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY) GROUP BY model ORDER BY calls DESC";
        }
        if (containsAny(q, "销售", "销售额", "gmv", "营收", "营业额", "成交", "订单量")) {
            return "SELECT DATE(paid_at) AS day, SUM(pay_amount) AS gmv, COUNT(*) AS orders "
                    + "FROM order_info WHERE status IN ('PAID','SHIPPED','DELIVERED','FINISHED') "
                    + "AND paid_at >= DATE_SUB(NOW(), INTERVAL 30 DAY) GROUP BY DATE(paid_at) ORDER BY day";
        }
        return "SELECT status, COUNT(*) AS cnt, SUM(pay_amount) AS amount FROM order_info "
                + "GROUP BY status ORDER BY cnt DESC";
    }

    private boolean containsAny(String text, String... keywords) {
        for (String keyword : keywords) {
            if (text.contains(keyword)) {
                return true;
            }
        }
        return false;
    }
}
