"""FastAPI 应用装配：中间件、异常映射、路由、启动/关闭钩子。

启动顺序（任一失败不阻塞服务，只降级）：
1. 结构化日志
2. 数据库连接与可选建表
3. MQ handler 注册 + 消费者线程
4. 本地 drainer 线程（MQ 不可用时兜底消费 ``async_task``）
5. Milvus 集合预建（失败则由 RAG 层自动降级到内存/全文检索）
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-01] 交互协议  |  [CAP-03] 运行时循环
# 职责：FastAPI 应用装配：中间件、异常映射、路由、启动/关闭钩子
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import admin, auth, chat, knowledge, orders, products, system
from app.common.envelope import fail
from app.common.errors import BizError, Codes
from app.common.ids import new_trace_id
from app.common.tracecontext import get_trace_id, set_trace_id
from app.config import settings
from app.infra.db import init_db
from app.obs.metrics import record_request

logger = logging.getLogger(__name__)

_stop_event = threading.Event()
_bg_threads: list[threading.Thread] = []


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动与关闭钩子。"""
    _setup_logging()
    logger.info(
        "启动 %s v%s backend=%s env=%s mock=%s",
        settings.app_name,
        settings.version,
        settings.backend,
        settings.app_env,
        settings.mock_llm,
    )

    _init_database()
    _init_messaging()
    _init_vector_store()

    _stop_event.clear()
    _start_background_threads()

    yield

    _stop_event.set()
    logger.info("正在关闭 %s", settings.app_name)
    try:
        from app.infra.db import dispose

        dispose()
    except Exception as exc:  # noqa: BLE001
        logger.warning("关闭数据库连接池失败: %s", exc)


# ---------------------------------------------------------------------------
# 启动子过程
# ---------------------------------------------------------------------------
def _setup_logging() -> None:
    try:
        from app.obs.logging import setup_logging

        setup_logging()
    except Exception as exc:  # noqa: BLE001
        logging.basicConfig(level=settings.log_level)
        logger.warning("结构化日志初始化失败，使用默认配置: %s", exc)


def _init_database() -> None:
    try:
        init_db(create_tables=settings.auto_create_tables)
        logger.info("数据库就绪 (%s)", "sqlite" if settings.is_sqlite else "mysql")
    except Exception as exc:  # noqa: BLE001 - 数据库不可用时服务仍启动，便于排查
        logger.error("数据库初始化失败: %s", exc)


def _init_messaging() -> None:
    try:
        from app.mq import register_all

        register_all()
        logger.info("MQ handler 注册完成")
    except Exception as exc:  # noqa: BLE001
        logger.error("MQ handler 注册失败: %s", exc)


def _init_vector_store() -> None:
    try:
        from app.rag.store import get_store

        store = get_store()
        store.ensure(settings.collection("knowledge"), settings.embedding_dim)
        store.ensure(settings.collection("product"), settings.embedding_dim)
        store.ensure(settings.collection("memory"), settings.embedding_dim)
        logger.info("向量存储就绪 (%s)", store.name)
    except Exception as exc:  # noqa: BLE001 - 未部署 Milvus 属预期
        logger.warning("向量存储不可用，RAG 将降级到内存/全文检索: %s", exc)


def _start_background_threads() -> None:
    if settings.mq_enabled and settings.mq_consumer_enabled:
        _spawn("mq-consumer", _consume_loop)
    if settings.mq_enabled:
        _spawn("task-drainer", _drain_loop)


def _spawn(name: str, target: Any) -> None:
    thread = threading.Thread(target=target, name=name, daemon=True)
    thread.start()
    _bg_threads.append(thread)
    logger.info("后台线程已启动: %s", name)


def _consume_loop() -> None:
    try:
        from app.infra.rabbit import QueueConsumer

        QueueConsumer().start()
    except Exception as exc:  # noqa: BLE001
        logger.warning("MQ 消费者启动失败（依赖本地 drainer 兜底）: %s", exc)


