"""评测体系 + Metrics / 可观测性回调测试。"""
from __future__ import annotations

import uuid

import pytest

from app.eval import (
    CaseDataset,
    EvalReport,
    Evaluator,
    GoldenCase,
    RegressionGate,
    ReplayRunner,
)
from app.observability.metrics import (
    Histogram,
    MetricRegistry,
    MetricsCollector,
    MetricsMiddleware,
    percentile,
)


# ------------------------------------------------------------------- dataset
def test_golden_case_dict_roundtrip():
    case = GoldenCase(
        id="c-1", name="推荐手机", input="有什么手机",
        expected={"contains": "手机"}, tags=["shopping", "smoke"],
        metadata={"owner": "qa"},
    )
    restored = GoldenCase.from_dict(case.to_dict())
    assert restored == case
    assert restored.tags == ["shopping", "smoke"]


def test_case_dataset_filter_by_tag():
    dataset = CaseDataset([
        GoldenCase("a", tags=["basic"]),
        GoldenCase("b", tags=["basic", "slow"]),
        GoldenCase("c", tags=["rag"]),
    ])
    assert [c.id for c in dataset.filter_by_tag("basic")] == ["a", "b"]
    assert [c.id for c in dataset.filter_by_tag(["rag", "slow"])] == ["b", "c"]


def test_case_dataset_json_roundtrip(tmp_path):
    dataset = CaseDataset([
        GoldenCase("a", "case a", "input", {"exact": "ok"}, ["basic"]),
        GoldenCase("b", "case b", {"q": "x"}, {"route_match": "order"}, ["router"]),
    ])
    text = dataset.to_json()
    restored = CaseDataset.from_json(text)
    assert len(restored) == 2
    assert restored.cases[1].expected == {"route_match": "order"}

    path = dataset.save(tmp_path / "golden.json")
    assert CaseDataset.load(path).to_dict() == restored.to_dict()


# ------------------------------------------------------------------- scorers
def test_exact_scorer():
    evaluator = Evaluator()
    assert evaluator.score("hello", {"exact": "hello"})[0] == 1.0
    assert evaluator.score({"answer": "hello"}, {"exact": "hello"})[0] == 1.0
    assert evaluator.score("hello!", {"exact": "hello"})[0] == 0.0


def test_contains_scorer():
    evaluator = Evaluator()
    assert evaluator.score("推荐 iPhone 手机", {"contains": "手机"})[0] == 1.0
    assert evaluator.score("推荐 iPhone", {"contains": ["iPhone", "手机"]})[0] == 0.0


def test_json_path_scorer():
    evaluator = Evaluator()
    actual = {"answer": "ok", "route": "shopping", "items": [{"id": "P1"}]}
    assert evaluator.score(
        actual, {"json_path": {"path": "$.route", "equals": "shopping"}}
    )[0] == 1.0
    assert evaluator.score(
        actual, {"json_path": ["$.items.0.id", "P1"]}
    )[0] == 1.0
    assert evaluator.score(
        actual, {"json_path": {"path": "$.route", "equals": "order"}}
    )[0] == 0.0


def test_route_match_scorer():
    evaluator = Evaluator()
    assert evaluator.score({"route": "order"}, {"route_match": "order"})[0] == 1.0
    assert evaluator.score({"route": "order"}, {"route_match": "shopping"})[0] == 0.0


def test_tool_called_scorer():
    evaluator = Evaluator()
    actual = {"tools_used": ["search_products", "check_inventory"]}
    assert evaluator.score(actual, {"tool_called": "search_products"})[0] == 1.0
    assert evaluator.score(
        actual, {"tool_called": ["search_products", "create_order"]}
    )[0] == 0.0


def test_answer_length_scorer():
    evaluator = Evaluator()
    assert evaluator.score("hello", {"answer_length": {"min": 3, "max": 10}})[0] == 1.0
    assert evaluator.score("hi", {"answer_length": {"min": 3, "max": 10}})[0] == 0.0
    assert evaluator.score("hello", {"answer_length": 3})[0] == 0.0


def test_custom_scorer():
    evaluator = Evaluator()
    evaluator.register_scorer(
        "starts_with", lambda actual, expected: 1.0 if str(actual).startswith(expected) else 0.0
    )
    assert evaluator.score("hello world", {"starts_with": "hello"})[0] == 1.0
    assert evaluator.score("world hello", {"starts_with": "hello"})[0] == 0.0


