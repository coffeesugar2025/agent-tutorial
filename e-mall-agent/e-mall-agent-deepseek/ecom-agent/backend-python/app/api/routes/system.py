"""系统接口：健康检查、Prometheus 指标、能力声明。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from app.common.envelope import ok
from app.config import settings

router = APIRouter(tags=["系统"])


@router.get("/health", summary="健康检查")
def health():
    """逐组件探测；任一 DOWN 时整体 DEGRADED，但 HTTP 仍 200。

    这样 Kubernetes 的 liveness 不会因为下游抖动而重启 Pod，
    readiness 可用响应体里的 components 自行判断。
    """
    components = {
        "mysql": _probe("app.infra.db", "health"),
        "redis": _probe("app.infra.redis", "health"),
        "rabbitmq": _probe_bus(),
        "milvus": _probe_store(),
    }
    status = "UP" if all(v == "UP" for v in components.values()) else "DEGRADED"
    return {"status": status, "components": components, "backend": settings.backend}


@router.get("/metrics", summary="Prometheus 指标")
def metrics():
    try:
        from app.obs.metrics import metrics_text

        payload, content_type = metrics_text()
        return Response(content=payload, media_type=content_type)
    except Exception:  # noqa: BLE001 - 指标不可用不能影响主服务
        return Response(content=b"", media_type="text/plain; version=0.0.4")


@router.get("/api/v1/meta/capabilities", summary="能力声明")
def capabilities():
    """前端据此显示/隐藏实验性入口，并展示当前后端与模型链路。"""
    from app.llm.providers import describe_providers

    providers = describe_providers()
    configured = [p["provider"] for p in providers if p.get("configured")]
    return ok(
        {
            "backend": settings.backend,
            "version": settings.version,
            "features": {
                "mcp": True,
                "skills": True,
                "codeMode": True,
                "text2sql": True,
                "hybridRag": True,
                "approval": True,
                "replay": True,
            },
            "llm": {
                "primary": settings.effective_primary,
                "fallbacks": settings.fallback_providers,
                "configured": configured,
                "providers": providers,
            },
            "limits": {
                "maxSteps": settings.max_steps,
                "maxTokenBudget": settings.max_token_budget,
                "taskTimeoutSeconds": settings.task_timeout_seconds,
                "rateLimitPerMinute": settings.rate_limit_per_minute,
            },
        }
    )


def _probe(module: str, attr: str) -> str:
    try:
        imported = __import__(module, fromlist=[attr])
        func = getattr(imported, attr, None)
        if func is None:
            return "UNKNOWN"
        return str(func())
    except Exception:  # noqa: BLE001
        return "DOWN"


def _probe_bus() -> str:
    try:
        from app.infra.rabbit import message_bus

        return str(message_bus.health())
    except Exception:  # noqa: BLE001
        return "DOWN"


def _probe_store() -> str:
    try:
        from app.rag.store import get_store

        return str(get_store().health())
    except Exception:  # noqa: BLE001
        return "DOWN"


__all__ = ["router"]