def _drain_loop() -> None:
    """定期把 ``async_task`` 里积压的任务就地消费（MQ 不可用时的兜底通道）。"""
    try:
        from app.infra.rabbit import drain_pending_tasks
    except Exception as exc:  # noqa: BLE001
        logger.warning("drainer 不可用: %s", exc)
        return

    while not _stop_event.is_set():
        try:
            handled = drain_pending_tasks(limit=10)
            if handled:
                logger.info("本地 drainer 处理 %s 个积压任务", handled)
        except Exception as exc:  # noqa: BLE001
            logger.warning("本地 drainer 异常: %s", exc)
        _stop_event.wait(15.0)


# ---------------------------------------------------------------------------
# 应用
# ---------------------------------------------------------------------------
app = FastAPI(
    title="星图商城 · 电商智能体 API",
    version=settings.version,
    description="导购 / 客服 / 运营三 Agent + RAG + HITL 的可观测 Agent 平台（Python 实现）",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id"],
)


@app.middleware("http")
async def trace_middleware(request: Request, call_next: Any):
    """注入 traceId（沿用上游透传值）、统计耗时、回写响应头。"""
    incoming = request.headers.get("X-Trace-Id")
    trace_id = incoming or new_trace_id()
    set_trace_id(trace_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except BizError:
        raise
    latency = time.perf_counter() - started
    try:
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        record_request(request.method, path, response.status_code, latency)
    except Exception:  # noqa: BLE001 - 指标失败不影响响应
        pass
    response.headers["X-Trace-Id"] = trace_id
    return response


@app.exception_handler(BizError)
async def handle_biz_error(request: Request, exc: BizError):
    """业务异常 → 统一信封 + 语义化 HTTP 状态码。"""
    payload = fail(exc.code, exc.message, trace_id=get_trace_id()).model_dump(by_alias=True)
    return JSONResponse(status_code=exc.http_status, content=payload)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError):
    details = "; ".join(
        f"{'.'.join(str(x) for x in err.get('loc', ()))}: {err.get('msg')}" for err in exc.errors()[:3]
    )
    payload = fail(Codes.PARAM_INVALID, f"参数校验失败: {details}").model_dump(by_alias=True)
    return JSONResponse(status_code=400, content=payload)


@app.exception_handler(Exception)
async def handle_unexpected(request: Request, exc: Exception):
    logger.exception("未捕获异常 path=%s", request.url.path)
    payload = fail(Codes.INTERNAL, "服务内部错误，请稍后重试").model_dump(by_alias=True)
    return JSONResponse(status_code=500, content=payload)


# 业务路由统一挂在 /api/v1 下
API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(chat.router, prefix=API_PREFIX)
app.include_router(products.router, prefix=API_PREFIX)
app.include_router(orders.router, prefix=API_PREFIX)
app.include_router(knowledge.router, prefix=API_PREFIX)
app.include_router(admin.router, prefix=API_PREFIX)
# 系统路由自带完整路径（/health、/metrics、/api/v1/meta/capabilities）
app.include_router(system.router)

# MCP：把工具集暴露为 MCP 端点（/mcp/tools、/mcp/tools/{name}/call 等）
# 未安装 MCP SDK 时该函数返回 False 并降级为纯 JSON 描述，不影响主服务。
try:
    from app.mcp.server import mount as mount_mcp

    _mcp_mounted = mount_mcp(app, allow_write=settings.app_env == "dev")
    logger.info("MCP 端点挂载: %s", _mcp_mounted)
except Exception as exc:  # noqa: BLE001
    logger.warning("MCP 端点挂载失败（不影响主服务）: %s", exc)


@app.get("/", include_in_schema=False)
def root():
    return {
        "name": settings.app_name,
        "backend": settings.backend,
        "version": settings.version,
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":  # pragma: no cover - 本地调试入口
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=settings.app_env == "dev",
        log_level=settings.log_level.lower(),
    )
