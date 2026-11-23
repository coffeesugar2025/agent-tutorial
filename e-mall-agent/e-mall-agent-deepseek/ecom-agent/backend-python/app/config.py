"""应用配置：pydantic-settings 读取环境变量，覆盖 docs/00 第 2 节全部变量。

设计要点：
1. 变量名与 Java 端完全同名同义，便于 docker-compose 一份 .env 双端复用；
2. ``DATABASE_URL`` 为显式覆盖项（测试用 SQLite 时不改 MySQL 变量）；
3. 所有派生连接串以 property 暴露，禁止在业务代码里手工拼串；
4. ``MOCK_LLM=true`` 时 ``effective_primary`` 强制为 ``mock``，保证离线可跑。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """全部运行期配置。``.env`` 与真实环境变量同时生效，后者优先。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- 基础 -----------------------------------------------------------------
    app_env: str = "dev"
    app_name: str = "ecom-agent"
    version: str = "1.0.0"
    backend: str = "python"
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    log_level: str = "INFO"
    timezone: str = "Asia/Shanghai"
    cors_origins: str = "*"

    # --- MySQL ---------------------------------------------------------------
    mysql_host: str = "mysql"
    mysql_port: int = 3306
    mysql_db: str = "ecom_agent"
    mysql_user: str = "ecom"
    mysql_password: str = "ecom123"
    database_url: str | None = None
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle: int = 1800
    auto_create_tables: bool = False

    # --- Redis ---------------------------------------------------------------
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    redis_socket_timeout: float = 1.0
    redis_connect_timeout: float = 0.5

    # --- RabbitMQ ------------------------------------------------------------
    rabbitmq_host: str = "rabbitmq"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "ecom"
    rabbitmq_password: str = "ecom123"
    rabbitmq_vhost: str = "ecom"
    rabbitmq_heartbeat: int = 60
    mq_enabled: bool = True
    mq_consumer_enabled: bool = True
    mq_exchange: str = "ecom.agent"
    mq_dlx_exchange: str = "ecom.agent.dlx"
    mq_max_retry: int = 3
    mq_queue_prefix: str = "ecom.agent.py"

    # --- Milvus --------------------------------------------------------------
    milvus_host: str = "milvus"
    milvus_port: int = 19530
    milvus_collection_prefix: str = "ecom"
    # auto / memory / milvus
    vector_store: str = "auto"

    # --- LLM -----------------------------------------------------------------
    llm_primary: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-max"
    qwen_fast_model: str = "qwen-turbo"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "qwen2.5:7b"
    llm_fallbacks: str = "qwen,openai"
    llm_temperature: float = 0.3
    llm_request_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    agent_engine: str = "native"

    # --- Embedding / Rerank --------------------------------------------------
    embedding_provider: str = "dashscope"
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024
    rerank_provider: str = "llm"
    rerank_top_n: int = 5

    # --- 安全 ----------------------------------------------------------------
    jwt_secret: str = "dev-only-change-me-32bytes-minimum!"
    jwt_algorithm: str = "HS256"
    jwt_expire_seconds: int = 86400
    rate_limit_per_minute: int = 30
    max_login_failures: int = 5

    # --- Agent 运行时 --------------------------------------------------------
    max_steps: int = 12
    max_token_budget: int = 60000
    task_timeout_seconds: int = 120
    approval_amount_threshold_cents: int = 100000
    approval_timeout_seconds: int = 1800
    summary_trigger_messages: int = 20
    memory_half_life_days: int = 30
    session_history_limit: int = 30

    # --- RAG -----------------------------------------------------------------
    knowledge_top_k: int = 5
    retrieval_dense_top_k: int = 20
    retrieval_sparse_top_k: int = 20
    chunk_size: int = 400
    chunk_overlap: int = 80
    parent_chunk_size: int = 1200
    upload_dir: str = "var/uploads"
    max_upload_mb: int = 20

    # --- 其它 ----------------------------------------------------------------
    mock_llm: bool = False
    eval_suites_dir: str = "eval_data"
    skills_dir: str = ""
    seed_demo: bool = False
    text2sql_max_rows: int = 200
    python_sandbox_timeout: float = 5.0

    # --- 校验/派生 -----------------------------------------------------------
    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @field_validator("vector_store")
    @classmethod
    def _check_vector_store(cls, value: str) -> str:
        allowed = {"auto", "memory", "milvus"}
        if value.lower() not in allowed:
            raise ValueError(f"VECTOR_STORE 只能是 {sorted(allowed)}")
        return value.lower()

    @field_validator("agent_engine")
    @classmethod
    def _check_engine(cls, value: str) -> str:
        allowed = {"native", "langchain"}
        if value.lower() not in allowed:
            raise ValueError(f"AGENT_ENGINE 只能是 {sorted(allowed)}")
        return value.lower()

    @property
    def mysql_dsn(self) -> str:
        """SQLAlchemy 同步 MySQL 连接串（utf8mb4，毫秒时间由库端负责）。"""
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_db}?charset=utf8mb4"
        )

    @property
    def database_uri(self) -> str:
        """实际使用的连接串：DATABASE_URL 优先（测试/SQLite）。"""
        return self.database_url or self.mysql_dsn

    @property
    def is_sqlite(self) -> bool:
        return self.database_uri.startswith("sqlite")

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def redis_configured(self) -> bool:
        """未显式配置 host 时视为不使用 Redis（纯本地降级模式）。"""
        return bool(self.redis_host)

    @property
    def milvus_uri(self) -> str:
        return f"http://{self.milvus_host}:{self.milvus_port}"

    @property
    def effective_primary(self) -> str:
        """MOCK_LLM=true 时无条件走 mock，任何 API Key 都不需要。"""
        return "mock" if self.mock_llm else self.llm_primary

    @property
    def fallback_providers(self) -> list[str]:
        return [p.strip().lower() for p in self.llm_fallbacks.split(",") if p.strip()]

    @property
    def provider_chain(self) -> list[str]:
        """主供应商 + 兜底链（去重，保持顺序）。"""
        chain = [self.effective_primary, *self.fallback_providers]
        seen: list[str] = []
        for item in chain:
            if item and item not in seen:
                seen.append(item)
        return seen

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def skills_path(self) -> Path:
        return Path(self.skills_dir) if self.skills_dir else PROJECT_ROOT / "app" / "skills" / "builtin"

    def collection(self, suffix: str) -> str:
        """集合名：``{prefix}_{suffix}``，与 docs/00 的 ecom_knowledge 等保持一致。"""
        return f"{self.milvus_collection_prefix}_{suffix}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程级单例；测试可用 ``get_settings.cache_clear()`` 重置。"""
    return Settings()


settings: Settings = get_settings()

__all__ = ["Settings", "get_settings", "settings", "PROJECT_ROOT"]
