package com.xingtu.agent.common;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * JSON 工具：JDBC 的 JSON 字段一律以 String 存取，这里统一做序列化/反序列化，
 * 避免为 MyBatis TypeHandler / JPA Converter 引入额外复杂度。
 */
public final class JsonUtil {

    private static final ObjectMapper MAPPER = new ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false)
            .configure(SerializationFeature.FAIL_ON_EMPTY_BEANS, false);

    private static final DateTimeFormatter ISO_OFFSET =
            DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ssXXX");

    private JsonUtil() {
    }

    public static ObjectMapper mapper() {
        return MAPPER;
    }

    public static String toJson(Object value) {
        if (value == null) {
            return "null";
        }
        try {
            return MAPPER.writeValueAsString(value);
        } catch (Exception e) {
            throw new IllegalStateException("JSON 序列化失败: " + e.getMessage(), e);
        }
    }

    /** 序列化失败时返回 fallback，用于日志/审计等非关键路径。 */
    public static String toJsonOrNull(Object value) {
        try {
            return toJson(value);
        } catch (RuntimeException e) {
            return null;
        }
    }

    public static <T> T fromJson(String json, Class<T> type) {
        if (json == null || json.isBlank() || "null".equals(json)) {
            return null;
        }
        try {
            return MAPPER.readValue(json, type);
        } catch (Exception e) {
            throw new IllegalArgumentException("JSON 反序列化失败: " + e.getMessage(), e);
        }
    }

    public static <T> T fromJsonOrNull(String json, Class<T> type) {
        try {
            return fromJson(json, type);
        } catch (RuntimeException e) {
            return null;
        }
    }

    public static Map<String, Object> toMap(Object value) {
        if (value == null) {
            return new LinkedHashMap<>();
        }
        if (value instanceof Map<?, ?> map) {
            Map<String, Object> result = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                result.put(String.valueOf(entry.getKey()), entry.getValue());
            }
            return result;
        }
        try {
            Map<String, Object> parsed = MAPPER.readValue(MAPPER.writeValueAsString(value),
                    new TypeReference<Map<String, Object>>() {
                    });
            return parsed == null ? new LinkedHashMap<>() : parsed;
        } catch (Exception e) {
            return new LinkedHashMap<>();
        }
    }

    public static Map<String, Object> parseMap(String json) {
        if (json == null || json.isBlank() || "null".equals(json)) {
            return new LinkedHashMap<>();
        }
        try {
            Map<String, Object> parsed = MAPPER.readValue(json, new TypeReference<Map<String, Object>>() {
            });
            return parsed == null ? new LinkedHashMap<>() : parsed;
        } catch (Exception e) {
            return new LinkedHashMap<>();
        }
    }

    public static List<Object> parseList(String json) {
        if (json == null || json.isBlank() || "null".equals(json)) {
            return List.of();
        }
        try {
            List<Object> parsed = MAPPER.readValue(json, new TypeReference<List<Object>>() {
            });
            return parsed == null ? List.of() : parsed;
        } catch (Exception e) {
            return List.of();
        }
    }

    public static <T> List<T> parseList(String json, Class<T> type) {
        if (json == null || json.isBlank() || "null".equals(json)) {
            return List.of();
        }
        try {
            return MAPPER.readValue(json, MAPPER.getTypeFactory().constructCollectionType(List.class, type));
        } catch (Exception e) {
            return List.of();
        }
    }

    /** 契约要求带时区偏移的 ISO8601，例如 2026-11-23T10:00:00+08:00。 */
    public static String formatTime(LocalDateTime time) {
        if (time == null) {
            return null;
        }
        return time.atZone(ZoneId.systemDefault()).format(ISO_OFFSET);
    }

    public static String formatDate(LocalDateTime time) {
        if (time == null) {
            return null;
        }
        return time.toLocalDate().toString();
    }
}
