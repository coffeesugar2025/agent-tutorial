package com.xingtu.agent.tool;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-13] 结构化知识
// 职责：工具执行上下文 + 参数取值帮助方法（避免每个工具重复做类型转换）
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 工具执行上下文 + 参数取值帮助方法（避免每个工具重复做类型转换）。
 */
public record ToolContext(long userId, long sessionId, String traceId, List<String> roles, String question) {

    public boolean hasRole(String role) {
        return roles != null && roles.contains(role);
    }

    public static String str(Map<String, Object> args, String key, String fallback) {
        if (args == null) {
            return fallback;
        }
        Object value = args.get(key);
        if (value == null) {
            return fallback;
        }
        String text = String.valueOf(value).trim();
        return text.isEmpty() ? fallback : text;
    }

    public static int intVal(Map<String, Object> args, String key, int fallback) {
        Object value = args == null ? null : args.get(key);
        if (value instanceof Number number) {
            return number.intValue();
        }
        if (value instanceof String text) {
            try {
                return Integer.parseInt(text.trim());
            } catch (NumberFormatException e) {
                return fallback;
            }
        }
        return fallback;
    }

    public static long longVal(Map<String, Object> args, String key, long fallback) {
        Object value = args == null ? null : args.get(key);
        if (value instanceof Number number) {
            return number.longValue();
        }
        if (value instanceof String text) {
            try {
                return Long.parseLong(text.trim());
            } catch (NumberFormatException e) {
                return fallback;
            }
        }
        return fallback;
    }

    public static BigDecimal decimal(Map<String, Object> args, String key) {
        Object value = args == null ? null : args.get(key);
        if (value instanceof BigDecimal decimal) {
            return decimal;
        }
        if (value instanceof Number number) {
            return BigDecimal.valueOf(number.doubleValue());
        }
        if (value instanceof String text && !text.isBlank()) {
            try {
                return new BigDecimal(text.trim());
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }

    public static List<String> strList(Map<String, Object> args, String key) {
        List<String> result = new ArrayList<>();
        Object value = args == null ? null : args.get(key);
        if (value instanceof List<?> list) {
            for (Object item : list) {
                if (item != null) {
                    result.add(String.valueOf(item));
                }
            }
        } else if (value instanceof String text && !text.isBlank()) {
            for (String item : text.split(",")) {
                if (!item.isBlank()) {
                    result.add(item.trim());
                }
            }
        }
        return result;
    }

    public static boolean boolVal(Map<String, Object> args, String key, boolean fallback) {
        Object value = args == null ? null : args.get(key);
        if (value instanceof Boolean bool) {
            return bool;
        }
        if (value instanceof String text) {
            return "true".equalsIgnoreCase(text.trim());
        }
        return fallback;
    }
}
