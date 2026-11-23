"""基础设施适配器与多模型网关测试。

全部本地确定性：不连接 MySQL/Redis/RabbitMQ/Milvus，也不调用真实大模型。
"""
from __future__ import annotations

import json

import pytest

from app.api import infra as infra_api
from app.infra import (
    SCHEMA_SQL,
    InfraHealth,
    InfraSettings,
    LLMGateway,
    MilvusVectorStore,
    MySQLRepository,
    RabbitMQEventBus,
    RedisCache,
)
from app.llm.factory import RuleBasedChatModel

_ENV_KEYS = (
    "ECOM_MYSQL_URL", "ECOM_REDIS_URL", "ECOM_RABBITMQ_URL", "ECOM_MILVUS_URL",
    "ECOM_MILVUS_TOKEN", "ECOM_LLM_PROVIDERS", "ECOM_LLM_DEFAULT_PROVIDER",
    "ECOM_DEEPSEEK_API_KEY", "ECOM_QWEN_API_KEY",
    "ECOM_DEEPSEEK_BASE_URL", "ECOM_QWEN_BASE_URL",
)


@pytest.fixture(autouse=True)
def clean_infra_singletons():
    """隔离 API 模块级单例的内存状态，避免用例间相互污染。"""
    def _reset() -> None:
        infra_api._cache._local.clear()
        infra_api._event_bus._queues.clear()
        infra_api._event_bus._published.clear()

    _reset()
    yield
    _reset()


