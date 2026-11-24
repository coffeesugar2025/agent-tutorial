"""评测链路单元测试：数据集校验、规则/LLM judge、分数归一、pass@k / pass^k 与落库。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-17] 评测与迭代  （支撑）
# 职责：评测链路单元测试：数据集校验、规则/LLM judge、分数归一、pass@k / pass^k 与落库
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import asyncio
import math

import pytest

from app.eval.dataset import CHECK_TYPES, available_suites, load_all, load_suite, summarize
from app.eval.judge import PASS_THRESHOLD, evaluate_checks, judge_case, mock_judge, normalize_score, rule_outcome
from app.eval.runner import calc_pass_at_k, calc_pass_pow_k, mock_asker, run_suite
from app.infra.db import session_scope
from app.infra.models_obs import EvalCaseResult, EvalRun

pytestmark = pytest.mark.unit


def _first_rule_case():
    for case in load_suite("shopping"):
        if case.has_checks:
            return case
    raise AssertionError("shopping 数据集缺少带规则断言的用例")


def test_datasets_load_and_are_consistent():
    suites = available_suites()
    assert {"shopping", "service", "rag"} <= set(suites)

    data = load_all()
    for name, cases in data.items():
        assert len(cases) >= 8, name
        assert len({case.id for case in cases}) == len(cases)
        assert all(case.suite == name for case in cases)
        assert all(case.question.strip() for case in cases)
        assert all(case.max_steps >= 1 for case in cases)
        for case in cases:
            for check in case.checks:
                assert check["type"] in CHECK_TYPES
                assert check["value"]

    info = summarize(data["rag"])
    assert info["total"] == len(data["rag"])
    assert info["bySuite"] == {"rag": len(data["rag"])}
    assert info["llmJudgeCases"] >= 1  # 至少一条无 checks，走 LLM judge


def test_normalize_score_handles_all_scales():
    assert normalize_score(0.8) == 0.8
    assert normalize_score(8) == 0.8
    assert normalize_score(80) == 0.8
    assert normalize_score(8, scale=10) == 0.8
    assert normalize_score(-5) == 0.0
    assert normalize_score(150) == 1.0
    assert normalize_score(None) == 0.0
    assert normalize_score("not-a-number") == 0.0
    assert normalize_score(math.nan) == 0.0
    assert normalize_score(math.inf) == 0.0


def test_rule_checks_pass_and_fail_with_context():
    answer = "退货运费由买家承担，质量问题由商家承担。"
    checks = [
        {"type": "contains", "value": "买家承担"},
        {"type": "not_contains", "value": "一律包邮"},
        {"type": "regex", "value": r"商家承担[。.]?$"},
    ]
    outcomes = evaluate_checks(answer, checks)

    assert all(item.passed for item in outcomes)
    assert rule_outcome(answer, checks).passed is True
    assert rule_outcome(answer, checks).score == 1.0

    failed = rule_outcome(answer, [{"type": "contains", "value": "七天无理由"}])
    assert failed.passed is False
    assert failed.score == 0.0
    assert "未包含" in failed.checks[0].detail


def test_unknown_or_invalid_rule_fails_safely():
    outcomes = evaluate_checks("任意回答", [{"type": "regex", "value": "([unclosed"}])

    assert outcomes[0].passed is False
    assert "非法正则" in outcomes[0].detail


def test_judge_uses_rules_when_checks_present():
    case = _first_rule_case()

    outcome = asyncio.run(judge_case(case, case.expected, mode="llm"))

    assert outcome.mode == "rules"
    assert outcome.passed is True
    assert outcome.score == 1.0
    assert outcome.checks

    wrong = asyncio.run(judge_case(case, "完全无关的回答", mode="auto"))
    assert wrong.mode == "rules"
    assert wrong.passed is False
    assert wrong.checks


def test_mock_judge_is_deterministic():
    case = _first_rule_case()
    first = mock_judge(case, case.expected)
    second = mock_judge(case, case.expected)
    empty = mock_judge(case, "")

    assert first.mode == "mock-llm"
    assert first.score == second.score == 1.0
    assert first.passed is True
    assert first.reason == second.reason
    assert empty.passed is False and empty.score == 0.0
    assert first.passed is (first.score >= PASS_THRESHOLD)


def test_pass_at_k_and_pass_pow_k_semantics():
    assert calc_pass_at_k([False, True, False]) is True
    assert calc_pass_pow_k([False, True, False]) is False
    assert calc_pass_pow_k([True, True]) is True
    assert calc_pass_at_k([]) is False
    assert calc_pass_pow_k([]) is False


def test_run_suite_tracks_pass_at_k_and_pass_pow_k():
    case = _first_rule_case()
    model = {"n": 0}

    def flaky(case_obj):
        model["n"] += 1
        # 奇数次正确、偶数次错误：pass@k 命中、pass^k 必然失败
        return case_obj.expected if model["n"] % 2 == 1 else "答非所问"

    report = asyncio.run(
        run_suite("shopping", cases=[case], repeat=4, ask=flaky, judge_mode="rules", persist=False)
    )

    attempts = [item.passed for item in report.cases[0].attempts]
    assert attempts == [True, False, True, False]
    assert report.total_attempts == 4
    assert report.passed_attempts == 2
    assert report.pass_rate == 0.5
    assert report.pass_at_k == 1.0
    assert report.pass_pow_k == 0.0
    assert report.cases[0].pass_at_k is True
    assert report.cases[0].pass_pow_k is False
    assert report.to_dict()["passAtK"] == 1.0
    assert report.to_dict()["passHatK"] == 0.0


@pytest.mark.integration
def test_run_suite_persists_eval_run_and_case_results():
    case = _first_rule_case()
    report = asyncio.run(
        run_suite("shopping", cases=[case], repeat=2, ask=mock_asker, persist=True)
    )

    assert report.persisted is True
    assert report.run_id and report.run_id > 0
    assert report.to_dict()["passHatK"] == 1.0

    with session_scope() as db:
        run = db.get(EvalRun, report.run_id)
        assert run is not None
        assert run.suite == "shopping"
        assert run.status == "SUCCESS"
        assert run.repeat_times == 2
        assert run.total == 2
        assert run.passed == 2
        assert run.pass_rate == 1.0
        assert run.pass_k == 1.0  # pass^k 写入 eval_run.pass_k
        assert run.report["passAtK"] == 1.0
        assert run.report["passHatK"] == 1.0

        rows = db.query(EvalCaseResult).filter(EvalCaseResult.run_id == report.run_id).all()
        assert len(rows) == 1
        assert rows[0].case_id == case.id
        assert rows[0].passed == 1
        assert rows[0].attempts == 2
        assert rows[0].score == 1.0
        assert rows[0].actual
