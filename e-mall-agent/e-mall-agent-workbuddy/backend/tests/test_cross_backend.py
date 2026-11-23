"""双后端一致性测试：同一契约分别请求 Python / Java 后端并比对业务语义。

默认两个后端都不在线时整体 skip，不破坏离线 pytest 基线。
启动方式：
    backend-python : http://127.0.0.1:8000
    backend-java   : http://127.0.0.1:8080
可通过 ECOM_PY_BACKEND_URL / ECOM_JAVA_BACKEND_URL 覆盖地址。
"""
from __future__ import annotations

import os

import httpx
import pytest

PY_URL = os.getenv("ECOM_PY_BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
JAVA_URL = os.getenv("ECOM_JAVA_BACKEND_URL", "http://127.0.0.1:8080").rstrip("/")
TIMEOUT = 6.0


def _healthy(base: str) -> bool:
    try:
        with httpx.Client(timeout=2.0) as client:
            return client.get(f"{base}/api/health").status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="module")
def backends():
    """只有两个后端都在线才执行一致性用例。"""
    if not (_healthy(PY_URL) and _healthy(JAVA_URL)):
        pytest.skip("双后端未同时在线：先启动 backend-python:8000 与 backend-java:8080")
    with httpx.Client(timeout=TIMEOUT) as client:
        yield {"python": PY_URL, "java": JAVA_URL}, client


def _login(client: httpx.Client, base: str, username: str = "张三") -> str:
    resp = client.post(f"{base}/api/auth/login", json={"username": username, "password": "123456"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data.get("token"), data
    return data["token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _get_products(client: httpx.Client, base: str, token: str) -> dict[str, dict]:
    resp = client.get(f"{base}/api/products", headers=_headers(token))
    assert resp.status_code == 200, resp.text
    items = resp.json()
    return {str(p["id"]): p for p in items}


def _chat(client: httpx.Client, base: str, token: str, message: str) -> str:
    resp = client.post(f"{base}/api/chat", json={"message": message}, headers=_headers(token))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return str(data.get("answer", ""))


# ---------- CONS-001 ~ CONS-003：认证与主数据 ----------

def test_cons001_login_shape(backends):
    _, client = backends
    results = {}
    for name, base in backends[0].items():
        resp = client.post(f"{base}/api/auth/login", json={"username": "张三", "password": "123456"})
        assert resp.status_code == 200, (name, resp.text)
        user = resp.json()["user"]
        results[name] = (user["id"], user["name"], user["role"])
    assert results["python"] == results["java"] == ("U001", "张三", "customer")


def test_cons002_catalog_matches(backends):
    _, client = backends
    catalogs = {}
    for name, base in backends[0].items():
        token = _login(client, base)
        catalogs[name] = _get_products(client, base, token)
    assert set(catalogs["python"]) == set(catalogs["java"])
    for pid in ("P001", "P005", "P007"):
        for name in catalogs:
            assert catalogs[name][pid]["price"] == catalogs["python"][pid]["price"]
            assert catalogs[name][pid]["stock"] == catalogs["python"][pid]["stock"]


def test_cons003_orders_isolated(backends):
    _, client = backends
    for name, base in backends[0].items():
        token = _login(client, base)
        resp = client.get(f"{base}/api/orders", headers=_headers(token))
        assert resp.status_code == 200, (name, resp.text)
        ids = {o["id"] for o in resp.json()}
        assert "O1001" in ids and "O1003" in ids and "O1002" not in ids


# ---------- CONS-004 ~ CONS-008：对话与业务动作 ----------

def test_cons004_product_recommendation(backends):
    _, client = backends
    for name, base in backends[0].items():
        token = _login(client, base)
        answer = _chat(client, base, token, "推荐降噪耳机")
        assert "P001" in answer or "耳机" in answer, (name, answer)


def test_cons005_my_orders(backends):
    _, client = backends
    for name, base in backends[0].items():
        token = _login(client, base)
        answer = _chat(client, base, token, "我的订单")
        assert "O1001" in answer, (name, answer)


def test_cons006_cross_customer_denied(backends):
    _, client = backends
    for name, base in backends[0].items():
        token = _login(client, base, username="李四")
        answer = _chat(client, base, token, "查 O1001 订单")
        assert any(k in answer for k in ("权限", "无权", "越权", "denied")) or \
            "denied" in answer.lower(), (name, answer)


def test_cons007_refund_status(backends):
    _, client = backends
    for name, base in backends[0].items():
        token = _login(client, base)
        _chat(client, base, token, "O1003 想退货退款")
        resp = client.get(f"{base}/api/orders", headers=_headers(token))
        statuses = {o["id"]: o["status"] for o in resp.json()}
        assert statuses.get("O1003") in ("refund_requested", "refunded"), (name, statuses)


def test_cons008_infra_health_shape(backends):
    _, client = backends
    for name, base in backends[0].items():
        resp = client.get(f"{base}/api/infra/health")
        assert resp.status_code == 200, (name, resp.text)
        components = resp.json().get("components", {})
        for key in ("mysql", "redis", "rabbitmq", "milvus", "llm"):
            assert key in components, (name, components)


# ---------- 契约健康度 ----------

def test_contract_health_endpoints(backends):
    _, client = backends
    for name, base in backends[0].items():
        resp = client.get(f"{base}/api/health")
        assert resp.status_code == 200, (name, resp.text)
        assert resp.json().get("status") in ("ok", "healthy")
