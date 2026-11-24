"""统一响应信封与分页结构。

契约（docs/03 §0.1/§0.2）要求外发 JSON 全部为 camelCase，因此所有 VO 继承
:class:`CamelModel`，内部用 snake_case 字段并以 alias 序列化（FastAPI 默认
``by_alias=True``）。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-01] 交互协议  |  [CAP-14] 可靠性/降级  （支撑）
# 职责：统一响应信封与分页结构
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import re
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.common.tracecontext import get_trace_id

T = TypeVar("T")

_CAMEL_RE = re.compile(r"_([a-z0-9])")


def to_camel(name: str) -> str:
    """snake_case → camelCase；以下划线开头的私有字段不做转换。"""
    if name.startswith("_"):
        return name
    return _CAMEL_RE.sub(lambda m: m.group(1).upper(), name)


def to_snake(name: str) -> str:
    """camelCase → snake_case。"""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class CamelModel(BaseModel):
    """对外 VO 基类：自动驼峰别名、允许按字段名或别名构造。"""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="ignore",
    )


class ApiResponse(CamelModel, Generic[T]):
    """统一响应信封：code=0 表示成功。"""

    code: int = 0
    message: str = "ok"
    data: T | None = None
    trace_id: str = Field(default_factory=get_trace_id)


class PageData(CamelModel, Generic[T]):
    """分页数据体（放在信封的 data 中）。"""

    items: list[T] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    size: int = 20


class PageQuery(BaseModel):
    """分页查询参数（page 从 1 开始）。"""

    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


def ok(data: Any = None, message: str = "ok") -> ApiResponse[Any]:
    """构造成功信封。"""
    return ApiResponse[Any](code=0, message=message, data=data, trace_id=get_trace_id())


def fail(code: int, message: str, trace_id: str | None = None) -> ApiResponse[Any]:
    """构造失败信封（HTTP 状态码由 errors 模块决定）。"""
    return ApiResponse[Any](
        code=code,
        message=message,
        data=None,
        trace_id=trace_id if trace_id is not None else get_trace_id(),
    )


def page_result(items: list[Any], total: int, page: int, size: int) -> PageData[Any]:
    """包装分页结果。"""
    return PageData[Any](items=items, total=total, page=page, size=size)


__all__ = [
    "ApiResponse",
    "CamelModel",
    "PageData",
    "PageQuery",
    "fail",
    "ok",
    "page_result",
    "to_camel",
    "to_snake",
]
