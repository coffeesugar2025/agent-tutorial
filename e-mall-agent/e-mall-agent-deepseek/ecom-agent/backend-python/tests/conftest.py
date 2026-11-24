"""pytest 全局夹具：让测试零外部依赖。

固定环境（必须在 ``import app.*`` 之前写入 ``os.environ``，因为
``app.config.settings`` / ``app.infra.db.engine`` 在导入期就读取配置）：

* ``MOCK_LLM=true``：LLM 走确定性 Mock，不需要任何 API Key；
* ``EMBEDDING_PROVIDER=hash``：离线哈希向量；
* ``VECTOR_STORE=memory``：进程内向量库，不连 Milvus；
* ``MQ_ENABLED=false``：不连 RabbitMQ；
* ``DATABASE_URL=sqlite:///./test.db``：文件型 SQLite，跨连接可见（内存库会因连接池丢表）。

另外每个用例前后都会清理 ``get_settings`` 缓存、embedding 单例、内存向量库与
临时业务数据，保证用例之间互不影响。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-17] 评测与迭代  （支撑）
# 职责：pytest 全局夹具：让测试零外部依赖
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_OFFLINE_ENV: dict[str, str] = {
    "APP_ENV": "test",
    "MOCK_LLM": "true",
    "LLM_PRIMARY": "mock",
    "EMBEDDING_PROVIDER": "hash",
    "VECTOR_STORE": "memory",
    "MQ_ENABLED": "false",
    "MQ_CONSUMER_ENABLED": "false",
    "DATABASE_URL": "sqlite:///./test.db",
    "AUTO_CREATE_TABLES": "true",
    "RERANK_PROVIDER": "none",
    "EVAL_SUITES_DIR": "eval_data",
    "SKILLS_DIR": "",
}

for _key, _value in _OFFLINE_ENV.items():
    os.environ[_key] = _value

import pytest  # noqa: E402

TEST_DB_FILE = Path("test.db")


@pytest.fixture(scope="session", autouse=True)
def offline_settings():
    """清理配置缓存并断言离线配置生效（防止环境变量被外部覆盖）。"""
    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()
    assert settings.mock_llm is True, "测试必须使用 MOCK_LLM=true"
    assert settings.embedding_provider == "hash"
    assert settings.vector_store == "memory"
    assert settings.mq_enabled is False
    assert settings.database_uri.startswith("sqlite"), settings.database_uri
    yield settings
    # 会话结束：释放连接池并删除 SQLite 文件
    try:
        from app.infra.db import dispose

        dispose()
    finally:
        TEST_DB_FILE.unlink(missing_ok=True)


@pytest.fixture(scope="session", autouse=True)
def database(offline_settings):
    """建表（session 级），结束时 drop_all。"""
    from app.infra.db import Base, engine, init_db

    import app.infra.models  # noqa: F401  注册业务表
    import app.infra.models_obs  # noqa: F401  注册可观测性/评测表

    init_db(create_tables=True)
    yield engine
    Base.metadata.drop_all(bind=engine)


def _purge_transient_rows() -> None:
    """清空测试期间写入的临时数据（知识库 / 幂等 / 审计 / LLM 账单）。"""
    from sqlalchemy import delete

    from app.infra.db import session_scope
    from app.infra.models import KnowledgeChunk, KnowledgeDocument, KnowledgeJob
    from app.infra.models_obs import (
        AuditLog,
        EvalCaseResult,
        EvalRun,
        IdempotencyRecord,
        LlmCall,
    )

    with session_scope() as db:
        for model in (
            EvalCaseResult,
            EvalRun,
            KnowledgeChunk,
            KnowledgeDocument,
            KnowledgeJob,
            IdempotencyRecord,
            AuditLog,
            LlmCall,
        ):
            db.execute(delete(model))


@pytest.fixture(autouse=True)
def clean_state(database):
    """每个用例前后重置单例与临时数据。"""
    from app.config import get_settings
    from app.rag.embedding import reset_embedding
    from app.rag.store import reset_stores

    get_settings.cache_clear()
    reset_embedding()
    reset_stores()
    _purge_transient_rows()
    yield
    reset_embedding()
    reset_stores()


@pytest.fixture
def settings():
    """当前配置（离线）。"""
    from app.config import get_settings

    return get_settings()


@pytest.fixture
def db_session(database):
    """直接操作数据库的会话（用例内手工提交/查询）。"""
    from app.infra.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
