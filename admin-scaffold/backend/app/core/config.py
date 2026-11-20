from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    APP_NAME: str = "FastAPI Admin"
    DEBUG: bool = True
    SECRET_KEY: str = "please-change-this-secret-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # asyncmy（高性能 Cython 扩展）或 aiomysql（纯 Python，免编译）
    MYSQL_DRIVER: str = "asyncmy"
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "admin"
    MYSQL_PASSWORD: str = "admin123"
    MYSQL_DB: str = "admin_scaffold"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""

    RABBITMQ_HOST: str = "localhost"
    RABBITMQ_PORT: int = 5672
    RABBITMQ_USER: str = "guest"
    RABBITMQ_PASSWORD: str = "guest"
    RABBITMQ_VHOST: str = "/"
    RABBITMQ_EXCHANGE: str = "admin.events"

    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_TOPIC: str = "admin.audit"

    ES_HOSTS: str = "http://localhost:9200"
    ES_INDEX: str = "admin-audit"
    ES_USERNAME: str = ""
    ES_PASSWORD: str = ""

    ENABLE_REDIS: bool = True
    ENABLE_RABBITMQ: bool = True
    ENABLE_KAFKA: bool = True
    ENABLE_ES: bool = True

    INIT_ADMIN_USERNAME: str = "admin"
    INIT_ADMIN_PASSWORD: str = "Admin@123"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:8080"

    @property
    def mysql_url(self) -> str:
        driver = self.MYSQL_DRIVER if self.MYSQL_DRIVER in ("asyncmy", "aiomysql") else "asyncmy"
        return (
            f"mysql+{driver}://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DB}?charset=utf8mb4"
        )

    @property
    def redis_url(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def rabbitmq_url(self) -> str:
        return (
            f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASSWORD}"
            f"@{self.RABBITMQ_HOST}:{self.RABBITMQ_PORT}{self.RABBITMQ_VHOST}"
        )

    @property
    def es_hosts(self) -> list[str]:
        return [h.strip() for h in self.ES_HOSTS.split(",") if h.strip()]

    @property
    def es_auth(self) -> tuple[str, str] | None:
        return (self.ES_USERNAME, self.ES_PASSWORD) if self.ES_USERNAME else None

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
