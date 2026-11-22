"""API 集成测试：认证、越权拦截、对话、SSE、商品订单、工作流与可观测性。"""
import json


def test_health_and_docs(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/openapi.json").status_code == 200


def test_login_success_and_failure(client):
    bad = client.post("/api/auth/login", json={"username": "张三", "password": "wrong"})
    assert bad.status_code == 401
    good = client.post("/api/auth/login", json={"username": "管理员", "password": "123456"})
    assert good.status_code == 200
    assert good.json()["role"] == "admin"
    assert "audit:read" in good.json()["permissions"]


def test_guest_cannot_read_orders(client):
    assert client.get("/api/orders").status_code == 403
    assert client.get("/api/audit").status_code == 403
    assert client.get("/api/traces").status_code == 403


def test_customer_order_scope(client, customer_headers):
    own = client.get("/api/orders", headers=customer_headers)
    assert own.status_code == 200
    assert {o["customer_id"] for o in own.json()} == {"U001"}
    assert client.get("/api/orders?customer_id=U002", headers=customer_headers).status_code == 403
    assert client.get("/api/orders/O1002", headers=customer_headers).status_code == 403


def test_service_can_cross_scope_but_not_manage_users(client, service_headers):
    assert client.get("/api/orders?customer_id=U002", headers=service_headers).status_code == 200
    assert client.get("/api/audit", headers=service_headers).status_code == 200
    refund = client.post("/api/orders/O1002/refund", headers=service_headers,
                         json={"reason": "客服协助退款"})
    assert refund.json()["status"] == "refund_requested"


def test_chat_and_stream(client, customer_headers):
    response = client.post("/api/chat", headers=customer_headers,
                           json={"message": "推荐降噪耳机", "thread_id": "api-t1"})
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "shopping"
    assert "P001" in body["answer"]
    assert body["context"]["sections"]

    stream = client.post("/api/chat/stream", headers=customer_headers,
                         json={"message": "我的订单", "thread_id": "api-t2"})
    assert stream.status_code == 200
    payload = stream.text
    assert "data: {" in payload
    events = [json.loads(line[6:]) for line in payload.splitlines() if line.startswith("data: {")]
    assert any(e["event"] == "route" for e in events)
    assert any(e["event"] == "done" for e in events)


def test_products_and_order_creation(client, customer_headers):
    products = client.get("/api/products?query=耳机", headers=customer_headers).json()
    assert products[0]["id"] == "P001"
    created = client.post("/api/orders", headers=customer_headers,
                          json={"items": [{"product_id": "P008", "quantity": 2}]})
    assert created.status_code == 201
    assert created.json()["total"] == 258.0
    refund = client.post(f"/api/orders/{created.json()['id']}/refund",
                         headers=customer_headers, json={"reason": "测试退款"})
    assert refund.json()["status"] == "refund_requested"


def test_workflow_api_with_approval(client, admin_headers):
    started = client.post("/api/workflows/fulfillment/run", headers=admin_headers,
                          json={"order_id": "O1001", "thread_id": "api-wf"})
    assert started.json()["status"] == "awaiting_approval"
    done = client.post("/api/workflows/fulfillment/resume", headers=admin_headers,
                       json={"thread_id": "api-wf", "approved": True})
    assert done.json()["status"] == "completed"


def test_context_preview_rag_and_graphs(client, customer_headers):
    preview = client.get("/api/context/preview?message=推荐耳机", headers=customer_headers).json()
    assert preview["snapshot"]["total_chars"] > 0
    assert len(preview["messages"]) == 2
    assert client.get("/api/rag/search?q=退货").json()
    graphs = client.get("/api/graphs").json()
    assert set(graphs) == {"supervisor", "fulfillment"}
