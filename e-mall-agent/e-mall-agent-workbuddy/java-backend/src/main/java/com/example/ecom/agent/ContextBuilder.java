package com.example.ecom.agent;

import com.example.ecom.rag.RagHit;
import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.SystemMessage;
import dev.langchain4j.data.message.UserMessage;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Context Engineering：系统提示模板 + RAG 引用注入 + token(字符)预算裁剪。
 * 优先级：system > user > rag > history；超预算时先丢最旧的历史，再压缩 RAG。
 */
@Component
public class ContextBuilder {

    @Value("${app.agent.context-max-chars:4000}")
    private int maxChars;

    public record Built(List<ChatMessage> messages, Map<String, Object> snapshot) {}

    public Built build(String systemPrompt, List<ChatMessage> history, String userInput,
                       List<RagHit> hits, String securityNote) {
        int budget = Math.max(500, maxChars);
        Map<String, Object> snapshot = new LinkedHashMap<>();
        List<Map<String, Object>> sections = new ArrayList<>();

        String sys = systemPrompt == null ? "" : systemPrompt;
        if (securityNote != null && !securityNote.isBlank()) {
            sys = sys + "\n\n【安全提示】" + securityNote;
        }
        String user = userInput == null ? "" : userInput;

        // RAG 按预算裁剪
        StringBuilder rag = new StringBuilder();
        int ragChars = 0;
        int ragKept = 0;
        int ragDropped = 0;
        int ragBudget = Math.max(200, budget / 2);
        if (hits != null) {
            for (RagHit hit : hits) {
                String chunk = "[" + (ragKept + 1) + "] " + hit.text() + "（来源：" + hit.source() + "）\n";
                if (ragChars + chunk.length() > ragBudget) {
                    ragDropped++;
                    continue;
                }
                rag.append(chunk);
                ragChars += chunk.length();
                ragKept++;
            }
        }
        if (rag.length() > 0) {
            sys = sys + "\n\n【知识库参考（回答时请引用编号）】\n" + rag;
        }
        addSection(sections, "system", sys.length(), true, 0, false);
        addSection(sections, "rag", ragChars, ragKept > 0, 1, ragDropped > 0);

        // 历史按优先级从新到旧装箱
        List<ChatMessage> keptHistory = new ArrayList<>();
        int used = sys.length() + user.length();
        int kept = 0;
        int dropped = 0;
        if (history != null) {
            for (int i = history.size() - 1; i >= 0; i--) {
                ChatMessage m = history.get(i);
                int chars = textOf(m).length();
                if (used + chars <= budget) {
                    keptHistory.add(0, m);
                    used += chars;
                    kept++;
                } else {
                    dropped++;
                }
            }
        }
        addSection(sections, "history", used - sys.length() - user.length(), kept > 0, 2, dropped > 0);
        addSection(sections, "user", user.length(), true, 0, false);

        List<ChatMessage> messages = new ArrayList<>();
        messages.add(SystemMessage.from(sys));
        messages.addAll(keptHistory);
        messages.add(UserMessage.from(user));

        snapshot.put("sections", sections);
        snapshot.put("max_chars", budget);
        snapshot.put("total_chars", used);
        snapshot.put("kept_messages", kept + 2);
        snapshot.put("dropped_messages", dropped + ragDropped);
        snapshot.put("compressed", dropped > 0 || ragDropped > 0);
        return new Built(messages, snapshot);
    }

    private static void addSection(List<Map<String, Object>> sections, String name,
                                   int chars, boolean included, int priority, boolean truncated) {
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("name", name);
        s.put("chars", chars);
        s.put("included", included);
        s.put("priority", priority);
        s.put("truncated", truncated);
        sections.add(s);
    }

    private static String textOf(ChatMessage message) {
        if (message instanceof UserMessage um && um.hasSingleText()) return um.singleText();
        if (message instanceof dev.langchain4j.data.message.AiMessage ai) {
            return ai.text() == null ? "" : ai.text();
        }
        return String.valueOf(message);
    }
}