def test_multiple_expectations_are_composed():
    evaluator = Evaluator()
    score, detail = evaluator.score(
        {"answer": "有货", "route": "shopping", "tools_used": ["check_inventory"]},
        {"contains": "有货", "route_match": "shopping", "tool_called": "check_inventory"},
    )
    assert score == 1.0
    assert set(detail) == {"contains", "route_match", "tool_called"}


# ---------------------------------------------------------------- evaluator
async def _fixed_runner(case):
    return {
        "answer": "为你找到 iPhone 手机",
        "route": "shopping",
        "tools_used": ["search_products"],
        "latency_ms": 12.0,
    }


async def test_batch_evaluation_report():
    dataset = CaseDataset([
        GoldenCase("c1", "exact", "q", {"exact": "为你找到 iPhone 手机"}, ["basic"]),
        GoldenCase("c2", "route", "q", {"route_match": "shopping"}, ["router"]),
        GoldenCase("c3", "tool", "q", {"tool_called": "search_products"}, ["router"]),
        GoldenCase("c4", "fail", "q", {"route_match": "order"}, ["router"]),
    ])
    report = await Evaluator().evaluate(dataset, _fixed_runner)
    assert report.total == 4
    assert report.passed == 3
    assert report.pass_rate == pytest.approx(0.75)
    assert report.by_tag["router"]["pass_rate"] == pytest.approx(2 / 3, abs=1e-3)
    assert all(r.latency_ms == 12.0 for r in report.per_case)
    assert report.avg_latency_ms == pytest.approx(12.0)


async def test_evaluator_reports_runner_errors_without_crashing():
    async def broken(case):
        raise RuntimeError("runner down")

    dataset = CaseDataset([GoldenCase("c1", "bad", "q", {"exact": "x"})])
    report = await Evaluator().evaluate(dataset, broken)
    assert report.total == 1
    assert report.passed == 0
    assert "runner down" in report.per_case[0].error


async def test_evaluator_input_only_mode():
    async def echo(text):
        return text.upper()

    dataset = CaseDataset([
        GoldenCase("c1", "upper", "hello", {"exact": "HELLO"}),
    ])
    report = await Evaluator().evaluate(dataset, echo, input_only=True)
    assert report.passed == 1


# -------------------------------------------------------------------- replay
def _events(*tools):
    return [
        {
            "ts": float(i), "trace_id": "trace-r", "node": "agent",
            "event": "tool_result",
            "payload": {"tool": name, "content": name},
        }
        for i, name in enumerate(tools)
    ]


def test_replay_extracts_tool_sequence_from_tracer_events():
    runner = ReplayRunner()
    result = runner.replay(_events("search_products", "check_inventory"))
    assert result.trace_id == "trace-r"
    assert result.tool_sequence == ["search_products", "check_inventory"]
    assert [s.seq for s in result.steps] == [1, 2]


def test_replay_executes_registered_tools():
    runner = ReplayRunner({"search_products": lambda q="手机": f"found:{q}"})
    events = [{
        "ts": 1.0, "trace_id": "t", "node": "shopping", "event": "tool_result",
        "payload": {"tool": "search_products", "args": ["平板"], "content": "x"},
    }]
    result = runner.replay(events, execute=True)
    assert result.executions[0]["ok"] is True
    assert result.executions[0]["result"] == "found:平板"


def test_replay_diff_detects_order_change():
    runner = ReplayRunner()
    diff = runner.diff(_events("a", "b"), _events("b", "a"))
    assert diff["match"] is False
    assert diff["order_changed"] is True
    assert diff["missing"] == []
    assert diff["extra"] == []


def test_replay_diff_detects_content_change():
    runner = ReplayRunner()
    expected = _events("search")
    actual = _events("search")
    actual[0]["payload"]["content"] = "不同结果"
    diff = runner.diff(expected, actual)
    assert diff["match"] is False
    assert any(item["reason"] == "payload"
               for item in diff["content_mismatches"])


def test_replay_diff_matches_identical_traces():
    runner = ReplayRunner()
    assert runner.diff(_events("a", "b"), _events("a", "b"))["match"] is True


# -------------------------------------------------------------- regression
def _report(pass_rate, p95):
    return EvalReport(
        total=10, passed=int(pass_rate * 10), pass_rate=pass_rate,
        p95_latency_ms=p95, avg_latency_ms=p95 / 2,
    )


def test_regression_gate_passes_on_stable_report():
    gate = RegressionGate()
    result = gate.check(_report(1.0, 100.0), _report(1.0, 105.0))
    assert result.passed is True
    assert result.reasons == []


