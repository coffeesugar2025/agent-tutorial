package com.xingtu.agent.common;

// ═══════ 文件级能力标注 ═══════
// [CAP-01] 交互协议  |  [CAP-14] 可靠性/降级  （支撑）
// 职责：请求级上下文：traceId + 当前登录用户
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import java.util.List;

/**
 * 请求级上下文：traceId + 当前登录用户。所有 ThreadLocal 必须在请求结束时 clear()。
 */
public final class TraceContext {

    public record Identity(long userId, String username, List<String> roles) {
    }

    private static final ThreadLocal<String> TRACE_ID = new ThreadLocal<>();
    private static final ThreadLocal<Identity> IDENTITY = new ThreadLocal<>();

    private TraceContext() {
    }

    public static void setTraceId(String traceId) {
        TRACE_ID.set(traceId);
    }

    /** 当前 traceId；未设置时返回空串，避免 NPE。 */
    public static String traceId() {
        String value = TRACE_ID.get();
        return value == null ? "" : value;
    }

    public static void setIdentity(long userId, String username, List<String> roles) {
        IDENTITY.set(new Identity(userId, username, roles));
    }

    public static Identity identity() {
        return IDENTITY.get();
    }

    public static long userId() {
        Identity id = IDENTITY.get();
        return id == null ? 0L : id.userId();
    }

    public static String username() {
        Identity id = IDENTITY.get();
        return id == null ? "" : id.username();
    }

    public static List<String> roles() {
        Identity id = IDENTITY.get();
        return id == null ? List.of() : id.roles();
    }

    public static boolean hasRole(String role) {
        Identity id = IDENTITY.get();
        return id != null && id.roles() != null && id.roles().contains(role);
    }

    public static boolean authenticated() {
        return IDENTITY.get() != null;
    }

    public static void clear() {
        TRACE_ID.remove();
        IDENTITY.remove();
    }
}
