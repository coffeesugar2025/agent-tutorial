"""业务异常与错误码表（docs/03 §0.3 为唯一事实源）。"""

from __future__ import annotations

from typing import Any

# 错误码 → HTTP 状态码
ERROR_HTTP_STATUS: dict[int, int] = {
    0: 200,
    40001: 400,
    40100: 401,
    40300: 403,
    40400: 404,
    40900: 409,
    42900: 429,
    50000: 500,
    50300: 503,
    50400: 504,
}


class Codes:
    """错误码常量（禁止在业务代码里写魔法数字）。"""

    OK = 0
    PARAM_INVALID = 40001
    UNAUTHORIZED = 40100
    FORBIDDEN = 40300
    NOT_FOUND = 40400
    CONFLICT = 40900
    RATE_LIMITED = 42900
    INTERNAL = 50000
    DEGRADED = 50300
    UPSTREAM_TIMEOUT = 50400


class BizError(Exception):
    """业务异常：由全局异常处理器转换为统一信封。

    :param code: 业务错误码（见 :data:`ERROR_HTTP_STATUS`）
    :param message: 面向用户的中文提示
    :param details: 可选调试信息（不外发敏感内容）
    """

    def __init__(self, code: int, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    @property
    def http_status(self) -> int:
        return ERROR_HTTP_STATUS.get(self.code, 500)

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"BizError(code={self.code}, message={self.message!r})"


def param_invalid(message: str = "参数校验失败", **details: Any) -> BizError:
    return BizError(Codes.PARAM_INVALID, message, details or None)


def unauthorized(message: str = "未认证或登录已过期") -> BizError:
    return BizError(Codes.UNAUTHORIZED, message)


def forbidden(message: str = "无权限访问该资源") -> BizError:
    return BizError(Codes.FORBIDDEN, message)


def not_found(message: str = "资源不存在") -> BizError:
    return BizError(Codes.NOT_FOUND, message)


def conflict(message: str = "状态冲突") -> BizError:
    return BizError(Codes.CONFLICT, message)


def rate_limited(message: str = "请求过于频繁，请稍后再试") -> BizError:
    return BizError(Codes.RATE_LIMITED, message)


def degraded(message: str = "依赖服务降级中，请稍后重试") -> BizError:
    return BizError(Codes.DEGRADED, message)


def upstream_timeout(message: str = "上游服务超时") -> BizError:
    return BizError(Codes.UPSTREAM_TIMEOUT, message)


def internal(message: str = "服务内部错误") -> BizError:
    return BizError(Codes.INTERNAL, message)


__all__ = [
    "ERROR_HTTP_STATUS",
    "BizError",
    "Codes",
    "conflict",
    "degraded",
    "forbidden",
    "internal",
    "not_found",
    "param_invalid",
    "rate_limited",
    "unauthorized",
    "upstream_timeout",
]
