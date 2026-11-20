"""20 条 Golden Case 的确定性评测。

口径（与第 15 章一致）：
- 任务成功率：intent / tools / must_include 三项全过；
- 工具准确率：实际调用集合与期望集合完全一致；
- 引用准确率：制度类用例必须带引用，引用片段必须能回溯到知识库，且覆盖关键词；
- P95 延迟用 nearest-rank；token 与成本是估算值。

评测使用固定时钟 ``config.REFERENCE_NOW`` 和独立 Store，
因此重复运行不会污染线上会话，也不会因为“今天是几号”改变结论。
"""

from __future__ import annotations

import json
import math
import time

try:  # 作为包导入
    from . import config
except ImportError:  # python app/backend/main.py
    import config  # type: ignore[no-redef]

try:
    from .agent import HRAgent
    from .store import Store
except ImportError:  # pragma: no cover
    from agent import HRAgent  # type: ignore
    from store import Store  # type: ignore


# 上一版 Prompt / 检索参数在同样 20 条用例上的固定基线。
# 这些数字是写死在教程里的对照值，绝不能由当前运行结果反推。
BASELINE = {
    "success_rate": 0.85,
    "tool_accuracy": 0.90,
    "p95_latency_ms": 95,
}


def load_golden_cases() -> list[dict]:
    cases: list[dict] = []
    path = config.GOLDEN_CASES_PATH
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cases.append(json.loads(line))
    return cases


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))
    return round(ordered[index], 2)


def run_evaluation(rag) -> dict:
    started_at = time.perf_counter()
    cases = load_golden_cases()
    store = Store(clock=lambda: config.REFERENCE_NOW)
    agent = HRAgent(store, rag)

    rows: list[dict] = []
    latencies: list[float] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    tools_ok_count = 0
    citation_needed = 0
    citation_ok_count = 0

    for case in cases:
        started = time.perf_counter()
        try:
            result = agent.run(
                case["input"],
                case["employee_id"],
                session_id=f"s_eval_{case['id']}",
                now=config.REFERENCE_NOW,
            )
            payload = result.payload
            tools_used = result.tools_used
            citations = result.citations
            reply = payload["reply"]
            tokens = int(payload["usage"]["total_tokens"])
            total_prompt_tokens += int(payload["usage"]["prompt_tokens"])
            total_completion_tokens += int(payload["usage"]["completion_tokens"])
        except Exception as exc:  # noqa: BLE001 - 单条用例失败不应中断整轮评测
            payload = {"reply": "", "intent": "error", "usage": {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0}}
            tools_used = []
            citations = []
            reply = ""
            tokens = 0
            error_message = f"运行异常：{type(exc).__name__}: {exc}"
        else:
            error_message = ""
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        latencies.append(latency_ms)

        expected_intent = case.get("expected_intent", "")
        expected_tools = list(case.get("expected_tools", []))
        must_include = list(case.get("must_include", []))

        actual_intent = payload.get("intent", "")
        actual_tools = list(dict.fromkeys(tools_used))

        intent_ok = actual_intent == expected_intent
        tools_ok = set(actual_tools) == set(expected_tools)
        missing = [text for text in must_include if text not in reply]
        must_include_ok = not missing
        if tools_ok:
            tools_ok_count += 1

        failures: list[str] = []
        if not intent_ok:
            failures.append(f"intent: 期望 {expected_intent}，实际 {actual_intent}")
        if not tools_ok:
            failures.append(
                f"tools: 期望 {sorted(expected_tools)}，实际 {sorted(actual_tools)}"
            )
        if not must_include_ok:
            failures.append(f"must_include: 回答缺少 {missing}")
        if error_message:
            failures.append(error_message)

        citation_ok = True
        if "search_policy" in expected_tools:
            citation_needed += 1
            combined = " ".join(item.get("snippet", "") for item in citations)
            citation_ok = (
                rag.all_citations_grounded(citations)
                and all(item.get("status") == "active" for item in citations)
                and all(text in combined for text in must_include)
            )
            if citation_ok:
                citation_ok_count += 1
            else:
                failures.append("citation: 引用无法回溯、非 active 或未覆盖关键词")

        passed = not failures
        rows.append(
            {
                "id": case["id"],
                "input": case["input"],
                "passed": passed,
                "intent_ok": intent_ok,
                "tools_ok": tools_ok,
                "must_include_ok": must_include_ok,
                "citation_ok": citation_ok,
                "latency_ms": latency_ms,
                "tokens": tokens,
                "reply": reply,
                "failures": failures,
                "expected_intent": expected_intent,
                "actual_intent": actual_intent,
                "expected_tools": expected_tools,
                "actual_tools": actual_tools,
            }
        )

    total = len(rows)
    passed_count = sum(1 for row in rows if row["passed"])
    total_tokens = total_prompt_tokens + total_completion_tokens
    summary = {
        "total": total,
        "passed": passed_count,
        "success_rate": round(passed_count / total, 3) if total else 0.0,
        "tool_accuracy": round(tools_ok_count / total, 3) if total else 0.0,
        "citation_accuracy": (
            round(citation_ok_count / citation_needed, 3) if citation_needed else 1.0
        ),
        "avg_latency_ms": round(sum(latencies) / total, 1) if total else 0.0,
        "p95_latency_ms": _p95(latencies),
        "total_tokens": total_tokens,
        "cost_usd": config.estimate_cost_usd(total_prompt_tokens, total_completion_tokens),
    }
    result = {
        "summary": summary,
        "baseline": dict(BASELINE),
        "cases": rows,
    }
    # 评测本身必须快。这里只做一次自检，避免未来加入网络调用后悄悄退化。
    elapsed_ms = (time.perf_counter() - started_at) * 1000
    if elapsed_ms > 5000:  # pragma: no cover - 防御性检查
        print(f"[eval] 警告：评测耗时 {elapsed_ms:.0f}ms，超过 5 秒预算")
    return result
