"""基础设施运维端点：健康探针、模型清单、事件发布与缓存读写演示。

权限复用现有 RBAC：项目中没有 llm:read，模型清单使用 chat:use；事件发布
需要 user:manage（仅 admin）；缓存演示使用 trace:read。健康检查无需鉴权，
便于 k8s liveness/readiness probe 直接访问。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..domain.models import User
from ..infra import InfraHealth, LLMGateway, RabbitMQEventBus, RedisCache
from .routes import require

router = APIRouter(prefix="/api/infra")

# 单例：与其余 API 模块保持一致的轻量依赖管理方式
_health = InfraHealth()
_cache = RedisCache()
_event_bus = RabbitMQEventBus()


class EventPublishRequest(BaseModel):
    """手动事件发布请求。"""

    topic: str
    payload: Any = None


class CacheSetRequest(BaseModel):
    """缓存写入请求。"""

    key: str
    value: Any = None
    ttl: int | None = None


@router.get("/health")
async def infra_health() -> dict[str, Any]:
    """聚合健康状态（无需鉴权，供 k8s probe 使用）。"""
    return _health.check()


@router.get("/providers")
async def list_providers(user: User = Depends(require("chat:use"))) -> dict[str, Any]:
    """多模型清单与当前默认供应商。"""
    gateway = LLMGateway()
    return {
        "default": gateway.default_provider,
        "providers": [provider.as_dict() for provider in gateway.list_providers()],
        "status": gateway.status(),
    }


@router.post("/events")
async def publish_event(payload: EventPublishRequest,
                        user: User = Depends(require("user:manage"))) -> dict[str, Any]:
    """手动发布事件到事件总线（仅管理员）。"""
    _event_bus.publish(payload.topic, payload.payload)
    return {"published": True, "topic": payload.topic,
            "backend": _event_bus.status()["backend"]}


@router.get("/cache/{key}")
async def get_cache(key: str,
                    user: User = Depends(require("trace:read"))) -> dict[str, Any]:
    """读取缓存键值演示。"""
    return {"key": key, "value": _cache.get(key), "backend": _cache.status()["backend"]}


@router.post("/cache")
async def set_cache(payload: CacheSetRequest,
                    user: User = Depends(require("trace:read"))) -> dict[str, Any]:
    """写入缓存键值演示（可选 ttl 秒）。"""
    _cache.set(payload.key, payload.value, ttl=payload.ttl)
    return {"key": payload.key, "stored": True, "backend": _cache.status()["backend"]}
