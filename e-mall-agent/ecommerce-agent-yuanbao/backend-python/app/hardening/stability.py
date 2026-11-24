"""稳定性：pass^k（k 次全成功）而非 pass@k（至少一次成功）（总纲 7.2 / 7.4 / C#9）。

之前 score_run 单次判定通过就收，正好踩中「只测一次就上线」。
"""
from __future__ import annotations

import statistics
from typing import Any, Callable

from app.capabilities.observability import EvalCase, EvalRun, score_run


def repeated_runs(case: EvalCase, runner: Callable[[EvalCase], EvalRun],
                  k: int = 5) -> dict[str, Any]:
    scores = [score_run(case, runner(case)) for _ in range(k)]
    passed = [s["passed"] for s in scores]
    lat = [s["latency_ms"] for s in scores]
    q = [s["end_to_end_quality"] for s in scores]
    return {
        "case_id": case.id, "k": k,
        "pass_at_k": round(sum(1 for p in passed if p) / k, 4),
        "pass_pow_k": 1.0 if all(passed) else 0.0,
        "all_passed": all(passed),
        "quality_mean": round(statistics.fmean(q), 4),
        "quality_stdev": round(statistics.pstdev(q), 4),
        "latency_p50_ms": sorted(lat)[k // 2],
        "latency_p95_ms": sorted(lat)[min(k - 1, int(k * 0.95))],
        "timeout_rate": round(sum(1 for x in lat if x > 30000) / k, 4),
        "verdict": "production_ready" if all(passed) else "needs_hardening",
    }


def suite_stability(suite: Any, runner: Callable[[EvalCase], EvalRun],
                    k: int = 3) -> dict[str, Any]:
    out = [repeated_runs(c, runner, k) for c in suite.cases.values()]
    return {"k": k, "cases": len(out),
            "aggregate_pass_pow_k": round(statistics.fmean(x["pass_pow_k"] for x in out), 4),
            "aggregate_pass_at_k": round(statistics.fmean(x["pass_at_k"] for x in out), 4),
            "flaky_cases": [x["case_id"] for x in out if not x["all_passed"]],
            "details": out}
