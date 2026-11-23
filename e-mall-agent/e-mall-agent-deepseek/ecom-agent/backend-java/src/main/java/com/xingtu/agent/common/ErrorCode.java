package com.xingtu.agent.common;

/**
 * 契约错误码（docs/03-API契约.md 0.3）。
 */
public enum ErrorCode {

    SUCCESS(0, 200, "ok"),
    VALIDATION(40001, 400, "参数校验失败"),
    UNAUTHORIZED(40100, 401, "未认证或 token 失效"),
    FORBIDDEN(40300, 403, "无权限"),
    NOT_FOUND(40400, 404, "资源不存在"),
    CONFLICT(40900, 409, "状态冲突"),
    RATE_LIMITED(42900, 429, "触发限流"),
    INTERNAL(50000, 500, "服务内部错误"),
    DEGRADED(50300, 503, "模型或依赖降级中"),
    UPSTREAM_TIMEOUT(50400, 504, "上游超时");

    private final int code;
    private final int httpStatus;
    private final String defaultMessage;

    ErrorCode(int code, int httpStatus, String defaultMessage) {
        this.code = code;
        this.httpStatus = httpStatus;
        this.defaultMessage = defaultMessage;
    }

    public int getCode() {
        return code;
    }

    public int getHttpStatus() {
        return httpStatus;
    }

    public String getDefaultMessage() {
        return defaultMessage;
    }
}