def test_regression_gate_fails_on_pass_rate_drop():
    gate = RegressionGate(pass_rate_drop_threshold=0.05)
    result = gate.check(_report(1.0, 100.0), _report(0.8, 100.0))
    assert result.passed is False
    assert any("通过率下降" in reason for reason in result.reasons)
    assert result.pass_rate_delta == pytest.approx(0.2)


def test_regression_gate_fails_on_p95_degradation():
    gate = RegressionGate(p95_degradation_threshold=0.2)
    result = gate.check(_report(1.0, 100.0), _report(1.0, 160.0))
    assert result.passed is False
    assert any("P95" in reason for reason in result.reasons)
    assert result.p95_delta_ratio == pytest.approx(0.6)


# ------------------------------------------------------------------ metrics
def test_counter_gauge_histogram_and_percentiles():
    registry = MetricRegistry()
    registry.increment("requests", 2, {"route": "shopping"})
    registry.increment("requests", 3, {"route": "shopping"})
    assert registry.counter("requests", {"route": "shopping"}).get() == 5

    registry.set_gauge("queue", 10)
    registry.gauge("queue").dec(3)
    assert registry.gauge("queue").get() == 7

    hist: Histogram = registry.histogram("latency")
    for value in range(1, 101):
        hist.observe(value)
    stats = hist.stats()
    assert stats["count"] == 100
    assert stats["sum"] == pytest.approx(5050.0)
    assert stats["p50"] == pytest.approx(50.5)
    assert stats["p95"] == pytest.approx(95.05)
    assert stats["p99"] == pytest.approx(99.01)
    assert percentile([], 0.95) == 0.0


def test_metric_registry_snapshot_includes_labels():
    registry = MetricRegistry()
    registry.increment("calls", 1, {"tool": "a", "ok": "true"})
    registry.increment("calls", 1, {"tool": "b", "ok": "false"})
    snapshot = registry.snapshot()
    keys = set(snapshot["counters"]["calls"])
    assert any("tool=a" in key for key in keys)
    assert any("tool=b" in key for key in keys)


def test_metrics_collector_snapshot_summary():
    collector = MetricsCollector()
    collector.record_agent_run("shopping", True, 20, 100, ["a", "b"])
    collector.record_agent_run("order", False, 80, 50, ["a"])
    collector.record_tool_call("a", True, 10)
    collector.record_tool_call("b", False, 30)
    collector.record_rag(3, 12, 0.85)

    summary = collector.snapshot()["summary"]
    assert summary["agent_runs"] == 2
    assert summary["success_rate"] == pytest.approx(0.5)
    assert summary["tool_error_rate"] == pytest.approx(0.5)
    assert summary["total_tokens"] == 150
    assert summary["agent_latency_ms"]["p95"] > 0
    assert collector.registry.gauge("rag_groundedness").get() == 0.85


class _FakeLLMResult:
    def __init__(self, tokens):
        self.llm_output = {"token_usage": {"total_tokens": tokens}}


def test_metrics_middleware_records_llm_callbacks():
    collector = MetricsCollector()
    middleware = MetricsMiddleware(collector)
    run_id = uuid.uuid4()
    middleware.on_llm_start({}, ["hello"], run_id=run_id,
                            metadata={"route": "shopping"})
    middleware.on_llm_end(_FakeLLMResult(42), run_id=run_id,
                          metadata={"route": "shopping"})
    summary = collector.snapshot()["summary"]
    assert summary["agent_runs"] == 1
    assert summary["success_rate"] == 1.0
    assert summary["total_tokens"] == 42
    assert summary["agent_latency_ms"]["count"] == 1


def test_metrics_middleware_records_tool_success_and_error():
    collector = MetricsCollector()
    middleware = MetricsMiddleware(collector)
    ok_id = uuid.uuid4()
    middleware.on_tool_start({"name": "search_products"}, "q", run_id=ok_id)
    middleware.on_tool_end([], run_id=ok_id)

    bad_id = uuid.uuid4()
    middleware.on_tool_start({"name": "create_order"}, {}, run_id=bad_id)
    middleware.on_tool_error(RuntimeError("denied"), run_id=bad_id)

    assert collector.registry.counter_total(
        "tool_calls_total", {"ok": "true"}
    ) == 1
    assert collector.registry.counter_total(
        "tool_calls_total", {"ok": "false"}
    ) == 1
