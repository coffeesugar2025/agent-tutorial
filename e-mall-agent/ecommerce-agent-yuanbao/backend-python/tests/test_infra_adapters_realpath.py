"""第三轮复盘新增：适配器不是「有降级就算接了」，验证真调用路径与掉线回退。"""
from __future__ import annotations

import app.infra.adapters as A


def test_relational_execute_and_query_roundtrip():
    A.DB.execute("INSERT OR REPLACE INTO sessions(thread_id,user_id,tenant_id,state_json) VALUES (?,?,?,?)",
                 ("t_adapter", "u1", "t_default", "{}"))
    rows = A.DB.query("SELECT * FROM sessions WHERE thread_id=?", ("t_adapter",))
    assert rows and rows[0]["thread_id"] == "t_adapter"


def test_relational_placeholder_conversion():
    sql, bound = A.DB._to_named("SELECT * FROM t WHERE a=? AND b=?", (1, "x"))
    assert sql == "SELECT * FROM t WHERE a=:p0 AND b=:p1"
    assert bound == {"p0": 1, "p1": "x"}


def test_relational_placeholder_arity_guard():
    import pytest
    with pytest.raises(ValueError):
        A.DB._to_named("SELECT ?", ())


def test_relational_stats_does_not_claim_mysql_without_engine():
    st = A.DB.stats()
    assert st["backend"] == "sqlite-fallback"
    assert st["mysql_engine_configured"] is False


def test_kv_roundtrip_and_incr():
    A.KV.set("k_adapter", {"a": 1}, 60)
    assert A.KV.get("k_adapter") == {"a": 1}
    n1, n2 = A.KV.incr("n_adapter"), A.KV.incr("n_adapter")
    assert n2 == n1 + 1


def test_kv_runtime_drop_falls_back(monkeypatch):
    """运行中 Redis 掉线：set/get 直接切内存，不抛异常。"""
    class DeadRedis:
        def setex(self, *a): raise ConnectionError("down")
        def get(self, *a): raise ConnectionError("down")
    original = A.KV._redis
    A.KV._redis = DeadRedis()
    try:
        A.KV.set("k_drop", "v", 60)
        assert A.KV.get("k_drop") == "v"
        assert A.KV.active_backend == "memory-fallback"
    finally:
        A.KV._redis = original


def test_bus_publish_consume_with_inproc_backend():
    r = A.BUS.publish("task.start", {"task_id": "adapter-1"})
    assert r["published"] is True
    assert A.BUS.consume("task.#")


def test_bus_runtime_drop_falls_back(monkeypatch):
    class DeadConn:
        pass
    class DeadCh:
        def basic_publish(self, *a, **k): raise ConnectionError("down")
    original_conn, original_ch = A.BUS._conn, getattr(A.BUS, "_ch", None)
    A.BUS._conn, A.BUS._ch = DeadConn(), DeadCh()
    try:
        r = A.BUS.publish("audit.call", {"trace_id": "drop"})
        assert r["published"] is True
        assert r["backend"] == "inproc-fallback"
    finally:
        A.BUS._conn, A.BUS._ch = original_conn, original_ch


def test_milvus_stats_reports_active_backend_and_error_field():
    st = A.VECTOR.stats()
    assert st["backend"] == "local-fallback"
    assert "last_error" in st


def test_infra_report_has_four_backends():
    r = A.infra_report()
    assert all(k in r for k in ("milvus", "mysql", "redis", "rabbitmq"))
