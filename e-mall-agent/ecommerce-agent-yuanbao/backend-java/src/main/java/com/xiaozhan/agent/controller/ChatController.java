package com.xiaozhan.agent.controller;

import com.xiaozhan.agent.ai.ShoppingAssistant;
import com.xiaozhan.agent.ai.OrderTools;
import com.xiaozhan.agent.service.ObservabilityService;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.*;

/**
 * 主链路端点，与 Python /v1/* 对齐，保证前端切到 java 后聊天、意图、审计同样可用。
 * mock 模式走规则答案（零 Key 可跑）；real 模式委托 @AiService 自动工具循环。
 */
@RestController
public class ChatController {
    /** 可选注入：mock 模式不依赖 @AiService bean，starter 未装配也能起 /health。 */
    private final ObjectProvider<ShoppingAssistant> assistantProvider;
    private final OrderTools tools;
    private final ObservabilityService obs;

    @Value("${agent.llm-mode:mock}") String mode;

    public ChatController(ObjectProvider<ShoppingAssistant> assistantProvider,
                          OrderTools tools, ObservabilityService obs) {
        this.assistantProvider = assistantProvider; this.tools = tools; this.obs = obs;
    }

    @PostMapping("/v1/chat/sync")
    public Map<String, Object> chatSync(@RequestBody Map<String, Object> body) {
        String msg = String.valueOf(body.getOrDefault("message", ""));
        String thread = String.valueOf(body.getOrDefault("threadId",
                body.getOrDefault("thread_id", "default")));
        String userId = String.valueOf(body.getOrDefault("userId",
                body.getOrDefault("user_id", "u_1001")));
        Map<String, Object> trace = obs.trace("chat.sync");
        String answer;
        List<String> used = new ArrayList<>();
        List<Map<String, Object>> cards = new ArrayList<>();
        if ("real".equalsIgnoreCase(mode)) {
            ShoppingAssistant a = assistantProvider.getIfAvailable();
            answer = a != null ? a.chat(thread, msg)
                    : "AI Service 未装配：请检查 langchain4j starter，或切回 LLM_MODE=mock";
        } else {
            if (msg.contains("券") || msg.contains("到手") || msg.contains("多少钱")) {
                Map<String, Object> price = tools.calculatePrice("SKU-1001", 1, "FULL100");
                used.add("calculatePrice"); cards.add(Map.of("type", "price", "data", price));
                answer = "星野 Pro 用 FULL100 券后到手 ¥" + price.get("payable") + " CNY（899 − 100）。";
            } else if (msg.contains("订单") || msg.contains("物流")) {
                Map<String, Object> order = tools.getOrder("EC20261118001", userId);
                used.add("getOrder"); cards.add(Map.of("type", "order", "data", order));
                answer = "订单 EC20261118001 当前状态：运输中。";
            } else if (msg.contains("忽略以上规则") || msg.contains("system prompt")) {
                answer = "请求已拦截：不得绕过系统规则或访问他人数据。";
            } else {
                Map<String, Object> prod = tools.searchProducts("耳机", 3);
                used.add("searchProducts"); cards.add(Map.of("type", "products", "data", prod));
                answer = "为你找到 星野 Pro 降噪耳机（SKU-1001），¥899.00，库存 12 件。";
            }
        }
        return Map.of("answer", answer, "trace_id", trace.get("trace_id"),
                "tools_used", used, "cards", cards, "backend", "java");
    }

    /** SSE：与 Python 同构事件序列 meta → token* → done。 */
    @PostMapping(value = "/v1/chat", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter chatStream(@RequestBody Map<String, Object> body) {
        SseEmitter emitter = new SseEmitter(60_000L);
        Map<String, Object> sync = chatSync(body);
        new Thread(() -> {
            try {
                emitter.send(SseEmitter.event().name("meta").data(Map.of("trace_id", sync.get("trace_id"))));
                String text = String.valueOf(sync.get("answer"));
                for (int i = 0; i < text.length(); i += 6) {
                    emitter.send(SseEmitter.event().name("token")
                            .data(Map.of("text", text.substring(i, Math.min(text.length(), i + 6)))));
                }
                emitter.send(SseEmitter.event().name("done").data(Map.of("tools_used", sync.get("tools_used"))));
                emitter.complete();
            } catch (IOException | IllegalStateException e) {
                emitter.completeWithError(e);
            }
        }).start();
        return emitter;
    }

    @PostMapping("/v1/intent")
    public Map<String, Object> intent(@RequestBody Map<String, Object> body) {
        String m = String.valueOf(body.getOrDefault("message", ""));
        String intent = m.contains("订单") ? "order_query"
                : (m.contains("退") ? "after_sale"
                : (m.contains("券") || m.contains("价") ? "price_calc" : "search_product"));
        return Map.of("intent", intent, "confidence", 0.92, "backend", "java");
    }

    @GetMapping("/v1/audit")
    public Map<String, Object> audit() {
        return Map.of("records", List.of(), "backend", "java");
    }
}
