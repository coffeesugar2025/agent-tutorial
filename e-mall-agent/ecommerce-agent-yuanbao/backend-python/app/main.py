"""FastAPI 入口。

启动：
    cd backend && uvicorn app.main:app --reload --port 8000
或：
    python3 -m app.main
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.builder import build_agent, build_intent_agent
from app.agent.mcp_tools import MCPToolProvider
from app.api.routes import router
from app.api.routes_ext import router as ext_router
from app.api.routes_v3 import router as v3_router
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 关键：MCP 连接由应用生命周期持有，Agent 调用工具期间 adapter 必须保持打开
    provider = MCPToolProvider(settings)
    async with provider:
        app.state.provider = provider
        app.state.agent = build_agent(provider.tools)
        app.state.intent_agent = build_intent_agent() if settings.agent_mode == "real" else None
        print(
            f"[boot] langchain=1.5 mode={settings.agent_mode} "
            f"tools={len(provider.tools)} source={provider.source}"
            + (f" fallback_reason={provider.error}" if provider.error else "")
        )
        yield


def create_app() -> FastAPI:
    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
        os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)

    app = FastAPI(
        title="电商智能体 · Ecommerce Agent",
        version="1.0.0",
        description="LangChain 1.5 create_agent + MCP Tools + Vue3 前端",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(ext_router)
    app.include_router(v3_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.app_host, port=settings.app_port)