# ---------- 配置解析 ----------
def test_settings_defaults(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    cfg = InfraSettings.from_env()
    assert (cfg.mysql_url, cfg.redis_url, cfg.rabbitmq_url, cfg.milvus_url) == ("", "", "", "")
    assert cfg.milvus_token == ""
    assert cfg.llm_providers == "offline"
    assert cfg.llm_default_provider == "offline"
    assert cfg.deepseek_api_key == "" and cfg.qwen_api_key == ""
    assert cfg.deepseek_base_url == "https://api.deepseek.com/v1"
    assert cfg.qwen_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert cfg.provider_names == ["offline"]


def test_settings_from_env(monkeypatch):
    values = {
        "ECOM_MYSQL_URL": "mysql://u:p@db:3306/ecom",
        "ECOM_REDIS_URL": "redis://cache:6379/0",
        "ECOM_RABBITMQ_URL": "amqp://guest:guest@mq:5672/",
        "ECOM_MILVUS_URL": "http://milvus:19530",
        "ECOM_MILVUS_TOKEN": "token-xyz",
        "ECOM_LLM_PROVIDERS": "offline,deepseek",
        "ECOM_LLM_DEFAULT_PROVIDER": "deepseek",
        "ECOM_DEEPSEEK_API_KEY": "sk-deepseek",
        "ECOM_QWEN_API_KEY": "sk-qwen",
        "ECOM_DEEPSEEK_BASE_URL": "https://ds.example/v1",
        "ECOM_QWEN_BASE_URL": "https://qwen.example/v1",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    cfg = InfraSettings.from_env()
    assert cfg.mysql_url == values["ECOM_MYSQL_URL"]
    assert cfg.redis_url == values["ECOM_REDIS_URL"]
    assert cfg.rabbitmq_url == values["ECOM_RABBITMQ_URL"]
    assert cfg.milvus_url == values["ECOM_MILVUS_URL"]
    assert cfg.milvus_token == values["ECOM_MILVUS_TOKEN"]
    assert cfg.llm_providers == values["ECOM_LLM_PROVIDERS"]
    assert cfg.llm_default_provider == values["ECOM_LLM_DEFAULT_PROVIDER"]
    assert cfg.deepseek_api_key == values["ECOM_DEEPSEEK_API_KEY"]
    assert cfg.qwen_api_key == values["ECOM_QWEN_API_KEY"]
    assert cfg.deepseek_base_url == values["ECOM_DEEPSEEK_BASE_URL"]
    assert cfg.qwen_base_url == values["ECOM_QWEN_BASE_URL"]


def test_provider_names_parsing(monkeypatch):
    monkeypatch.setenv("ECOM_LLM_PROVIDERS", " deepseek, qwen, deepseek, , OFFLINE ")
    assert InfraSettings.from_env().provider_names == ["deepseek", "qwen", "offline"]
    monkeypatch.setenv("ECOM_LLM_PROVIDERS", "  ")
    assert InfraSettings.from_env().provider_names == ["offline"]


# ---------- Redis 回退 ----------
def test_redis_fallback_get_set():
    cache = RedisCache()
    assert cache.status()["backend"] == "memory"
    cache.set("greeting", "你好")
    assert cache.get("greeting") == "你好"
    assert cache.get("missing") is None


def test_redis_fallback_ttl():
    cache = RedisCache()
    cache.set("alive", "ok", ttl=60)
    cache.set("expired", "gone", ttl=-1)
    assert cache.get("alive") == "ok"
    assert cache.get("expired") is None


def test_redis_delete_and_incr():
    cache = RedisCache()
    cache.set("counter", 5)
    assert cache.incr("counter") == 6
    assert cache.incr("counter", 4) == 10
    assert cache.delete("counter") is True
    assert cache.get("counter") is None
    assert cache.delete("counter") is False


def test_redis_status_not_configured():
    status = RedisCache().status()
    assert status["configured"] is False
    assert status["active"] is False
    assert status["backend"] == "memory"
    assert "not_configured" in status["detail"]


def test_redis_configured_without_driver(monkeypatch):
    monkeypatch.setenv("ECOM_REDIS_URL", "redis://localhost:6379/0")
    status = RedisCache().status()
    assert status["configured"] is True
    assert status["active"] is False
    assert "缺少 redis 驱动" in status["detail"]


# ---------- RabbitMQ 回退 ----------
def test_rabbitmq_publish_events_and_drain():
    bus = RabbitMQEventBus()
    bus.publish("order.created", {"id": "O1001"})
    assert bus.events("order.created") == [("order.created", {"id": "O1001"})]
    assert bus.drain("order.created") == [{"id": "O1001"}]
    assert bus.drain("order.created") == []
    assert len(bus.events()) == 1  # drain 只消费队列，不清空已发布清单


def test_rabbitmq_topic_isolation():
    bus = RabbitMQEventBus()
    bus.publish("topic.a", 1)
    bus.publish("topic.b", 2)
    assert bus.drain("topic.a") == [1]
    assert bus.drain("topic.b") == [2]
    assert len(bus.events()) == 2


def test_rabbitmq_status_not_configured():
    status = RabbitMQEventBus().status()
    assert status["configured"] is False
    assert status["backend"] == "memory"
    assert "not_configured" in status["detail"]


# ---------- Milvus 回退 ----------
def test_milvus_fallback_add_and_search():
    store = MilvusVectorStore()
    store.add_texts(
        ["七天无理由退货政策说明", "数码类商品整机保修十二个月"],
        metadatas=[{"source": "售后政策"}, {"source": "质保规则"}],
    )
    results = store.similarity_search("退货政策", k=2)
    assert len(results) == 2
    assert any("退货" in doc.page_content for doc in results)
    assert all(doc.metadata.get("source") for doc in results)


def test_milvus_status_not_configured():
    status = MilvusVectorStore().status()
    assert status["configured"] is False
    assert status["active"] is False
    assert status["backend"] == "memory"
    assert "not_configured" in status["detail"]


# ---------- MySQL 回退 ----------
def test_mysql_not_configured_status():
    status = MySQLRepository().status()
    assert status["configured"] is False
    assert status["active"] is False
    assert status["backend"] == "memory"
    assert "not_configured" in status["detail"]


def test_mysql_configured_without_driver(monkeypatch):
    monkeypatch.setenv("ECOM_MYSQL_URL", "mysql://root:pwd@127.0.0.1:3306/ecom")
    status = MySQLRepository().status()
    assert status["configured"] is True
    assert status["active"] is False
    assert "缺少 pymysql" in status["detail"]


def test_mysql_fallback_repository_api():
    repo = MySQLRepository()
    assert repo.authenticate("张三", "123456").id == "U001"
    assert repo.get_product("P001").name == "无线降噪耳机 Pro"
    assert repo.get_inventory("P007")["available"] is False
    assert repo.decrease_stock("P008", 1) is True
    order = repo.create_order("U001", [{"product_id": "P008", "quantity": 2}])
    assert order.total == 258.0
    assert repo.get_order(order.id).id == order.id
    assert repo.set_order_status(order.id, "paid").status == "paid"
    assert repo.request_refund(order.id, "不想要了").status == "refund_requested"
    assert len(repo.list_orders("U001")) >= 3
    assert repo.get_user("U404") is None


def test_mysql_schema_sql_contains_tables_and_seed():
    for table in ("users", "products", "orders", "order_items"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in SCHEMA_SQL
    for table in ("users", "products", "orders", "order_items"):
        assert f"INSERT IGNORE INTO {table}" in SCHEMA_SQL


# ---------- 多模型网关 ----------
def test_gateway_default_provider_list(monkeypatch):
    monkeypatch.delenv("ECOM_LLM_PROVIDERS", raising=False)
    gateway = LLMGateway()
    assert [p.name for p in gateway.list_providers()] == ["offline"]
    assert gateway.default_provider == "offline"
    assert isinstance(gateway.create_chat_model(), RuleBasedChatModel)


def test_gateway_multi_provider_list(monkeypatch):
    monkeypatch.setenv("ECOM_LLM_PROVIDERS", "offline,deepseek,qwen")
    monkeypatch.setenv("ECOM_LLM_DEFAULT_PROVIDER", "deepseek")
    gateway = LLMGateway()
    assert [p.name for p in gateway.list_providers()] == ["offline", "deepseek", "qwen"]
    assert gateway.default_provider == "deepseek"
    deepseek = gateway.get_provider("deepseek")
    assert deepseek.model == "deepseek-chat"
    assert deepseek.base_url == "https://api.deepseek.com/v1"
    qwen = gateway.get_provider("qwen")
    assert qwen.model == "qwen-plus"
    assert qwen.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_gateway_unknown_provider():
    gateway = LLMGateway()
    assert gateway.get_provider("missing") is None
    with pytest.raises(KeyError):
        gateway.create_chat_model("missing")


def test_gateway_fallback_reason_without_key(monkeypatch):
    monkeypatch.setenv("ECOM_LLM_PROVIDERS", "deepseek,qwen")
    monkeypatch.setenv("ECOM_DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("ECOM_QWEN_API_KEY", "")
    gateway = LLMGateway()
    assert isinstance(gateway.create_chat_model("deepseek"), RuleBasedChatModel)
    status = gateway.status()
    reasons = [item["fallback_reason"] for item in status["providers"]]
    assert any(reason and "API key 未配置" in reason for reason in reasons)
    assert status["active"] is False
    assert status["backend"] == "offline"
    assert "回退" in status["detail"]


def test_gateway_fallback_without_sdk(monkeypatch):
    monkeypatch.setenv("ECOM_LLM_PROVIDERS", "deepseek")
    monkeypatch.setenv("ECOM_DEEPSEEK_API_KEY", "sk-test")
    gateway = LLMGateway()
    assert isinstance(gateway.create_chat_model("deepseek"), RuleBasedChatModel)
    assert "缺少 langchain-openai" in gateway.status()["detail"]


def test_gateway_provider_dict_masks_api_key(monkeypatch):
    monkeypatch.setenv("ECOM_LLM_PROVIDERS", "deepseek")
    monkeypatch.setenv("ECOM_DEEPSEEK_API_KEY", "sk-secret-123")
    data = LLMGateway().get_provider("deepseek").as_dict()
    assert data["api_key_set"] is True
    assert "sk-secret-123" not in json.dumps(data, ensure_ascii=False)


# ---------- 健康聚合 ----------
def test_infra_health_aggregation():
    report = InfraHealth().check()
    assert report["status"] == "ok"
    assert set(report["components"]) == {"mysql", "redis", "rabbitmq", "milvus", "llm"}
    for name, status in report["components"].items():
        for key in ("configured", "active", "backend", "detail"):
            assert key in status, name
        assert isinstance(status["configured"], bool)
        assert isinstance(status["active"], bool)


def test_infra_health_with_custom_components():
    class Stub:
        def status(self) -> dict:
            return {"configured": True, "active": True, "backend": "stub", "detail": "ok"}

    report = InfraHealth(components={"stub": Stub()}).check()
    assert report["configured_count"] == 1
    assert report["active_count"] == 1
    assert report["components"]["stub"]["backend"] == "stub"
    assert InfraHealth(components={"stub": Stub()}).as_dict() == report


# ---------- API 冒烟 ----------
def test_api_infra_health_is_public(client):
    response = client.get("/api/infra/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "mysql" in body["components"]


def test_api_providers_permissions_and_payload(client, admin_headers):
    assert client.get("/api/infra/providers").status_code == 200  # chat:use
    body = client.get("/api/infra/providers", headers=admin_headers).json()
    assert body["default"] == "offline"
    assert body["providers"][0]["name"] == "offline"
    assert "api_key_set" in body["providers"][0]
    assert "sk-" not in json.dumps(body, ensure_ascii=False)


def test_api_events_require_admin(client, customer_headers, admin_headers):
    denied = client.post("/api/infra/events", headers=customer_headers,
                         json={"topic": "order.created", "payload": {"id": "O1"}})
    assert denied.status_code == 403
    ok = client.post("/api/infra/events", headers=admin_headers,
                     json={"topic": "order.created", "payload": {"id": "O1001"}})
    assert ok.status_code == 200
    assert ok.json()["published"] is True
    assert ok.json()["backend"] == "memory"
    assert any(topic == "order.created" for topic, _ in infra_api._event_bus.events())


def test_api_cache_round_trip(client, service_headers, customer_headers):
    assert client.get("/api/infra/cache/k", headers=customer_headers).status_code == 403
    stored = client.post("/api/infra/cache", headers=service_headers,
                         json={"key": "k", "value": {"v": 1}, "ttl": 60})
    assert stored.status_code == 200
    assert stored.json()["stored"] is True
    read = client.get("/api/infra/cache/k", headers=service_headers)
    assert read.status_code == 200
    assert read.json()["value"] == {"v": 1}
    assert read.json()["backend"] == "memory"


def test_openapi_exposes_infra_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/api/infra/health", "/api/infra/providers", "/api/infra/events",
                 "/api/infra/cache/{key}", "/api/infra/cache"):
        assert path in paths
