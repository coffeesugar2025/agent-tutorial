package com.xingtu.agent.obs;

import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.common.TraceContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 结构化日志：一行一个 JSON，统一带 traceId / userId，便于 ELK 检索。
 */
@Component
public class StructuredLogger {

    private static final Logger log = LoggerFactory.getLogger("ecom-agent.event");

    public void event(String event, Map<String, Object> fields) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("event", event);
        payload.put("traceId", TraceContext.traceId());
        payload.put("userId", TraceContext.userId());
        if (fields != null) {
            payload.putAll(fields);
        }
        log.info(JsonUtil.toJson(payload));
    }

    public void event(String event, String key, Object value) {
        Map<String, Object> fields = new LinkedHashMap<>();
        fields.put(key, value);
        event(event, fields);
    }

    public void warn(String event, String message) {
        Map<String, Object> fields = new LinkedHashMap<>();
        fields.put("warning", message);
        log.warn(JsonUtil.toJson(fields));
    }
}
