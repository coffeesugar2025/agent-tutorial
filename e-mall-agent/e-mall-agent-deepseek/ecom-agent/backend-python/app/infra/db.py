"""数据库引擎与会话管理（SQLAlchemy 2.x 同步 ORM）。

约定：
* 生产连 MySQL（PyMySQL 驱动），测试可用 ``DATABASE_URL=sqlite+pysqlite:///...``；
* 库内时间一律 naive UTC；``DATETIME(3)`` 精度由库端 schema 决定；
* 业务代码统一用 :func:`session_scope` 或 FastAPI 的 :func:`get_db` 依赖，
  禁止全局共享 Session（非线程安全）。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """所有 ORM 模型基类（``metadata`` 供建表/测试使用）。"""


def _build_engine() -> Engine:
    uri = settings.database_uri
    kwargs: dict[str, object] = {"echo": settings.db_echo, "future": True}
    if uri.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in uri:
            kwargs["poolclass"] = StaticPool
    else:
        kwargs.update(
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_recycle=settings.db_pool_recycle,
            pool_timeout=30,
        )
    return create_engine(uri, **kwargs)


engine: Engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：请求级 Session，异常回滚。"""
    db = SessionLocal()
    try:
        yield db
    except Exception:  # noqa: BLE001 - 必须回滚后再抛出
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """后台任务/脚本使用的会话上下文（自动提交/回滚/关闭）。"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db(create_tables: bool | None = None) -> None:
    """初始化：导入模型并（可选）建表。

    生产环境使用 ``deploy/mysql/init/01-schema.sql`` 建表，这里默认只做导入，
    只有显式开启 ``AUTO_CREATE_TABLES``（或测试）才 ``create_all``。
    """
    from app.infra import models, models_obs  # noqa: F401  确保模型注册到 metadata

    should_create = settings.auto_create_tables if create_tables is None else create_tables
    if should_create:
        Base.metadata.create_all(bind=engine)
        logger.info("已按 ORM 元数据建表（auto_create_tables=true）")


def ping() -> bool:
    """探活：执行 ``SELECT 1``。"""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("MySQL 探活失败: %s", exc)
        return False


def health() -> str:
    return "UP" if ping() else "DOWN"


def dispose() -> None:
    """关闭连接池（应用退出/测试清理）。"""
    engine.dispose()


__all__ = ["Base", "SessionLocal", "dispose", "engine", "get_db", "health", "init_db", "ping", "session_scope"]
