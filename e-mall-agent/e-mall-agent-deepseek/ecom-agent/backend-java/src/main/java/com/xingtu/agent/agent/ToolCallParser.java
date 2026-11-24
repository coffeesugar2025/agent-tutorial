package com.xingtu.agent.agent;

// ═══════ 文件级能力标注 ═══════
// [CAP-03] 运行时循环  |  [CAP-04] 规划与反思  |  [CAP-06] 上下文工程
// 职责：工具调用协议解析：模型只需输出一行 JSON —— {"tool":"
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.JsonUtil;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 工具调用协议解析：模型只需输出一行 JSON —— {"tool":"...","args":{...}}。
 * 兼容 ```json 代码块包裹、前后带说明文字、以及工具名简写。
 */
@Component
public class ToolCallParser {

    public record ToolCall(String name, Map<String, Object> args, String raw) {
    }

    private static final Pattern FENCED = Pattern.compile("```(?:json)?\\s*([\\s\\S]*?)```");
    private static final Pattern NAME_ONLY = Pattern.compile("\"tool\"\\s*:\\s*\"([A-Za-z0-9_]+)\"");

    public Optional<ToolCall> parse(String text) {
        if (text == null || text.isBlank()) {
            return Optional.empty();
        }
        String candidate = extractJson(text);
        if (candidate == null) {
            return Optional.empty();
        }
        Map<String, Object> parsed = JsonUtil.parseMap(candidate);
        Object tool = parsed.get("tool");
        if (tool == null) {
            return Optional.empty();
        }
        String name = String.valueOf(tool).trim();
        if (name.isEmpty()) {
            return Optional.empty();
        }
        Map<String, Object> args = new LinkedHashMap<>();
        Object rawArgs = parsed.get("args");
        if (rawArgs instanceof Map<?, ?> map) {
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                args.put(String.valueOf(entry.getKey()), entry.getValue());
            }
        }
        return Optional.of(new ToolCall(name, args, candidate));
    }

    /** 从模型输出中截取第一个 JSON 对象。 */
    private String extractJson(String text) {
        Matcher fenced = FENCED.matcher(text);
        if (fenced.find()) {
            String block = fenced.group(1).trim();
            if (block.startsWith("{")) {
                return block;
            }
        }
        int start = text.indexOf('{');
        if (start < 0) {
            return null;
        }
        int depth = 0;
        boolean inString = false;
        boolean escaped = false;
        for (int i = start; i < text.length(); i++) {
            char c = text.charAt(i);
            if (escaped) {
                escaped = false;
                continue;
            }
            if (c == '\\') {
                escaped = true;
                continue;
            }
            if (c == '"') {
                inString = !inString;
                continue;
            }
            if (inString) {
                continue;
            }
            if (c == '{') {
                depth++;
            } else if (c == '}') {
                depth--;
                if (depth == 0) {
                    return text.substring(start, i + 1);
                }
            }
        }
        // 半截 JSON：尝试只识别工具名，参数留空
        Matcher nameOnly = NAME_ONLY.matcher(text);
        if (nameOnly.find()) {
            return "{\"tool\":\"" + nameOnly.group(1) + "\",\"args\":{}}";
        }
        return null;
    }
}
