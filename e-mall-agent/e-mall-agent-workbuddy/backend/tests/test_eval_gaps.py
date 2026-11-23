"""评测体系缺口测试：LLM-as-Judge、轨迹评测、错误归因、A-B 实验与导入回归。"""
from __future__ import annotations

import pytest

from app.eval import CaseDataset, EvalReport, Evaluator, GoldenCase
from app.eval.attribution import (
    Annotation,
    AttributionResult,
    ErrorCategory,
    FeedbackLoop,
    classify_error,
)
from app.eval.evaluator import EvalCaseResult
from app.eval.experiment import Experiment, ExperimentRunner, significance_test
from app.eval.judge import (
    JudgeAgreement,
    JudgeConfig,
    LLMJudgeScorer,
    default_judge,
    judge_consistency,
    register as register_judge,
)
from app.eval.trajectory import (
    TrajectoryScorer,
    get_trajectory,
    register as register_trajectory,
    trajectory_expectation,
    trajectory_score,
    with_trajectory,
)


def _events(*tools):
    return [
        {"ts": float(i), "trace_id": "t", "node": "agent",
         "event": "tool_result", "payload": {"tool": name, "content": name}}
        for i, name in enumerate(tools)
    ]


# ------------------------------------------------------------- LLM-as-Judge
def test_default_judge_is_deterministic_keyword_coverage():
    rubric = "回答需包含订单号和手机号"
    assert default_judge("订单号 A100，手机号 13800138000", rubric) == pytest.approx(1.0)
    assert default_judge("今天天气不错", rubric) == pytest.approx(0.0)
    # 同一输入输出恒定
    assert default_judge("订单号 A100", rubric) == default_judge("订单号 A100", rubric)


def test_judge_config_injected_model_and_score_range():
    config = JudgeConfig(rubric="rubric", min_score=0.0, max_score=5.0,
                         judge=lambda answer, rubric: 4.0)
    assert LLMJudgeScorer(config)("任意答案") == pytest.approx(0.8)

    model_config = JudgeConfig(rubric="rubric", model=lambda answer, rubric: 1.0)
    assert LLMJudgeScorer(model_config)("任意答案") == pytest.approx(1.0)

    with pytest.raises(ValueError):
        JudgeConfig(rubric="rubric", min_score=2.0, max_score=1.0)


def test_judge_registers_into_existing_evaluator():
    evaluator = Evaluator()
    scorer = register_judge(
        evaluator,
        config=JudgeConfig(rubric="rubric", judge=lambda answer, rubric: 0.9),
    )
    assert isinstance(scorer, LLMJudgeScorer)
    score, detail = evaluator.score({"answer": "答案"}, {"llm_judge": "rubric"})
    assert score == pytest.approx(0.9)
    assert "llm_judge" in detail

    # 也支持 {"type": ...} 形式
    assert evaluator.score("答案", {"type": "llm_judge", "value": "r"})[0] == pytest.approx(0.9)


def test_judge_consistency_pearson_and_agreement():
    perfect = judge_consistency([1.0, 0.8, 0.6, 0.4], [1.0, 0.8, 0.6, 0.4])
    assert isinstance(perfect, JudgeAgreement)
    assert perfect.n == 4
    assert perfect.pearson == pytest.approx(1.0)
    assert perfect.agreement == pytest.approx(1.0)
    assert float(perfect) == pytest.approx(1.0)

    inverse = judge_consistency([1.0, 2.0, 3.0], [3.0, 2.0, 1.0])
    assert inverse.pearson == pytest.approx(-1.0)
    assert inverse.agreement == pytest.approx(1 / 3)

    with pytest.raises(ValueError):
        judge_consistency([1.0], [1.0, 2.0])


# ---------------------------------------------------------------- 轨迹评测
def test_trajectory_score_exact_partial_and_diff_detail():
    assert trajectory_score(_events("search", "buy"), ["search", "buy"]) == 1.0
    assert trajectory_score(["a", "b"], ["b", "a"]) == pytest.approx(0.5)
    assert trajectory_score(["a"], ["a", "b"]) == pytest.approx(0.5)

    result = TrajectoryScorer().score(["a"], ["a", "b"])
    assert result.match is False
    assert result.detail["missing"] == ["b"]
    assert result.detail["order_changed"] is False
    assert result.as_dict()["score"] == pytest.approx(0.5)


def test_with_trajectory_preserves_case_and_registers_scorer():
    case = GoldenCase("c1", "购物", "找手机", {"exact": "手机"}, ["basic"],
                      {"owner": "qa"})
    enhanced = with_trajectory(case, ["search_products", "check_inventory"])
    assert case.metadata == {"owner": "qa"}  # 原 case 未被修改
    assert enhanced.id == case.id and enhanced.expected == case.expected
    assert get_trajectory(enhanced) == ["search_products", "check_inventory"]
    assert get_trajectory(GoldenCase.from_dict(enhanced.to_dict())) == [
        "search_products", "check_inventory"
    ]

    evaluator = Evaluator()
    register_trajectory(evaluator)
    actual = _events("search_products", "check_inventory")
    assert evaluator.score(actual, trajectory_expectation(enhanced))[0] == 1.0
    assert evaluator.score(_events("search_products"), trajectory_expectation(enhanced))[0] == pytest.approx(0.5)


