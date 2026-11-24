package com.xingtu.agent.common;

// ═══════ 文件级能力标注 ═══════
// [CAP-01] 交互协议  |  [CAP-14] 可靠性/降级  （支撑）
// 职责：统一响应信封：{"code":0,"message":"ok","data":{},"traceId":"
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * 统一响应信封：{"code":0,"message":"ok","data":{},"traceId":"..."}。
 */
@JsonInclude(JsonInclude.Include.ALWAYS)
public record ApiResponse<T>(int code, String message, T data, String traceId) {

    public static <T> ApiResponse<T> ok(T data) {
        return new ApiResponse<>(ErrorCode.SUCCESS.getCode(), "ok", data, TraceContext.traceId());
    }

    public static <T> ApiResponse<T> ok() {
        return ok(null);
    }

    public static <T> ApiResponse<T> error(int code, String message) {
        return new ApiResponse<>(code, message, null, TraceContext.traceId());
    }

    public static <T> ApiResponse<T> error(ErrorCode errorCode) {
        return error(errorCode.getCode(), errorCode.getDefaultMessage());
    }
}
