"""Central configuration. All settings are overridable with ECOM_* env vars."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="ECOM_", extra="ignore", case_sensitive=False
    )

    app_name: str = "E-Commerce Intelligent Agent"
    debug: bool = False

    # LLM: "offline" uses a deterministic rule-based tool-calling model so the
    # whole system is runnable/testable without an API key. "openai" uses a real model.
    llm_provider: str = "offline"
    llm_model: str = "gpt-4o-mini"
    openai_api_key: str = ""

    # MCP: "local" loads the exact same tool functions in-process (dev/test),
    # "http" connects to the standalone FastMCP server via streamable HTTP.
    mcp_mode: str = "local"
    mcp_http_url: str = "http://127.0.0.1:8001/mcp"

    context_max_chars: int = 3200
    context_recent_messages: int = 8
    rag_top_k: int = 3

    secret_key: str = "dev-secret-change-me"
    token_ttl_seconds: int = 3600
    audit_max_entries: int = 500


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