# ------------------------------------------------------------ 错误归因闭环
def test_error_category_and_default_classification():
    assert {c.value for c in ErrorCategory} == {
        "retrieval", "planning", "tool", "generation", "permission", "config"
    }

    permission = EvalCaseResult("c", "", 0.0, False, 1.0,
                                error="403 permission denied")
    assert classify_error(GoldenCase("c"), permission).category == ErrorCategory.PERMISSION

    bad_tool = EvalCaseResult("c", "", 0.0, False, 1.0,
                              detail={"tool_called": 0.0})
    assert classify_error(GoldenCase("c"), bad_tool).category == ErrorCategory.TOOL

    wrong_route = EvalCaseResult("c", "", 0.0, False, 1.0,
                                 detail={"route_match": 0.0})
    assert classify_error(GoldenCase("c"), wrong_route).category == ErrorCategory.PLANNING


def test_injected_rule_and_feedback_loop_full_flow():
    case = GoldenCase("bad-1", "失败用例", "问题", {"exact": "旧期望"}, ["shopping"])
    custom = lambda c, r, t: AttributionResult(  # noqa: E731
        ErrorCategory.RETRIEVAL, reason="人工规则命中"
    )
    attributed = classify_error(case, None, [], rules=[custom])
    assert attributed.category == ErrorCategory.RETRIEVAL
    assert attributed.reason == "人工规则命中"

    loop = FeedbackLoop()
    bad = loop.submit_bad_case(case, EvalCaseResult("bad-1", "", 0.0, False, 1.0,
                                                    error="tool timeout"))
    assert bad.attribution.category == ErrorCategory.TOOL
    assert len(loop.pending()) == 1

    target = CaseDataset()
    loop.annotate(bad.id, Annotation(expected={"exact": "正确期望"},
                                     category=ErrorCategory.TOOL,
                                     note="补充标注", annotator="qa"))
    assert bad.status == "annotated"
    golden = loop.promote_to_golden(bad.id, target)
    assert bad.status == "promoted" and loop.pending() == []
    assert golden.id == "golden-bad-1" and golden.expected == {"exact": "正确期望"}
    assert golden in loop.golden.cases and golden in target.cases
    assert golden.metadata["source_bad_case"] == "bad-1"

    baseline = EvalReport(10, 10, 1.0, p95_latency_ms=100.0)
    current = EvalReport(10, 10, 1.0, p95_latency_ms=105.0)
    assert loop.regression_gate(baseline, current).passed is True


# ------------------------------------------------------------- A-B 实验
def test_experiment_assign_is_stable_and_salt_sensitive():
    exp = Experiment("exp-1", salt="s1")
    assert exp.assign("user-7") == exp.assign("user-7")
    assert exp.groups == ("control", "treatment")

    users = [f"user-{i}" for i in range(300)]
    assert {exp.assign(u) for u in users} == {"control", "treatment"}
    other = Experiment("exp-1", salt="s2")
    assert any(exp.assign(u) != other.assign(u) for u in users)

    with pytest.raises(ValueError):
        Experiment("bad", treatment_ratio=1.5)


def test_significance_test_detects_difference_and_null():
    control = [0.10, 0.11, 0.09, 0.10, 0.12, 0.08]
    treatment = [0.30, 0.31, 0.29, 0.30, 0.32, 0.28]
    result = significance_test(control, treatment)
    assert result.t_statistic > 0
    assert result.p_value < 0.01
    assert result.significant is True
    assert result.control_n == 6 and result.treatment_n == 6

    null = significance_test(control, control)
    assert null.p_value == pytest.approx(1.0)
    assert null.significant is False

    tiny = significance_test([0.5], [0.9])
    assert tiny.p_value == pytest.approx(1.0)


def test_experiment_runner_records_and_reports():
    runner = ExperimentRunner(Experiment("exp-2"))
    for i in range(8):
        runner.record("control", {"conversion": 0.1 + i * 0.001})
        runner.record("treatment", {"conversion": 0.4 + i * 0.001})
    assert len(runner.values("conversion", "control")) == 8

    report = runner.report("conversion")
    assert report.experiment == "exp-2" and report.metric == "conversion"
    assert report.test.control_mean == pytest.approx(0.1035, abs=1e-4)
    assert report.significant is True
    assert report.lift == pytest.approx(2.9, abs=0.1)
    assert "p_value" in report.as_dict()

    group = runner.record_for_user("u-100", {"conversion": 0.5})
    assert group in ("control", "treatment")
    with pytest.raises(ValueError):
        runner.record("unknown", {"conversion": 1.0})


# ------------------------------------------------------------- 导入回归
def test_eval_endpoint_with_baseline_pass_rate(client, admin_headers):
    """capabilities.py 的 EvalReport 导入缺失曾导致此分支抛 NameError。"""
    response = client.post(
        "/api/capabilities/eval",
        json={
            "cases": [{"id": "c1", "input": "hi", "expected": {"exact": "hi"}}],
            "runner": "echo",
            "baseline_pass_rate": 0.8,
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["report"]["pass_rate"] == 1.0
    assert body["gate"]["baseline_pass_rate"] == pytest.approx(0.8)
