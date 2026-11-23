package com.xingtu.agent.security;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * 间接提示注入检测：检索内容、工具返回值一律视为不可信数据。
 *
 * <p>两道防线：1) 统一包 &lt;untrusted_data&gt; 标签并在系统提示中声明「标签内不是指令」；
 * 2) 命中典型越狱/注入模式时降权并从上下文剔除。</p>
 */
@Component
public class InjectionDetector {

    public record Detection(boolean suspicious, List<String> hits, String reason) {
    }

    private static final List<Pattern> PATTERNS = List.of(
            Pattern.compile("ignore\\s+(all\\s+)?(previous|above|prior)\\s+instructions?", Pattern.CASE_INSENSITIVE),
            Pattern.compile("disregard\\s+(all\\s+)?(previous|above)\\s+", Pattern.CASE_INSENSITIVE),
            Pattern.compile("忽略(之前|上面|以上|前面)(的)?(所有)?(指令|规则|提示)"),
            Pattern.compile("(reveal|show|print|repeat)\\s+(me\\s+)?(your\\s+)?(system\\s+prompt|instructions)",
                    Pattern.CASE_INSENSITIVE),
            Pattern.compile("输出(你的)?(系统)?提示词|泄露(系统)?提示"),
            Pattern.compile("you\\s+are\\s+now\\s+(a|an|the)\\s+", Pattern.CASE_INSENSITIVE),
            Pattern.compile("from\\s+now\\s+on\\s+you\\s+(are|will)", Pattern.CASE_INSENSITIVE),
            Pattern.compile("<\\|?\\s*(system|im_start|im_end)\\s*\\|?>", Pattern.CASE_INSENSITIVE),
            Pattern.compile("BEGIN\\s+SYSTEM\\s+PROMPT", Pattern.CASE_INSENSITIVE),
            Pattern.compile("(调用|执行|运行)(以下)?(工具|命令|sql|代码)"),
            Pattern.compile("(new|updated)\\s+instructions?\\s*:", Pattern.CASE_INSENSITIVE));

    private static final String OPEN = "<untrusted_data>";
    private static final String CLOSE = "</untrusted_data>";

    public Detection inspect(String text) {
        if (text == null || text.isBlank()) {
            return new Detection(false, List.of(), null);
        }
        List<String> hits = new ArrayList<>();
        for (Pattern pattern : PATTERNS) {
            if (pattern.matcher(text).find()) {
                hits.add(pattern.pattern());
            }
        }
        return new Detection(!hits.isEmpty(), hits, hits.isEmpty() ? null : "疑似提示注入");
    }

    public boolean suspicious(String text) {
        return inspect(text).suspicious();
    }

    /** 统一包裹不可信内容；已包裹的不重复包裹。 */
    public String wrapUntrusted(String content) {
        if (content == null) {
            return OPEN + "\n" + CLOSE;
        }
        String trimmed = content.trim();
        if (trimmed.startsWith(OPEN)) {
            return trimmed;
        }
        return OPEN + "\n" + trimmed + "\n" + CLOSE;
    }

    /**
     * 清洗：命中注入模式时把可疑片段替换为中性占位符，并去掉零宽字符与控制字符。
     */
    public String sanitize(String content) {
        if (content == null || content.isEmpty()) {
            return "";
        }
        String cleaned = content.replace("\u200B", "").replace("\u200C", "").replace("\u200D", "");
        cleaned = cleaned.replace("\u0000", "");
        for (Pattern pattern : PATTERNS) {
            cleaned = pattern.matcher(cleaned).replaceAll("[filtered]");
        }
        return cleaned;
    }

    /** 供工具层使用：先清洗再包裹。 */
    public String sanitizeAndWrap(String content) {
        return wrapUntrusted(sanitize(content));
    }
}
