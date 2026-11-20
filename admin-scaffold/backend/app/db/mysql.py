from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.mysql_url,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_recycle=3600,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_tables() -> None:
    # 脚手架用 create_all 快速起步；生产环境请接 Alembic 做版本迁移
    from app import models  # noqa: F401  确保模型已注册

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_mysql() -> None:
    await engine.dispose()
