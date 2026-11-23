"""权限感知检索：在不改动 pipeline / hybrid 的前提下增加 ACL 行级过滤。

- ``ACLPolicy``：owner / allowed_users / denied_users / tenant 四要素。
- ``row_level_filter``：对任意检索结果列表按用户与租户做行级过滤。
- ``ACLFilteredRetriever``：包装现有检索器，强制传入 ``user_id`` 才返回结果。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .hybrid import RetrievedChunk


@dataclass
class ACLPolicy:
    """单条记录的访问控制策略；显式允许优先于默认，拒绝始终优先。"""

    owner: str | None = None
    allowed_users: set[str] = field(default_factory=set)
    denied_users: set[str] = field(default_factory=set)
    tenant: str | None = None

    @classmethod
    def from_dict(cls, data: Any) -> "ACLPolicy | None":
        """从字典或其他 ACLPolicy 构造；空值返回 None。"""
        if data is None:
            return None
        if isinstance(data, ACLPolicy):
            return data
        if not isinstance(data, dict) or not data:
            return None
        return cls(
            owner=data.get("owner"),
            allowed_users=set(data.get("allowed_users") or []),
            denied_users=set(data.get("denied_users") or []),
            tenant=data.get("tenant"),
        )

    def allows(self, user_id: str, tenant: str | None = None) -> bool:
        """判断用户（及可选租户）是否有权访问该记录。"""
        if not user_id:
            return False
        if user_id in self.denied_users:
            return False
        if self.tenant is not None and tenant is not None and tenant != self.tenant:
            return False
        if self.owner and user_id == self.owner:
            return True
        return bool(self.allowed_users) and user_id in self.allowed_users

    def as_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "allowed_users": sorted(self.allowed_users),
            "denied_users": sorted(self.denied_users),
            "tenant": self.tenant,
        }


_ACL_FIELDS = ("owner", "allowed_users", "denied_users", "tenant")


def _policy_of(record: Any, policy_key: str) -> ACLPolicy | None:
    """从结果对象 / 字典中提取 ACL 策略；无策略返回 None。"""
    if isinstance(record, ACLPolicy):
        return record
    if isinstance(record, dict):
        metadata = record.get("metadata") or {}
        embedded = record.get(policy_key)
        if embedded is None:
            embedded = metadata.get(policy_key)
        if embedded is not None:
            return ACLPolicy.from_dict(embedded)
        fields = {key: metadata[key] if key in metadata else record[key]
                  for key in _ACL_FIELDS
                  if key in metadata or key in record}
        return ACLPolicy.from_dict(fields) if fields else None
    if isinstance(record, RetrievedChunk):
        metadata = record.metadata or {}
        embedded = metadata.get(policy_key)
        if embedded is not None:
            return ACLPolicy.from_dict(embedded)
        fields = {key: metadata[key] for key in _ACL_FIELDS if key in metadata}
        return ACLPolicy.from_dict(fields) if fields else None
    metadata = getattr(record, "metadata", None)
    if isinstance(metadata, dict) and policy_key in metadata:
        return ACLPolicy.from_dict(metadata[policy_key])
    return None


def row_level_filter(
    records: Iterable[Any],
    user_id: str,
    *,
    tenant: str | None = None,
    policy_key: str = "acl",
    deny_by_default: bool = False,
) -> list[Any]:
    """按用户（可选租户）过滤检索结果。

    Args:
        records: 检索结果列表，元素可为字典、``RetrievedChunk`` 或任意带 metadata 的对象。
        user_id: 当前用户标识，必填。
        tenant: 租户标识，用于校验策略中的 tenant。
        policy_key: 策略在 metadata / 字典中的字段名。
        deny_by_default: 无 ACL 策略的记录是否默认拒绝（默认放行公共知识）。
    """
    if not user_id:
        return []
    result: list[Any] = []
    for record in records:
        policy = _policy_of(record, policy_key)
        if policy is None:
            if not deny_by_default:
                result.append(record)
        elif policy.allows(user_id, tenant):
            result.append(record)
    return result


class ACLFilteredRetriever:
    """包装任意检索器，强制按 ``user_id`` 做行级过滤后再返回。"""

    def __init__(
        self,
        retriever: Callable[..., list[Any]] | Any,
        *,
        default_tenant: str | None = None,
        policy_key: str = "acl",
        deny_by_default: bool = False,
    ) -> None:
        self.retriever = retriever
        self.default_tenant = default_tenant
        self.policy_key = policy_key
        self.deny_by_default = deny_by_default

    def retrieve(self, query: str, user_id: str, *,
                 tenant: str | None = None, **kwargs: Any) -> list[Any]:
        """先调用底层检索，再应用 ACL 过滤；未传 user_id 直接返回空。"""
        if not user_id:
            return []
        if hasattr(self.retriever, "retrieve"):
            results = self.retriever.retrieve(query, **kwargs)
        else:
            results = self.retriever(query, **kwargs)
        return row_level_filter(
            results or [],
            user_id,
            tenant=tenant or self.default_tenant,
            policy_key=self.policy_key,
            deny_by_default=self.deny_by_default,
        )

    # 便于直接替换带 search 方法的检索器
    search = retrieve


__all__ = ["ACLPolicy", "ACLFilteredRetriever", "row_level_filter"]
