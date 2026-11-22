"""MCP 工具装载层。

主路径：LangChain 1.5 内置 `langchain.mcp.MCPAdapter`（1.4+ 随 langchain[mcp] 提供，
标准 MCPConfig 结构，支持 stdio 子进程与 Streamable HTTP，工具名自动带 server 前缀）。
兼容路径：`langchain_mcp_adapters.MultiServerMCPClient`（旧写法，可选依赖）。
降级路径：本地 @tool 工具，保证 MCP 服务不可用时智能体仍能回答。
"""
from __future__ import annotations

import warnings
from typing import Any

from langchain_core.tools import BaseTool, tool

from app.config import Settings, settings
from app.services import catalog

warnings.filterwarnings("ignore", message=".*langchain.mcp.*beta.*")


def _as_local_tools() -> list[BaseTool]:
    """把同一批领域函数注册成本地 @tool，作为 MCP 不可用时的降级实现。"""

    @tool
    def local_search_products(keyword: str = "", max_price: float | None = None, limit: int = 5) -> dict:
        """检索商品：按关键词与价格上限返回 SKU、价格、库存、评分。"""
        return catalog.search_products(keyword=keyword, max_price=max_price, limit=limit)

    @tool
    def local_get_order(order_id: str, user_id: str = "u_1001") -> dict:
        """按订单号查询状态、金额与物流节点，user_id 用于归属校验。"""
        return catalog.get_order(order_id, user_id)

    @tool
    def local_calculate_price(sku: str, quantity: int = 1, coupon_code: str | None = None) -> dict:
        """计算到手价，返回原价、优惠拆解与应付金额。"""
        return catalog.calculate_price(sku, quantity, coupon_code)

    @tool
    def local_recommend_products(budget: float = 1000.0, preference: str = "") -> dict:
        """按预算与偏好推荐有货商品。"""
        return catalog.recommend_products(budget=budget, preference=preference)

    return [local_search_products, local_get_order, local_calculate_price, local_recommend_products]


class MCPToolProvider:
    """用 async context manager 管理 MCP 连接生命周期。

    关键：adapter / client 必须在 Agent 仍能调用工具的整个期间保持打开，
    因此由 FastAPI lifespan 持有，而不是每次请求创建。
    """

    def __init__(self, cfg: Settings | None = None) -> None:
        self.cfg = cfg or settings
        self.tools: list[Any] = []
        self.source: str = "uninitialized"
        self.error: str | None = None
        self._adapter: Any = None
        self._client: Any = None

    async def __aenter__(self) -> "MCPToolProvider":
        try:
            if self.cfg.mcp_client == "adapters":
                await self._open_with_adapters()
            else:
                await self._open_with_builtin()
        except Exception as exc:  # 降级，不让单点故障拖垮整个服务
            self.error = f"{type(exc).__name__}: {exc}"
            self.tools = _as_local_tools()
            self.source = "local-fallback"
        if not self.tools:
            self.tools = _as_local_tools()
            self.source = "local-fallback"
        return self

    async def _open_with_builtin(self) -> None:
        from langchain.mcp import MCPAdapter

        adapter = MCPAdapter(self.cfg.mcp_config)
        await adapter.__aenter__()
        self._adapter = adapter
        self.tools = await adapter.list_tools()
        self.source = f"builtin-mcp/{self.cfg.mcp_transport}"

    async def _open_with_adapters(self) -> None:
        from langchain_mcp_adapters.client import MultiServerMCPClient

        conf = self.cfg.mcp_config["mcpServers"]["shop"]
        if self.cfg.mcp_transport == "http":
            server = {"transport": "streamable_http", "url": conf["url"]}
        else:
            server = {"transport": "stdio", "command": conf["command"], "args": conf["args"]}
        self._client = MultiServerMCPClient({"shop": server})
        self.tools = await self._client.get_tools()
        self.source = "langchain-mcp-adapters"

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._adapter is not None:
            try:
                await self._adapter.__aexit__(exc_type, exc, tb)
            except Exception:
                pass
        if self._client is not None:
            closer = getattr(self._client, "aclose", None) or getattr(self._client, "close", None)
            if closer:
                try:
                    result = closer()
                    if hasattr(result, "__await__"):
                        await result
                except Exception:
                    pass

    def describe(self) -> list[dict[str, str]]:
        out = []
        for t in self.tools:
            name = t.get("name", "") if isinstance(t, dict) else getattr(t, "name", "")
            desc = t.get("description", "") if isinstance(t, dict) else getattr(t, "description", "")
            out.append({"name": name, "description": (desc or "").strip().split("\n")[0][:160], "source": self.source})
        return out
