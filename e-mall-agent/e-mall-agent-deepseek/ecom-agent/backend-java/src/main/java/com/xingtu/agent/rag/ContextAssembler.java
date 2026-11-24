package com.xingtu.agent.rag;

// ═══════ 文件级能力标注 ═══════
// [CAP-12] 检索增强 RAG
// 职责：上下文装配：把命中切片拼成可注入 prompt 的上下文，统一包 &lt;untrusted_data&gt;， 并限制
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.security.InjectionDetector;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * 上下文装配：把命中切片拼成可注入 prompt 的上下文，统一包 &lt;untrusted_data&gt;，
 * 并限制总字符预算，避免撑爆上下文窗口。
 */
@Component
public class ContextAssembler {

    public record Assembled(String contextText, List<Citation> citations, int usedChars) {
    }

    private final InjectionDetector injectionDetector;

    public ContextAssembler(InjectionDetector injectionDetector) {
        this.injectionDetector = injectionDetector;
    }

    public Assembled assemble(List<Citation> citations, int budgetChars) {
        if (citations == null || citations.isEmpty()) {
            return new Assembled("", List.of(), 0);
        }
        int budget = budgetChars <= 0 ? 4000 : budgetChars;
        StringBuilder sb = new StringBuilder();
        List<Citation> used = new ArrayList<>();
        for (int i = 0; i < citations.size(); i++) {
            Citation citation = citations.get(i);
            String block = "[" + (i + 1) + "] " + safe(citation.title()) + "\n"
                    + truncate(safe(citation.snippet()), 500) + "\n";
            if (sb.length() + block.length() > budget) {
                break;
            }
            sb.append(block).append('\n');
            used.add(citation);
        }
        return new Assembled(injectionDetector.wrapUntrusted(sb.toString()), used, sb.length());
    }

    private String safe(String text) {
        return injectionDetector.sanitize(text == null ? "" : text);
    }

    private String truncate(String text, int max) {
        return text.length() <= max ? text : text.substring(0, max) + "…";
    }
}
