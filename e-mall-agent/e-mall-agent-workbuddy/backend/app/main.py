"""FastAPI entry point: uvicorn app.main:app --reload --port 8000"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.capabilities import router as capabilities_router
from .api.frontier import router as frontier_router
from .api.infra import router as infra_router
from .api.routes import router
from .config import get_settings
from .rag.pipeline import get_rag_pipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_rag_pipeline().ingest()
    yield


app = FastAPI(title=get_settings().app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(router)
app.include_router(capabilities_router)
app.include_router(frontier_router)
app.include_router(infra_router)


@app.exception_handler(PermissionError)
async def permission_handler(request: Request, exc: PermissionError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.get("/", include_in_schema=False)
async def index() -> dict[str, str]:
    return {"name": get_settings().app_name, "docs": "/docs", "api": "/api/health"}
