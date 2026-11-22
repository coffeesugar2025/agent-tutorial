"""Shared fixtures: deterministic state reset for every test."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.workflows.fulfillment as fulfillment  # noqa: E402
from app.agents.supervisor import get_conversation_store  # noqa: E402
from app.domain.models import User  # noqa: E402
from app.domain.repository import reset_repository  # noqa: E402
from app.main import app  # noqa: E402
from app.observability.tracer import get_tracer  # noqa: E402
from app.security.audit import get_audit_logger  # noqa: E402
from app.security.rbac import set_current_user  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state():
    reset_repository()
    get_audit_logger().clear()
    get_tracer().clear()
    get_conversation_store().clear()
    fulfillment._graph = None
    set_current_user(User(id="anonymous", name="访客", role="guest"))
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def auth_header(client: TestClient, username: str = "张三") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": "123456"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.fixture
def customer_headers(client: TestClient) -> dict[str, str]:
    return auth_header(client, "张三")


@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    return auth_header(client, "管理员")


@pytest.fixture
def service_headers(client: TestClient) -> dict[str, str]:
    return auth_header(client, "王客服")
