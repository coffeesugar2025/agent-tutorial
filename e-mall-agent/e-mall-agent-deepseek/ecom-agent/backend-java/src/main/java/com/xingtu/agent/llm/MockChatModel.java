package com.xingtu.agent.llm;

// ═══════ 文件级能力标注 ═══════
// [CAP-02] 模型接入与输出控制  |  [CAP-18] 成本与模型工程
// 职责：离线确定性 Mock 模型（LLM_PRIMARY=mock）
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.TokenEstimator;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.SystemMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.model.chat.ChatLanguageModel;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.response.ChatResponse;

import java.util.ArrayList;
import java.util.List;

/**
 * 离线确定性 Mock 模型（LLM_PRIMARY=mock）。
 *
 * <p>它实现 LangChain4j 的 {@link ChatLanguageModel}，但决策逻辑完全来自
 * {@link #respond(LlmProvider.Request)}：解析 prompt 中的 STEP / AGENT / QUESTION 标记，
 * 按规则产出「工具调用 JSON」或最终答案，因此在没有网络、没有 API Key 的环境下也能跑通
 * 完整的 ReAct 循环、审批中断、成本与追踪链路。</p>
 */
public class MockChatModel implements ChatLanguageModel {

    private final ThreadLocal<LlmProvider.Request> pending = new ThreadLocal<>();

    /** 绑定当前请求，供 LangChain4j 的 chat() 回调读取。 */
    public void bind(LlmProvider.Request request) {
        pending.set(request);
    }

    public void clear() {
        pending.remove();
    }

    @Override
    public ChatResponse chat(ChatRequest chatRequest) {
        LlmProvider.Request request = pending.get();
        String text = respond(request);
        return ChatResponse.builder()
                .aiMessage(AiMessage.from(text))
                .build();
    }

    /** 通过 LangChain4j 消息类型构造 ChatRequest 并取回文本（验证消息转换链路）。 */
    public String chatViaLangChain4j(LlmProvider.Request request) {
        List<dev.langchain4j.data.message.ChatMessage> messages = new ArrayList<>();
        for (LlmProvider.Message message : request.messages()) {
            if ("system".equals(message.role())) {
                messages.add(SystemMessage.from(message.content()));
            } else {
                messages.add(UserMessage.from(message.content()));
            }
        }
        bind(request);
        try {
            ChatResponse response = chat(ChatRequest.builder().messages(messages).build());
            AiMessage aiMessage = response.aiMessage();
            return aiMessage == null || aiMessage.text() == null ? "" : aiMessage.text();
        } finally {
            clear();
        }
    }

    /** 确定性决策核心：同样的 prompt 永远得到同样的输出。 */
    public String respond(LlmProvider.Request request) {
        if (request == null) {
            return "（Mock 模型未收到请求）";
        }
        String prompt = request.lastUserContent();
        int step = extractInt(prompt, "STEP:\\s*(\\d+)", 1);
        String agent = extractString(prompt, "AGENT:\\s*([A-Z_]+)", "SUPERVISOR");
        String question = extractString(prompt, "QUESTION:\\s*(.+)", "你好");
        boolean hasToolResult = prompt.contains("TOOL_RESULT");
        boolean hasToolError = prompt.contains("TOOL_RESULT ok=false");

        String intent = detectIntent(question);

        if ("refund".equals(intent)) {
            if (step <= 1) {
                return toolCall("check_refund_eligibility", "{\"orderNo\":\"LATEST\"}");
            }
            if (step == 2 && !hasToolError) {
                return toolCall("create_refund_request",
                        "{\"orderNo\":\"LATEST\",\"reason\":\"商品不符合预期\",\"amount\":0}");
            }
            return "已为你确认退款资格（订单 " + latestOrderNo(prompt) + "），并提交退款申请。"
                    + "该操作属于不可逆动作，已生成人工审批任务，审批通过后系统会自动执行退款，"
                    + "你可以在「审批」列表中查看进度。";
        }

        if ("logistics".equals(intent)) {
            if (step <= 1) {
                return toolCall("get_logistics", "{\"orderNo\":\"LATEST\"}");
            }
            return "已查询到订单 " + latestOrderNo(prompt) + " 的物流轨迹，最新状态见上方工具结果。"
                    + "如超过 48 小时没有更新，可以申请物流异常核查。";
        }

        if ("order".equals(intent)) {
            if (step <= 1) {
                return toolCall("list_orders", "{}");
            }
            return "已为你列出最近的订单，详见上方工具结果。你可以继续告诉我想查看哪一笔订单的物流或售后。";
        }

        if ("analytics".equals(intent)) {
            if (step <= 1) {
                return toolCall("text2sql", "{\"question\":" + quote(question) + "}");
            }
            return "经营分析结果已生成（见上方工具结果中的 SQL 与数据摘要）。"
                    + "如需按品类或时间维度下钻，可以继续提问。";
        }

        if ("shopping".equals(intent)) {
            if (step <= 1) {
                return toolCall("search_products",
                        "{\"query\":" + quote(question) + ",\"topK\":3,\"maxPrice\":0}");
            }
            return "结合检索结果，为你推荐以上商品：优先考虑拍照与续航兼顾的型号，"
                    + "价格都在预算区间内；如果更看重手感可以选小屏版本。需要我按价格或品牌再筛一次吗？";
        }

        if ("knowledge".equals(intent)) {
            if (step <= 1) {
                return toolCall("search_knowledge", "{\"query\":" + quote(question) + ",\"topK\":3}");
            }
            return "根据知识库检索结果，相关政策要点见上方引用。若与订单实际情况不符，可以申请人工介入。";
        }

        if ("human".equals(intent)) {
            return "这个问题需要人工客服进一步核实，我马上为你转接（已生成工单）。";
        }

        if (step <= 1 && hasToolResult) {
            return "已获取到需要的信息，下面是我的结论：" + summarize(question);
        }
        return "我是星图商城的智能导购助手，可以帮你找商品、查订单物流、处理退款与售后，"
                + "也可以查询经营数据。请告诉我具体诉求，例如「帮我找 5000 以内的拍照手机」。"
                + "（当前为 Mock 模型，问题：" + abbreviate(question) + "）";
    }

