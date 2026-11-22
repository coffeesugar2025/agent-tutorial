"""共享 fixture。

注意：MCPAdapter 绑定创建它的 event loop，因此不在不同 loop 间复用 provider；
e2e 用例各自用 async with 打开，API 用例由 TestClient 在自己的 lifespan 中持有。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
