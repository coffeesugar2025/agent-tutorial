"""可观测性与评测最小实现：Trace / Metrics / Eval Runner。

生产里对应：OpenTelemetry + Jaeger/Tempo（Trace）、Prometheus + Grafana（Metrics）、
结构化日志 + ELK/Loki（Logs）、Langfuse / LangSmith / Arize Phoenix（LLM 专用）、
以及自建 Golden Case 回归集（评测）。这里手写是为了让你知道**每个指标怎么算出来的**。
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable

from . import hr_data


@dataclass
class Span:
    span_id: str
    name: str
    parent_id: str | None
    start_ms: float
    end_ms: float = 0.0
    attrs: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"

    @property
    def duration_ms(self) -> float:
        return round(self.end_ms - self.start_ms, 2)

    def as_dict(self) -> dict:
        return {"span_id": self.span_id, "name": self.name, "parent_id": self.parent_id,
                "duration_ms": self.duration_ms, "attrs": self.attrs, "status": self.status}


class Tracer:
    """一个 trace_id 串起一次任务，span 之间用 parent_id 形成树。"""
    def __init__(self, trace_id: str | None = None):
        self.trace_id = trace_id or uuid.uuid4().hex[:12]
        self.spans: list[Span] = []
        self._stack: list[str] = []

    @contextmanager
    def span(self, name: str, **attrs: Any):
        s = Span(span_id=uuid.uuid4().hex[:8], name=name,
                 parent_id=self._stack[-1] if self._stack else None,
                 start_ms=time.perf_counter() * 1000, attrs=attrs)
        self._stack.append(s.span_id)
        try:
            yield s
        except Exception as exc:
            s.status = "error"
            s.attrs["error"] = str(exc)
            raise
        finally:
            s.end_ms = time.perf_counter() * 1000
            self._stack.pop()
            self.spans.append(s)

    def as_dict(self) -> dict:
        return {"trace_id": self.trace_id, "spans": [s.as_dict() for s in self.spans],
                "total_ms": round(sum(s.duration_ms for s in self.spans), 2)}


class MetricsCollector:
    def __init__(self) -> None:
        self.counters: dict[str, float] = {}
        self.histograms: dict[str, list[float]] = {}

    def inc(self, name: str, value: float = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + value

    def observe(self, name: str, value: float) -> None:
        self.histograms.setdefault(name, []).append(float(value))

    @staticmethod
    def percentile(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        s = sorted(values)
        idx = min(len(s) - 1, int(round((p / 100) * len(s)) - 1))
        return round(s[max(idx, 0)], 2)

    def snapshot(self) -> dict:
        out = {"counters": dict(self.counters)}
        for name, vals in self.histograms.items():
            out[name] = {"count": len(vals), "avg": round(sum(vals) / len(vals), 2),
                         "p95": self.percentile(vals, 95), "p99": self.percentile(vals, 99)}
        return out


class EvalRunner:
    """Golden Case 回归：跑一批固定用例，用断言算任务成功率 / 工具调用准确率。

    真实项目还要加：LLM-as-Judge 评回答质量、幻觉率人工标注、Bad Case 回放、
    A/B 对比、回归门禁（指标下降就阻断发布）。
    """
    def __init__(self) -> None:
        self.metrics = MetricsCollector()
        self.tracer = Tracer()
        self.results: list[dict] = []

    def cases(self) -> list[dict]:
        conn = hr_data.connect()
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM eval_cases")]
        finally:
            conn.close()

    def run(self, execute: Callable[[dict], dict], *, limit: int = 5) -> dict:
        t0 = time.perf_counter()
        for case in self.cases()[:limit]:
            t_case = time.perf_counter()
            with self.tracer.span("eval_case", case_id=case["case_id"]) as sp:
                res = execute(case)
                steps = res.get("steps", [])
                answer = str(res.get("answer", ""))
                tool_hit = any(case["expect_tool"] in str(s) for s in steps) if case["expect_tool"] else True
                keywords = [k.strip() for k in case["expect_keywords"].split(",") if k.strip()]
                kw_hit = all(k in answer for k in keywords) if keywords else True
                passed = bool(tool_hit and kw_hit)
                self.results.append({
                    "case_id": case["case_id"], "question": case["question"],
                    "expect_tool": case["expect_tool"], "tool_hit": tool_hit,
                    "keywords": keywords, "kw_hit": kw_hit, "passed": passed,
                    "answer_preview": answer[:120],
                })
                sp.attrs["passed"] = passed
                self.metrics.inc("cases_total")
                self.metrics.inc("cases_passed" if passed else "cases_failed")
                self.metrics.observe("latency_ms", (time.perf_counter() - t_case) * 1000)
                self.metrics.inc("tokens_total", res.get("metrics", {}).get("tokens_est", 0))
        conn = hr_data.connect()
        try:
            for r in self.results:
                conn.execute("INSERT INTO eval_runs(trace_id,case_id,passed,detail,created_at) VALUES(?,?,?,?,?)",
                             (self.tracer.trace_id, r["case_id"], int(r["passed"]),
                              json.dumps(r, ensure_ascii=False), hr_data.now()))
            conn.commit()
        finally:
            conn.close()
        total = len(self.results) or 1
        snap = self.metrics.snapshot()
        return {
            "trace": self.tracer.as_dict(),
            "results": self.results,
            "metrics": snap,
            "summary": {
                "任务成功率": f"{sum(r['passed'] for r in self.results)}/{total}",
                "工具调用命中率": f"{sum(r['tool_hit'] for r in self.results)}/{total}",
                "P95 延迟(ms)": snap.get("latency_ms", {}).get("p95", 0),
                "Token 成本估算": snap["counters"].get("tokens_total", 0),
                "回归耗时(s)": round(time.perf_counter() - t0, 3),
            },
        }
