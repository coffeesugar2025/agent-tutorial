package com.xingtu.agent.common;

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
