package com.xingtu.agent.common;

// ═══════ 文件级能力标注 ═══════
// [CAP-01] 交互协议  |  [CAP-14] 可靠性/降级  （支撑）
// 职责：业务异常：携带契约错误码与 HTTP 语义状态码
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

/**
 * 业务异常：携带契约错误码与 HTTP 语义状态码。
 */
public class BizException extends RuntimeException {

    private final int code;
    private final int httpStatus;

    public BizException(ErrorCode errorCode) {
        this(errorCode.getCode(), errorCode.getHttpStatus(), errorCode.getDefaultMessage());
    }

    public BizException(ErrorCode errorCode, String message) {
        this(errorCode.getCode(), errorCode.getHttpStatus(), message);
    }

    public BizException(int code, int httpStatus, String message) {
        super(message);
        this.code = code;
        this.httpStatus = httpStatus;
    }

    public int getCode() {
        return code;
    }

    public int getHttpStatus() {
        return httpStatus;
    }

    public static BizException validation(String message) {
        return new BizException(ErrorCode.VALIDATION, message);
    }

    public static BizException unauthorized(String message) {
        return new BizException(ErrorCode.UNAUTHORIZED, message);
    }

    public static BizException forbidden(String message) {
        return new BizException(ErrorCode.FORBIDDEN, message);
    }

    public static BizException notFound(String message) {
        return new BizException(ErrorCode.NOT_FOUND, message);
    }

    public static BizException conflict(String message) {
        return new BizException(ErrorCode.CONFLICT, message);
    }

    public static BizException degraded(String message) {
        return new BizException(ErrorCode.DEGRADED, message);
    }

    public static BizException rateLimited(String message) {
        return new BizException(ErrorCode.RATE_LIMITED, message);
    }
}
