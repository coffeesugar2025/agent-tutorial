"""检索层 ACL：先过滤再检索（总纲 4.7 / 5.3，越权召回是高频事故）。

原则：权限过滤必须发生在**召回之前**，不能召回完再丢弃（会泄漏存在性，且浪费预算）。
命名空间隔离 + 行级 tenant_id + 角色白名单，三层同时生效。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant_id: str
    roles: tuple[str, ...] = ("user",)

    @classmethod
    def from_headers(cls, user_id: str, tenant_id: str | None = None,
                     roles: str = "user") -> "Principal":
        """身份来自网关注入的可信 header，绝不信模型自述的 user_id。"""
        return cls(user_id=user_id, tenant_id=tenant_id or "t_default",
                   roles=tuple(r.strip() for r in roles.split(",") if r.strip()))


def acl_filter(principal: Principal, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    visible = []
    for c in chunks:
        meta = c.get("meta", {}) or {}
        tenant = meta.get("acl_tenant", c.get("acl_tenant", "t_default"))
        allowed = meta.get("acl_roles", c.get("acl_roles", ["user"]))
        if isinstance(allowed, str):
            allowed = [r.strip() for r in allowed.split(",")]
        if tenant != principal.tenant_id:
            continue
        if not set(principal.roles) & set(allowed):
            continue
        visible.append(c)
    return {"principal": {"user_id": principal.user_id, "tenant_id": principal.tenant_id,
                          "roles": list(principal.roles)},
            "input": len(chunks), "visible": len(visible),
            "filtered_out": len(chunks) - len(visible), "chunks": visible}


def acl_milvus_expr(principal: Principal) -> str:
    """生成下推到 Milvus 的标量过滤表达式（检索前执行）。"""
    roles = ",".join(f'"{r}"' for r in principal.roles)
    return f'acl_tenant == "{principal.tenant_id}" and acl_roles in [{roles}]'


def assert_no_cross_tenant(principal: Principal, hits: list[dict[str, Any]]) -> bool:
    return all((h.get("meta", {}).get("acl_tenant", h.get("acl_tenant", "t_default"))
                == principal.tenant_id) for h in hits)
