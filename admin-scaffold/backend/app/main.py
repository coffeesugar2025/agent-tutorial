from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app import __version__
from app.api import api_router
from app.core.config import settings
from app.db.elasticsearch import es_client
from app.db.mysql import close_mysql, init_tables
from app.db.redis import redis_client
from app.mq.kafka import kafka_client
from app.mq.rabbitmq import rabbit_client
from scripts.seed import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"{settings.APP_NAME} v{__version__} starting ...")
    try:
        await init_tables()
        await seed()
    except Exception as exc:
        logger.error(f"[mysql] 初始化失败：{exc}")
        msg = str(exc)
        if "cryptography" in msg or "caching_sha2_password" in msg or "sha256_password" in msg:
            logger.error(
                "[mysql] 缺少 MySQL 8 认证所需的加密依赖。请执行：pip install cryptography "
                "（或重跑 pip install -r requirements.txt），然后重启服务。"
            )
        elif "MissingGreenlet" in msg or "greenlet_spawn" in msg:
            logger.error(
                "[mysql] 异步会话里发生了隐式 IO：某个 ORM 关系未被预加载就被读/写了。"
                "请确认用的是最新版脚手架（seed.py 在构造时传关联、crud.py 统一 selectinload 预加载），"
                "再重启服务。详见 README 的 MissingGreenlet 排障章节。"
            )
        elif "Access denied" in msg or "1045" in msg:
            logger.error(
                "[mysql] 账号或密码不对，请核对 backend/.env 的 MYSQL_USER / MYSQL_PASSWORD；"
                "若用 docker compose 起的库，默认是 admin / admin123。"
            )
        else:
            logger.error(
                "MySQL 是本项目的唯一强依赖，请先启动 MySQL 并核对 backend/.env："
                "docker compose up -d mysql  （或检查 MYSQL_HOST / MYSQL_PORT / MYSQL_USER / "
                "MYSQL_PASSWORD / MYSQL_DB / MYSQL_DRIVER）"
            )
        raise
    await redis_client.connect()
    await es_client.connect()
    await rabbit_client.connect()
    await kafka_client.connect()
    logger.info("startup finished (optional middlewares degrade gracefully)")
    yield
    await kafka_client.close()
    await rabbit_client.close()
    await es_client.close()
    await redis_client.close()
    await close_mysql()
    logger.info("shutdown finished")


app = FastAPI(
    title=settings.APP_NAME,
    version=__version__,
    description="FastAPI + MySQL/Redis/RabbitMQ/Kafka/ES 管理系统脚手架",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": str(exc.detail), "data": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"code": 422, "message": "参数校验失败", "data": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(f"unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": "服务器内部错误", "data": None},
    )


@app.get("/", include_in_schema=False)
async def root():
    return {"name": settings.APP_NAME, "version": __version__, "docs": "/docs"}
