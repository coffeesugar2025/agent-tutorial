package com.example.ecom.observability;

import com.example.ecom.domain.User;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;

import java.util.UUID;

/** Trace id 传播 + 当前用户：同时写入 MDC，日志模板用 %X{traceId} 输出。 */
@Component
public class TraceContext {

    private static final ThreadLocal<String> TRACE_ID = new ThreadLocal<>();
    private static final ThreadLocal<User> CURRENT_USER = new ThreadLocal<>();

    public static String newTrace() {
        String id = UUID.randomUUID().toString().replace("-", "").substring(0, 16);
        TRACE_ID.set(id);
        MDC.put("traceId", id);
        return id;
    }

    public static String traceId() {
        String id = TRACE_ID.get();
        if (id == null) {
            id = newTrace();
        }
        return id;
    }

    public static void setUser(User user) { CURRENT_USER.set(user); }

    public static User user() { return CURRENT_USER.get(); }

    public static void clear() {
        TRACE_ID.remove();
        CURRENT_USER.remove();
        MDC.remove("traceId");
    }
}