    private String detectIntent(String question) {
        String q = question == null ? "" : question;
        if (containsAny(q, "退款", "退货", "售后", "退钱")) {
            return "refund";
        }
        if (containsAny(q, "物流", "快递", "到哪", "签收", "发货")) {
            return "logistics";
        }
        if (containsAny(q, "订单", "买了", "下单")) {
            return "order";
        }
        if (containsAny(q, "报表", "销售额", "GMV", "gmv", "统计", "经营", "趋势", "转化率", "客单价")) {
            return "analytics";
        }
        if (containsAny(q, "政策", "规则", "说明书", "手册", "怎么用", "保修")) {
            return "knowledge";
        }
        if (containsAny(q, "人工", "客服", "投诉", "转人工")) {
            return "human";
        }
        if (containsAny(q, "推荐", "手机", "买", "商品", "对比", "价格", "拍照", "耳机", "笔记本", "预算")) {
            return "shopping";
        }
        return "chat";
    }

    private boolean containsAny(String text, String... keywords) {
        for (String keyword : keywords) {
            if (text.contains(keyword)) {
                return true;
            }
        }
        return false;
    }

    private String toolCall(String name, String argsJson) {
        return "{\"tool\":\"" + name + "\",\"args\":" + argsJson + "}";
    }

    private String latestOrderNo(String prompt) {
        java.util.regex.Matcher matcher = java.util.regex.Pattern.compile("(SO\\d{8,24})").matcher(prompt);
        String last = "LATEST";
        while (matcher.find()) {
            last = matcher.group(1);
        }
        return last;
    }

    private String summarize(String question) {
        return abbreviate(question) + "——已根据工具返回结果完成核对。";
    }

    private String abbreviate(String text) {
        if (text == null) {
            return "";
        }
        String single = text.replace('\n', ' ').trim();
        return single.length() <= 40 ? single : single.substring(0, 40) + "...";
    }

    private String quote(String text) {
        StringBuilder sb = new StringBuilder("\"");
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c == '"' || c == '\\') {
                sb.append('\\');
            }
            if (c == '\n') {
                sb.append("\\n");
                continue;
            }
            sb.append(c);
        }
        return sb.append('"').toString();
    }

    private int extractInt(String text, String regex, int fallback) {
        java.util.regex.Matcher matcher = java.util.regex.Pattern.compile(regex).matcher(text);
        if (matcher.find()) {
            try {
                return Integer.parseInt(matcher.group(1));
            } catch (NumberFormatException e) {
                return fallback;
            }
        }
        return fallback;
    }

    private String extractString(String text, String regex, String fallback) {
        java.util.regex.Matcher matcher = java.util.regex.Pattern.compile(regex).matcher(text);
        return matcher.find() ? matcher.group(1).trim() : fallback;
    }

    /** 供单元测试估算 token（Mock 不返回真实 usage）。 */
    public static int estimateTokens(String text) {
        return TokenEstimator.estimate(text);
    }
}
