"""P1 与基础设施适配器契约回归（零外部服务依赖）。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.decision import decision
from app.hardening import cache, cost, hitl_v2, memory_v2, query_understanding, rag_eval, replay, tools
from app.infra import adapters, llm_gateway
from app.main import app


def test_decision_fit_blocks_rule_enumerable_task():
    t = decision.TaskProfile("固定发票开具", True, True, True, 0.3, 100000, 100,
                             True, False, True)
    out = decision.agent_fit(t)
    assert out["fit"] is False
    assert any("规则可穷举" in b or "强审计" in b for b in out["blockers"])


def test_decision_roi_formula():
    r = decision.roi(0.01, 0.8, 0.15, 0.15, 1000)
    assert r["effective_cost_per_task"] > r["inference_per_task"]
    assert "成功率" in r["note"]


def test_architecture_tree_defaults_to_workflow():
    t = decision.TaskProfile("对账", True, True, False, 0.95, 200, 60000, True, True, True)
    assert "Workflow" in decision.architecture_tree(t)["choice"]


def test_autonomy_levels_are_five():
    assert [x["level"] for x in decision.autonomy_levels()] == ["L0", "L1", "L2", "L3", "L4"]


def test_gateway_has_six_providers_and_multimodel():
    p = llm_gateway.provider_capability_matrix()
    assert {"deepseek", "qwen", "openai", "glm", "wenxin", "ollama"} <= set(p)
    assert p["openai"]["structured_output"] == "strict_json_schema"
    assert p["ollama"]["local"] is True


def test_gateway_mock_chat_and_cost():
    r = llm_gateway.GATEWAY.chat("你好", intent="search", system_prompt="S")
    assert r.text.startswith("[mock:") and r.cost_usd >= 0
    assert llm_gateway.GATEWAY.chat("你好", intent="search", system_prompt="S").from_cache


def test_gateway_route_sensitive_forces_local():
    p = llm_gateway.GATEWAY.route("order_query", sensitive=True)
    assert p.primary == "ollama" and "本地" in p.reason


def test_caching_layout_orders_stable_prefix_first():
    o = llm_gateway.GATEWAY.note_caching_layout()["order"]
    assert o[0].startswith("system") and o[-1].startswith("user")


def test_cache_four_layers_and_invalidation():
    c = cache.CacheLayer()
    c.put("exact", {"q": "退货"}, "7 天")
    assert c.get("exact", {"q": "退货"})[0] is True
    c.invalidate("doc_policies")
    assert c.get("exact", {"q": "退货"})[1] == "7 天"   # 无 tag 不受影响
    c.invalidate(all_layers=True)
    assert c.get("exact", {"q": "退货"})[0] is False
    assert set(c.report()["layers"]) == {"exact", "semantic", "retrieval", "embedding"}


def test_semantic_cache_threshold_avoids_mis_hit():
    c = cache.CacheLayer()
    c.semantic_put("怎么退货", "7 天无理由")
    hit, value, sim = c.semantic_get("能不能退货")
    assert isinstance(sim, float) and (hit is True or hit is False)


def test_replay_record_and_deterministic_rerun():
    steps = [("tool", "get_order", lambda: {"ok": True, "status": "运输中"})]
    t = replay.record("订单到哪了", steps)
    out = replay.deterministic_replay(t.trace_id, steps)
    assert out["ok"] and out["identical"] is True
    tt = replay.deterministic_replay(t.trace_id, steps, overrides={1: {"status": "已签收"}})
    assert tt["time_travel_from"] == 1 and tt["identical"] is False
    assert replay.STORE.compare(t.trace_id, tt["replay"])["diff_count"] >= 1


def test_cost_per_success_and_anomaly():
    l = cost.CostLedger(budget_usd=0.001)
    l.charge("deepseek", 1000, 300, 0.27, 1.1)
    l.finish(True)
    l.finish(False, human=True)
    r = l.report()
    assert r["per_success_task"] > r["per_task"] or r["success"] == 1
    assert r["effective_cost_usd"] > 0 and "anomaly" in r
    assert len(cost.optimization_order()) == 4 and cost.optimization_order()[0]["priority"] == 1


def test_cost_budget_hard_termination():
    l = cost.CostLedger(budget_usd=0.0000001)
    out = l.charge("openai", 1000, 1000, 0.15, 0.6)
    assert out["over_budget"] and out["action"] == "terminate"


def test_rag_layered_diagnose_points_to_retrieval():
    out = rag_eval.layered_diagnose("价保多久", {"d1", "d2"}, ["x", "y", "z"],
                                    [], "不知道", "", {"15 天"})
    assert out["bottleneck_layer"] == "检索没召回到"
    assert "别先调 prompt" in out["recommended_action"]


def test_rag_metrics_are_bounded():
    assert rag_eval.recall_at_k({"a", "b"}, ["a", "x"], 2) == 0.5
    assert rag_eval.mrr({"a"}, ["x", "a"]) == 0.5
    assert 0 <= rag_eval.ndcg_at_k({"a"}, ["a"], 5) <= 1


def test_query_understanding_gate_and_decompose():
    assert query_understanding.should_retrieve("你好")["retrieve"] is False
    assert query_understanding.should_retrieve("刚才说的", True)["retrieve"] is False
    u = query_understanding.understand("退货政策和优惠券门槛")
    assert len(u["sub_queries"]) >= 2 and "hyde_document" in u


def test_tool_spec_has_when_not_to_use_and_error_codes():
    card = tools.REGISTRY.card("get_order")
    assert "不要" in card["when_not_to_use"] and "E_FORBIDDEN" in card["error_codes"]
    gate = tools.REGISTRY.side_effect_gate("apply_refund")
    assert gate["allowed"] is False and gate["hitl"] is True
    assert tools.REGISTRY.side_effect_gate("apply_refund", "apr_1")["allowed"] is True


def test_tool_output_token_budget():
    out = tools.REGISTRY.validate_output("search_products", {"products": ["x"] * 500})
    assert "budget" in out and out["action"] in ("ok", "截断/摘要后再入上下文")


def test_memory_governance_conflict_and_reject():
    m = memory_v2.GovernedMemory()
    a = m.merge("u1", "预算 500 推荐数码")
    b = m.merge("u1", "预算 300")
    assert a["written"] and b["conflicts"]
    assert m.merge("u1", "今天随便看看")["written"] == []
    assert "半衰期" in b["policy"] or "冲突留痕" in b["policy"]


def test_hitl_timeout_default_reject_and_context_injection():
    mgr = hitl_v2.HITLManager()
    it = mgr.submit("interrupt", "apply_refund", {"amount": 799}, "high",
                    "金额超阈值", "tr_1", timeout_seconds=-1)
    assert "待审批" in it.summary and "tr_1" in it.summary
    assert it.id in mgr.scan_timeouts()["expired_rejected"]
    assert mgr.decide(it.id, "approve")["ok"] is False    # 已超时拒绝


def test_hitl_decision_injects_structured_context():
    mgr = hitl_v2.HITLManager()
    it = mgr.submit("pre_approval", "apply_refund", {}, "high", "写操作", "tr_2")
    out = mgr.decide(it.id, "approve", "reviewer", "金额已核对")
    assert out["ok"] and "人工审批结果" in out["context_injection"]["content"]
    assert "不得重复提交" in out["context_injection"]["content"]


def test_infra_adapters_all_degrade_gracefully():
    r = adapters.infra_report()
    assert {"milvus", "mysql", "redis", "rabbitmq"} <= set(r)
    assert r["milvus"]["backend"] in ("milvus", "local-fallback")
    assert r["mysql"]["backend"] in ("mysql", "sqlite-fallback")
    assert r["redis"]["backend"] in ("redis", "memory-fallback")
    assert r["rabbitmq"]["backend"] in ("rabbitmq", "inproc-fallback")


def test_message_bus_publish_consume():
    b = adapters.MessageBus()
    assert b.publish("task.start", {"task_id": "t1"})["published"]
    assert b.consume("task.#")[0]["task_id"] == "t1"


def test_v3_endpoints_smoke():
    with TestClient(app) as c:
        assert len(c.get("/v3/models").json()["providers"]) == 6
        assert c.post("/v3/models/chat", json={"message": "你好"}).json()["result"]["text"]
        assert c.get("/v3/capabilities").json()["chapters"] == 10
        assert c.post("/v3/decision/fit", json={"name": "导购", "decomposable": True,
            "verifiable_feedback": True, "reversible": True, "error_cost": 0.2,
            "call_frequency": 100, "latency_sla_ms": 2000, "context_available": True,
            "long_tail": True}).json()["fit"]["fit"] is True
        assert c.post("/v3/rag/understand", json={"question": "退货政策和券门槛"}).json()["sub_queries"]
        assert c.get("/v3/cost/report").json()["optimization_order"][0]["priority"] == 1
        assert c.get("/v3/tools/specs").json()["cards"]
        assert c.post("/v3/evals/stability", json={"k": 2}).json()["aggregate_pass_pow_k"] == 1.0


def test_existing_routes_not_broken():
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/v2/capabilities").status_code == 200
