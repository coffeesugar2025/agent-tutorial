"""In-process metrics registry, collector and LangChain callback middleware.

No external metrics backend is required; :class:`MetricRegistry` is a
thread-safe, label-aware implementation that can be swapped for Prometheus by
replacing :class:`MetricsCollector`'s registry.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

from langchain_core.callbacks import BaseCallbackHandler


def _label_key(labels: Mapping[str, Any] | None) -> tuple[tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def _format_labels(key: tuple[tuple[str, str], ...]) -> str:
    if not key:
        return "{}"
    return "{" + ",".join(f"{k}={v}" for k, v in key) + "}"


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolated percentile (q in [0, 1]); 0.0 for empty input."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = max(0.0, min(1.0, q)) * (len(ordered) - 1)
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    frac = pos - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * frac)


@dataclass
class Counter:
    value: float = 0.0

    def inc(self, amount: float = 1) -> None:
        self.value += float(amount)

    def get(self) -> float:
        return self.value

    def as_dict(self) -> dict[str, Any]:
        return {"value": round(self.value, 4)}


@dataclass
class Gauge:
    value: float = 0.0

    def set(self, value: float) -> None:
        self.value = float(value)

    def inc(self, amount: float = 1) -> None:
        self.value += float(amount)

    def dec(self, amount: float = 1) -> None:
        self.value -= float(amount)

    def get(self) -> float:
        return self.value

    def as_dict(self) -> dict[str, Any]:
        return {"value": round(self.value, 4)}


class Histogram:
    """Exact histogram: keeps observations for precise quantiles."""

    def __init__(self, max_samples: int = 20_000) -> None:
        self._values: list[float] = []
        self._sum = 0.0
        self._max_samples = max_samples
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        v = float(value)
        with self._lock:
            self._sum += v
            if len(self._values) < self._max_samples:
                self._values.append(v)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._values)

    @property
    def sum(self) -> float:
        with self._lock:
            return self._sum

    def quantile(self, q: float) -> float:
        with self._lock:
            return percentile(list(self._values), q)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            values = list(self._values)
            total = self._sum
        count = len(values)
        return {
            "count": count,
            "sum": round(total, 4),
            "avg": round(total / count, 4) if count else 0.0,
            "min": round(min(values), 4) if values else 0.0,
            "max": round(max(values), 4) if values else 0.0,
            "p50": round(percentile(values, 0.50), 4),
            "p95": round(percentile(values, 0.95), 4),
            "p99": round(percentile(values, 0.99), 4),
        }

    def as_dict(self) -> dict[str, Any]:
        return self.stats()


class MetricRegistry:
    """Thread-safe store of named, labelled Counter/Gauge/Histogram metrics."""

    def __init__(self) -> None:
        self._metrics: dict[tuple[str, str], dict[tuple[tuple[str, str], ...], Any]] = {}
        self._lock = threading.Lock()

    def _get(self, kind: str, name: str,
             labels: Mapping[str, Any] | None) -> Any:
        key = _label_key(labels)
        with self._lock:
            group = self._metrics.setdefault((kind, name), {})
            if key not in group:
                group[key] = Counter() if kind == "counter" \
                    else Gauge() if kind == "gauge" else Histogram()
            return group[key]

    def counter(self, name: str, labels: Mapping[str, Any] | None = None) -> Counter:
        return self._get("counter", name, labels)

    def gauge(self, name: str, labels: Mapping[str, Any] | None = None) -> Gauge:
        return self._get("gauge", name, labels)

    def histogram(self, name: str,
                  labels: Mapping[str, Any] | None = None) -> Histogram:
        return self._get("histogram", name, labels)

    def increment(self, name: str, value: float = 1,
                  labels: Mapping[str, Any] | None = None) -> None:
        self.counter(name, labels).inc(value)

    def set_gauge(self, name: str, value: float,
                  labels: Mapping[str, Any] | None = None) -> None:
        self.gauge(name, labels).set(value)

    def observe(self, name: str, value: float,
                labels: Mapping[str, Any] | None = None) -> None:
        self.histogram(name, labels).observe(value)

    def values(self, name: str, kind: str = "histogram") -> list[float]:
        """Collect all label buckets of a metric into a flat list."""
        with self._lock:
            group = dict(self._metrics.get((kind, name), {}))
        if kind == "histogram":
            result: list[float] = []
            for hist in group.values():
                with hist._lock:  # noqa: SLF001 - same module
                    result.extend(hist._values)  # noqa: SLF001
            return result
        return [float(m.get()) for m in group.values()]

    def counter_total(self, name: str,
                      label_filter: Mapping[str, Any] | None = None) -> float:
        """Sum every label bucket of a counter, optionally filtering labels."""
        with self._lock:
            group = dict(self._metrics.get(("counter", name), {}))
        wanted = _label_key(label_filter)
        total = 0.0
        for key, metric in group.items():
            if wanted and not all(item in key for item in wanted):
                continue
            total += float(metric.get())
        return total

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            items = list(self._metrics.items())
        result: dict[str, Any] = {"counters": {}, "gauges": {}, "histograms": {}}
        for (kind, name), group in items:
            target = result["counters" if kind == "counter"
                            else "gauges" if kind == "gauge" else "histograms"]
            bucket = target.setdefault(name, {})
            for key, metric in group.items():
                bucket[_format_labels(key)] = metric.as_dict()
        return result


class MetricsCollector:
    """Domain-level instrumentation built on :class:`MetricRegistry`."""

    def __init__(self, registry: MetricRegistry | None = None) -> None:
        self.registry = registry or MetricRegistry()

    def record_agent_run(self, route: str, ok: bool, latency_ms: float,
                         tokens: int = 0,
                         tools_used: list[str] | None = None) -> None:
        self.registry.increment("agent_runs_total", 1,
                                {"route": route, "ok": str(bool(ok)).lower()})
        self.registry.observe("agent_latency_ms", latency_ms, {"route": route})
        if tokens:
            self.registry.increment("agent_tokens_total", tokens, {"route": route})
        for tool in tools_used or []:
            self.registry.increment("agent_tools_total", 1, {"tool": tool})

    def record_tool_call(self, name: str, ok: bool, latency_ms: float) -> None:
        self.registry.increment("tool_calls_total", 1,
                                {"tool": name, "ok": str(bool(ok)).lower()})
        self.registry.observe("tool_latency_ms", latency_ms, {"tool": name})

    def record_rag(self, top_k: int, latency_ms: float,
                   groundedness: float) -> None:
        self.registry.increment("rag_queries_total", 1, {"top_k": str(top_k)})
        self.registry.observe("rag_latency_ms", latency_ms)
        self.registry.set_gauge("rag_groundedness", groundedness)

    def snapshot(self) -> dict[str, Any]:
        data = self.registry.snapshot()
        total_runs = sum(m["value"] for m in
                         data["counters"].get("agent_runs_total", {}).values())
        ok_runs = self.registry.counter_total("agent_runs_total", {"ok": "true"})
        tool_calls = sum(m["value"] for m in
                         data["counters"].get("tool_calls_total", {}).values())
        tool_errors = self.registry.counter_total("tool_calls_total", {"ok": "false"})
        tokens = sum(m["value"] for m in
                     data["counters"].get("agent_tokens_total", {}).values())
        latency = self.registry.values("agent_latency_ms")
        tool_latency = self.registry.values("tool_latency_ms")

        def _stats(values: list[float]) -> dict[str, Any]:
            return {
                "count": len(values),
                "sum": round(sum(values), 4),
                "p50": round(percentile(values, 0.50), 4),
                "p95": round(percentile(values, 0.95), 4),
                "p99": round(percentile(values, 0.99), 4),
            }

        data["summary"] = {
            "agent_runs": int(total_runs),
            "success_rate": round(ok_runs / total_runs, 4) if total_runs else 1.0,
            "tool_calls": int(tool_calls),
            "tool_error_rate": round(tool_errors / tool_calls, 4) if tool_calls else 0.0,
            "total_tokens": int(tokens),
            "agent_latency_ms": _stats(latency),
            "tool_latency_ms": _stats(tool_latency),
        }
        return data


class MetricsMiddleware(BaseCallbackHandler):
    """LangChain callback handler that feeds :class:`MetricsCollector`."""

    def __init__(self, collector: MetricsCollector | None = None) -> None:
        self.collector = collector or MetricsCollector()
        self._starts: dict[Any, tuple[str, float]] = {}

    @staticmethod
    def _run_id(kwargs: Mapping[str, Any]) -> Any:
        return kwargs.get("run_id") or kwargs.get("parent_run_id") or id(kwargs)

    @staticmethod
    def _route(kwargs: Mapping[str, Any]) -> str:
        metadata = kwargs.get("metadata") or {}
        if isinstance(metadata, Mapping) and metadata.get("route"):
            return str(metadata["route"])
        tags = kwargs.get("tags") or []
        if tags:
            return str(tags[0])
        return "default"

    @staticmethod
    def _tool_name(args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> str:
        name = kwargs.get("tool_name") or kwargs.get("name")
        if name:
            return str(name)
        serialized = kwargs.get("serialized")
        if serialized is None and args:
            serialized = args[0]
        if isinstance(serialized, Mapping) and serialized.get("name"):
            return str(serialized["name"])
        return "unknown"

    @staticmethod
    def _tokens(response: Any) -> int:
        output = getattr(response, "llm_output", None)
        if not isinstance(output, Mapping):
            return 0
        usage = output.get("token_usage") or output.get("usage") or {}
        if isinstance(usage, Mapping):
            return int(usage.get("total_tokens", 0) or 0)
        return int(output.get("total_tokens", 0) or 0)

    def _begin(self, kind: str, kwargs: Mapping[str, Any]) -> None:
        self._run_id(kwargs)
        self._starts[self._run_id(kwargs)] = (kind, time.perf_counter())

    def _end(self, kind: str, kwargs: Mapping[str, Any]) -> float:
        started = self._starts.pop(self._run_id(kwargs), None)
        if started is None or started[0] != kind:
            return 0.0
        return (time.perf_counter() - started[1]) * 1000

    # ---- LLM callbacks ----------------------------------------------------
    def on_llm_start(self, *args: Any, **kwargs: Any) -> None:
        self._begin("llm", kwargs)

    def on_llm_end(self, response: Any = None, *args: Any, **kwargs: Any) -> None:
        latency = self._end("llm", kwargs)
        self.collector.record_agent_run(
            route=self._route(kwargs), ok=True, latency_ms=latency,
            tokens=self._tokens(response),
        )

    def on_llm_error(self, error: Any = None, *args: Any, **kwargs: Any) -> None:
        latency = self._end("llm", kwargs)
        self.collector.record_agent_run(
            route=self._route(kwargs), ok=False, latency_ms=latency,
        )

    # ---- Tool callbacks ---------------------------------------------------
    def on_tool_start(self, *args: Any, **kwargs: Any) -> None:
        name = self._tool_name(args, kwargs)
        self._starts[self._run_id(kwargs)] = ("tool:" + name, time.perf_counter())

    def on_tool_end(self, output: Any = None, *args: Any, **kwargs: Any) -> None:
        name = self._tool_name(args, kwargs)
        marker = "tool:" + name
        started = self._starts.pop(self._run_id(kwargs), None)
        latency = (time.perf_counter() - started[1]) * 1000 \
            if started and started[0] == marker else 0.0
        self.collector.record_tool_call(name, True, latency)

    def on_tool_error(self, error: Any = None, *args: Any, **kwargs: Any) -> None:
        name = self._tool_name(args, kwargs)
        marker = "tool:" + name
        started = self._starts.pop(self._run_id(kwargs), None)
        latency = (time.perf_counter() - started[1]) * 1000 \
            if started and started[0] == marker else 0.0
        self.collector.record_tool_call(name, False, latency)


__all__ = [
    "Counter", "Gauge", "Histogram", "MetricRegistry", "MetricsCollector",
    "MetricsMiddleware", "percentile",
]
