"""集中配置：全部来自环境变量，.env 放在仓库根目录。"""
from __future__ import annotations

import os
import site
import sys
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]
MCP_SERVER_PATH = BACKEND_DIR / "mcp_server" / "server.py"


def _stdio_env() -> dict[str, str]:
    """MCP stdio 子进程默认拿到被裁剪的环境变量，user site-packages 会丢失。

    显式把当前解释器的 site-packages 与项目根目录写进 PYTHONPATH，
    保证 FastMCP 与 app.services 在子进程里一定可导入。
    """
    env = dict(os.environ)
    parts = [str(BACKEND_DIR), os.environ.get("PYTHONPATH", "")]
    for candidate in (site.getusersitepackages(), *site.getsitepackages()):
        if candidate and Path(candidate).is_dir():
            parts.append(str(candidate))
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(p for p in parts if p))
    env["PYTHONUNBUFFERED"] = "1"
    return env


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # 运行模式
    agent_mode: Literal["mock", "real"] = "mock"
    model_name: str = "openai:gpt-4o-mini"
    openai_api_key: str = ""
    openai_base_url: str = ""

    # MCP
    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_http_url: str = "http://127.0.0.1:9000/mcp"
    mcp_client: Literal["builtin", "adapters"] = "builtin"

    # 服务
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    max_tool_calls: int = 8

    # 可观测
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "ecommerce-agent"

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def mcp_config(self) -> dict:
        """LangChain 1.5 内置 MCPAdapter 使用的标准 MCPConfig 结构。

        单服务器可直接传 Path / URL；多服务器用 {"mcpServers": {...}}，
        此时工具名会自动带 `{server}_` 前缀，避免不同 MCP 服务间撞名。
        """
        if self.mcp_transport == "http":
            return {"mcpServers": {"shop": {"url": self.mcp_http_url}}}
        return {
            "mcpServers": {
                "shop": {
                    # 必须用当前解释器：MCPAdapter 拉起的子进程若落到系统 python，
                    # 会找不到 venv 里的 fastmcp / langchain 依赖。
                    "command": sys.executable,
                    "args": [str(MCP_SERVER_PATH)],
                    "env": _stdio_env(),
                }
            }
        }


settings = Settings()
