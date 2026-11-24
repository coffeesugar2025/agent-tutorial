"""统一配置：所有外部依赖开关集中在这里，不散落在业务代码。"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _b(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    llm_mode: str = os.getenv("LLM_MODE", "mock")
    default_provider: str = os.getenv("DEFAULT_PROVIDER", "deepseek")
    model_version_pin: str = os.getenv("MODEL_VERSION_PIN", "")
    mysql_host: str = os.getenv("MYSQL_HOST", "localhost")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_user: str = os.getenv("MYSQL_USER", "agent")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "")
    mysql_db: str = os.getenv("MYSQL_DB", "ecommerce_agent")
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    rabbit_host: str = os.getenv("RABBITMQ_HOST", "localhost")
    rabbit_user: str = os.getenv("RABBITMQ_USER", "guest")
    rabbit_password: str = os.getenv("RABBITMQ_PASSWORD", "guest")
    milvus_host: str = os.getenv("MILVUS_HOST", "localhost")
    milvus_port: int = int(os.getenv("MILVUS_PORT", "19530"))
    milvus_collection: str = os.getenv("MILVUS_COLLECTION", "ecommerce_chunks")
    use_external: bool = _b("USE_EXTERNAL_INFRA")

    def describe(self) -> dict[str, object]:
        return {k: ("***" if "password" in k or "key" in k else v)
                for k, v in self.__dict__.items()}


S = Settings()
