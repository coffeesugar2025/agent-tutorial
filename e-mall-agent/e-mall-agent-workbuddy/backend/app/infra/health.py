"""基础设施健康聚合器。

汇总每个适配器的 status() 为可序列化 dict，供 /api/infra/health 与 k8s probe
使用。离线回退属于受支持的运行状态，因此未配置外部依赖时 status 仍为 ok。
"""
from __future__ import annotations

from typing import Any

from .llm_gateway import LLMGateway
from .milvus_store import MilvusVectorStore
from .mysql_repo import MySQLRepository
from .rabbitmq import RabbitMQEventBus
from .redis_cache import RedisCache
from .settings import InfraSettings


class InfraHealth:
    """聚合 MySQL / Redis / RabbitMQ / Milvus / LLM 状态。"""

    def __init__(self, settings: InfraSettings | None = None,
                 components: dict[str, Any] | None = None) -> None:
        cfg = settings or InfraSettings.from_env()
        self.settings = cfg
        self.components: dict[str, Any] = components if components is not None else {
            "mysql": MySQLRepository(settings=cfg),
            "redis": RedisCache(settings=cfg),
            "rabbitmq": RabbitMQEventBus(settings=cfg),
            "milvus": MilvusVectorStore(settings=cfg),
            "llm": LLMGateway(settings=cfg),
        }

    def check(self) -> dict[str, Any]:
        """返回可序列化的聚合状态（每个组件含 configured/active/backend/detail）。"""
        statuses = {name: component.status() for name, component in self.components.items()}
        return {
            "status": "ok",
            "configured_count": sum(1 for s in statuses.values() if s.get("configured")),
            "active_count": sum(1 for s in statuses.values() if s.get("active")),
            "components": statuses,
        }

    def as_dict(self) -> dict[str, Any]:
        """check() 的序列化别名。"""
        return self.check()
