"""评测跑批：pass@k / pass^k、成本、延迟，并落 ``eval_run`` / ``eval_case_result``。

指标口径（与 docs 的评测要求一致，避免歧义）：

* **attempt**：一次「提问 → 回答 → 判定」；``repeat=k`` 表示同一用例跑 k 次；
* **pass@k**：k 次尝试中**至少一次**通过（``any``），衡量"能不能做对"；
* **pass^k**：k 次尝试**全部**通过（``all``），衡量"稳不稳定"；
* 落库映射：``eval_run.total/passed/pass_rate`` 按 attempt 统计；
  ``eval_run.pass_k`` 存 **pass^k**；pass@k 与 pass^k 同时写入
  ``eval_run.report``（键 ``passAtK`` / ``passHatK``），
  ``eval_case_result`` 每用例一行（``passed`` 取 pass@k、``score`` 取最佳分）。

回答来源通过 :class:`Asker` 注入：默认 ``auto`` 会尝试接入 ``app.agents.*``，
不可用时降级为确定性 :func:`mock_asker`（离线 CI / 演示用），
因此本模块 import 不依赖 Agent 运行时是否已实现。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-17] 评测与迭代
# 职责：评测跑批：pass@k / pass^k、成本、延迟，并落 ``eval_run`` / ``eval_case_res
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.common.timeutil import utcnow
from app.eval.dataset import EvalCase, available_suites, load_suite
from app.eval.judge import PASS_THRESHOLD, judge_case

logger = logging.getLogger(__name__)

AskerFn = Callable[[EvalCase], Awaitable[Any] | Any]

# 自动发现 Agent 入口时依次尝试的模块与函数名（存在即用，不存在就降级）
_AGENT_MODULES: tuple[str, ...] = (
    "app.agents.runtime",
    "app.agents.pipeline",
    "app.agents.graph",
    "app.agents.supervisor",
    "app.agents.team",
    "app.api.chat",
)
_AGENT_ATTRS: tuple[str, ...] = (
    "ask",
    "ask_once",
    "answer_question",
    "answer",
    "run_agent",
    "execute",
)

# eval_run.report 里保留的回答长度（完整回答在 eval_case_result.actual）
_REPORT_ANSWER_LIMIT = 500


# ---------------------------------------------------------------------------
# 回答与尝试
# ---------------------------------------------------------------------------
@dataclass
class AnswerResult:
    """一次回答及其成本/延迟（由 Asker 返回，也接受 str/dict 自动归一）。"""

    text: str = ""
    cost_cents: int = 0
    latency_ms: int = 0
    steps: int = 0
    asker: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "costCents": self.cost_cents,
            "latencyMs": self.latency_ms,
            "steps": self.steps,
            "asker": self.asker,
            "error": self.error,
        }


@dataclass
class Asker:
    """回答提供者：把「一条用例」变成 :class:`AnswerResult`。"""

    name: str
    fn: AskerFn
    description: str = ""

    async def ask(self, case: EvalCase) -> AnswerResult:
        started = time.perf_counter()
        value = self.fn(case)
        if inspect.isawaitable(value):
            value = await value
        elapsed = max(int((time.perf_counter() - started) * 1000), 0)
        result = coerce_answer(value, latency_ms=elapsed, asker=self.name)
        return result


@dataclass
class AttemptOutcome:
    """单次尝试结果。"""

    attempt: int
    passed: bool
    score: float
    answer: str = ""
    cost_cents: int = 0
    latency_ms: int = 0
    steps: int = 0
    mode: str = ""
    reason: str = ""
    checks: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self, *, include_answer: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "attempt": self.attempt,
            "passed": self.passed,
            "score": self.score,
            "costCents": self.cost_cents,
            "latencyMs": self.latency_ms,
            "steps": self.steps,
            "mode": self.mode,
            "reason": self.reason,
            "checks": self.checks,
            "error": self.error,
        }
        if include_answer:
            payload["answer"] = self.answer
        return payload


@dataclass
class CaseOutcome:
    """一条用例的 k 次尝试与聚合指标。"""

    case: EvalCase
    attempts: list[AttemptOutcome] = field(default_factory=list)

    @property
    def case_id(self) -> str:
        return self.case.id

    @property
    def pass_at_k(self) -> bool:
        return calc_pass_at_k([attempt.passed for attempt in self.attempts])

    @property
    def pass_pow_k(self) -> bool:
        return calc_pass_pow_k([attempt.passed for attempt in self.attempts])

    @property
    def best_score(self) -> float:
        return round(max((attempt.score for attempt in self.attempts), default=0.0), 3)

    @property
    def avg_score(self) -> float:
        if not self.attempts:
            return 0.0
        return round(sum(attempt.score for attempt in self.attempts) / len(self.attempts), 3)

    @property
    def avg_cost_cents(self) -> int:
        if not self.attempts:
            return 0
        return int(round(sum(attempt.cost_cents for attempt in self.attempts) / len(self.attempts)))

    @property
    def avg_latency_ms(self) -> int:
        if not self.attempts:
            return 0
        return int(round(sum(attempt.latency_ms for attempt in self.attempts) / len(self.attempts)))

    @property
    def best_answer(self) -> str:
        if not self.attempts:
            return ""
        best = max(self.attempts, key=lambda item: (item.passed, item.score))
        return best.answer

    def to_dict(self, *, include_answer: bool = False) -> dict[str, Any]:
        return {
            "caseId": self.case_id,
            "suite": self.case.suite,
            "question": self.case.question,
            "expected": self.case.expected,
            "passAtK": self.pass_at_k,
            "passHatK": self.pass_pow_k,
            "bestScore": self.best_score,
            "avgScore": self.avg_score,
            "avgCostCents": self.avg_cost_cents,
            "avgLatencyMs": self.avg_latency_ms,
            "attempts": [
                attempt.to_dict(include_answer=include_answer) for attempt in self.attempts
            ],
        }


@dataclass
class EvalReport:
    """一次 suite 跑批的完整报告。"""

    suite: str
    repeat: int = 1
    asker: str = ""
    threshold: float = PASS_THRESHOLD
    cases: list[CaseOutcome] = field(default_factory=list)
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None
    elapsed_ms: int = 0
    run_id: int | None = None
    persisted: bool = False
    persist_error: str | None = None

    # --- 聚合 ------------------------------------------------------------
    @property
    def total_cases(self) -> int:
        return len(self.cases)

    @property
    def total_attempts(self) -> int:
        return sum(len(case.attempts) for case in self.cases)

    @property
    def passed_attempts(self) -> int:
        return sum(1 for case in self.cases for attempt in case.attempts if attempt.passed)

    @property
    def pass_rate(self) -> float:
        total = self.total_attempts
        return round(self.passed_attempts / total, 4) if total else 0.0

    @property
    def pass_at_k(self) -> float:
        if not self.cases:
            return 0.0
        return round(sum(1 for case in self.cases if case.pass_at_k) / len(self.cases), 4)

    @property
    def pass_pow_k(self) -> float:
        if not self.cases:
            return 0.0
        return round(sum(1 for case in self.cases if case.pass_pow_k) / len(self.cases), 4)

    @property
    def avg_cost_cents(self) -> int:
        if not self.cases:
            return 0
        return int(round(sum(case.avg_cost_cents for case in self.cases) / len(self.cases)))

    @property
    def avg_latency_ms(self) -> int:
        if not self.cases:
            return 0
        return int(round(sum(case.avg_latency_ms for case in self.cases) / len(self.cases)))

    @property
    def failed_case_ids(self) -> list[str]:
        return [case.case_id for case in self.cases if not case.pass_at_k]

    def to_dict(self, *, include_answers: bool = False) -> dict[str, Any]:
        """序列化（落 ``eval_run.report`` / CLI ``--json``）。"""
        return {
            "runId": self.run_id,
            "suite": self.suite,
            "repeat": self.repeat,
            "asker": self.asker,
            "threshold": self.threshold,
            "startedAt": self.started_at.isoformat(timespec="seconds"),
            "finishedAt": (self.finished_at or utcnow()).isoformat(timespec="seconds"),
            "elapsedMs": self.elapsed_ms,
            "totalCases": self.total_cases,
            "totalAttempts": self.total_attempts,
            "passedAttempts": self.passed_attempts,
            "passRate": self.pass_rate,
            "passAtK": self.pass_at_k,
            "passHatK": self.pass_pow_k,
            "avgCostCents": self.avg_cost_cents,
            "avgLatencyMs": self.avg_latency_ms,
            "failedCaseIds": self.failed_case_ids,
            "persisted": self.persisted,
            "persistError": self.persist_error,
            "cases": [case.to_dict(include_answer=include_answers) for case in self.cases],
        }


# ---------------------------------------------------------------------------
# 指标函数
# ---------------------------------------------------------------------------
def calc_pass_at_k(flags: Sequence[bool]) -> bool:
    """pass@k：k 次尝试至少一次通过。"""
    return any(bool(flag) for flag in flags)


# ──────── [CAP-17] 评测与迭代 ────────
#   本处：pass^k（k 次全过的稳定性口径）
#   域约束：能用规则判定就不上 LLM judge；eval_run.pass_k 存的是 pass^k 而非 pass@k
def calc_pass_pow_k(flags: Sequence[bool]) -> bool:
    """pass^k：k 次尝试全部通过（空序列视为未通过）。"""
    return bool(flags) and all(bool(flag) for flag in flags)


# ---------------------------------------------------------------------------
# 回答来源
# ---------------------------------------------------------------------------
def coerce_answer(value: Any, *, latency_ms: int = 0, asker: str = "custom") -> AnswerResult:
    """把任意回答归一为 :class:`AnswerResult`（str / dict / 对象 / 已有实例）。"""
    if isinstance(value, AnswerResult):
        if not value.latency_ms:
            value.latency_ms = latency_ms
        if not value.asker:
            value.asker = asker
        return value
    if isinstance(value, str):
        return AnswerResult(text=value, latency_ms=latency_ms, asker=asker)
    if isinstance(value, dict):
        text = value.get("answer") or value.get("text") or value.get("content") or value.get("reply") or ""
        return AnswerResult(
            text=str(text),
            cost_cents=int(value.get("costCents") or value.get("cost_cents") or 0),
            latency_ms=int(value.get("latencyMs") or value.get("latency_ms") or latency_ms),
            steps=int(value.get("steps") or value.get("stepCount") or 0),
            asker=str(value.get("asker") or asker),
            error=value.get("error"),
        )
    # 对象：按常见字段名兜底
    text = ""
    for attr in ("answer", "text", "content", "reply"):
        candidate = getattr(value, attr, None)
        if isinstance(candidate, str) and candidate:
            text = candidate
            break
    return AnswerResult(
        text=text,
        cost_cents=int(getattr(value, "cost_cents", 0) or 0),
        latency_ms=int(getattr(value, "latency_ms", latency_ms) or latency_ms),
        steps=int(getattr(value, "steps", 0) or 0),
        asker=str(getattr(value, "asker", asker) or asker),
        error=getattr(value, "error", None),
    )


async def mock_asker(case: EvalCase) -> AnswerResult:
    """确定性回答：直接复用 ``expected``（离线演示 / 判分链路自检）。

    ⚠️ 只用于 ``MOCK_LLM=true`` 的 CI 与首次体验，不能用于真实质量评估。
    """
    expected = str(getattr(case, "expected", "") or "").strip()
    checks = getattr(case, "checks", None) or []
    if not expected:
        expected = "；".join(
            str(check.get("value", ""))
            for check in checks
            if str(check.get("type", "")).lower() == "contains"
        )
    if not expected:
        expected = f"（mock 回答）关于「{getattr(case, 'question', '')}」，建议转人工客服进一步确认。"
    return AnswerResult(text=expected, cost_cents=0, latency_ms=0, steps=1, asker="mock")


def _call_agent_fn(fn: Any, question: str) -> Any:
    """按签名调用 Agent 入口（兼容 ``fn(question)`` 与 ``fn(question=...)``）。"""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(question)
    parameters = signature.parameters
    if "question" in parameters or "query" in parameters:
        key = "question" if "question" in parameters else "query"
        return fn(**{key: question})
    positional = [
        param
        for param in parameters.values()
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)
    ]
    if positional:
        return fn(question)
    return fn()


def find_agent_callable() -> tuple[str, Any] | None:
    """在候选模块里寻找可用的 Agent 入口；找不到返回 ``None``（不抛异常）。"""
    for module_name in _AGENT_MODULES:
        try:
            module = importlib.import_module(module_name)
        except Exception:  # noqa: BLE001 - 模块不存在/依赖缺失都属于"不可用"
            continue
        for attr in _AGENT_ATTRS:
            candidate = getattr(module, attr, None)
            if callable(candidate) and not inspect.isclass(candidate):
                return f"{module_name}.{attr}", candidate
    return None


def resolve_asker(name: str | None = None) -> Asker:
    """解析回答来源。

    * ``mock`` / ``stub``：确定性 mock；
    * ``auto`` / ``agent``：优先接入 ``app.agents.*``，失败降级 mock；
    * 其它字符串：视为未知，打印警告后用 mock。
    """
    resolved = (name or "auto").lower()
    if resolved in {"mock", "stub", "expected"}:
        return Asker(name="mock", fn=mock_asker, description="确定性 mock（回显 expected）")
    if resolved in {"auto", "agent", "runtime"}:
        found = find_agent_callable()
        if found is None:
            logger.warning("未发现 Agent 运行时入口，评测降级为 mock asker")
            return Asker(name="mock(auto)", fn=mock_asker, description="Agent 不可用，降级 mock")
        label, fn = found
        asker_name = f"agent:{label}"
        return Asker(name=asker_name, fn=_wrap_agent(fn, asker_name), description=label)
    logger.warning("未知 asker=%s，降级 mock", name)
    return Asker(name="mock", fn=mock_asker, description="未知 asker，降级 mock")


def _wrap_agent(fn: Any, asker_name: str) -> AskerFn:
    async def _run(case: EvalCase) -> AnswerResult:
        started = time.perf_counter()
        value = _call_agent_fn(fn, case.question)
        if inspect.isawaitable(value):
            value = await value
        elapsed = max(int((time.perf_counter() - started) * 1000), 0)
        return coerce_answer(value, latency_ms=elapsed, asker=asker_name)

    return _run


# ---------------------------------------------------------------------------
# 跑批
# ---------------------------------------------------------------------------
async def run_suite(
    suite: str,
    *,
    cases: Sequence[EvalCase] | None = None,
    repeat: int = 1,
    ask: Asker | AskerFn | None = None,
    judge_mode: str = "auto",
    threshold: float = PASS_THRESHOLD,
    persist: bool = False,
    limit: int | None = None,
    concurrency: int = 1,
) -> EvalReport:
    """跑一个 suite 并返回报告。"""
    k = max(int(repeat), 1)
    loaded = list(cases) if cases is not None else load_suite(suite)
    if limit is not None:
        loaded = loaded[: max(int(limit), 0)]

    if isinstance(ask, Asker):
        asker = ask
    elif callable(ask):
        asker = Asker(name="custom", fn=ask, description="调用方注入")
    else:
        asker = resolve_asker()

    report = EvalReport(
        suite=suite,
        repeat=k,
        asker=asker.name,
        threshold=threshold,
        started_at=utcnow(),
    )
    if not loaded:
        report.finished_at = utcnow()
        return report

    semaphore = asyncio.Semaphore(max(int(concurrency), 1))

    async def _one(case: EvalCase) -> CaseOutcome:
        async with semaphore:
            attempts: list[AttemptOutcome] = []
            for attempt_no in range(1, k + 1):
                started = time.perf_counter()
                error: str | None = None
                try:
                    answer = await asker.ask(case)
                except Exception as exc:  # noqa: BLE001 - 单条失败不影响整批
                    logger.warning("用例 %s 第 %s 次回答失败: %s", case.id, attempt_no, exc)
                    answer = AnswerResult(error=f"{type(exc).__name__}: {exc}", asker=asker.name)
                    error = answer.error
                elapsed = max(int((time.perf_counter() - started) * 1000), 0)
                verdict = await judge_case(
                    case, answer.text, mode=judge_mode, threshold=threshold
                )
                passed = bool(verdict.passed) and error is None
                attempts.append(
                    AttemptOutcome(
                        attempt=attempt_no,
                        passed=passed,
                        score=verdict.score,
                        answer=answer.text,
                        cost_cents=answer.cost_cents,
                        latency_ms=answer.latency_ms or elapsed,
                        steps=answer.steps,
                        mode=verdict.mode,
                        reason=verdict.reason,
                        checks=[check.to_dict() for check in verdict.checks],
                        error=error,
                    )
                )
            return CaseOutcome(case=case, attempts=attempts)

    if concurrency > 1:
        outcomes = await asyncio.gather(*(_one(case) for case in loaded))
    else:
        outcomes = [await _one(case) for case in loaded]

    report.cases = list(outcomes)
    report.finished_at = utcnow()
    report.elapsed_ms = max(int((report.finished_at - report.started_at).total_seconds() * 1000), 0)

    if persist:
        try:
            report.run_id = persist_report(report)
            report.persisted = True
        except Exception as exc:  # noqa: BLE001 - 落库失败不丢评测结果
            logger.error("评测落库失败 suite=%s err=%s", suite, exc)
            report.persist_error = f"{type(exc).__name__}: {exc}"
    return report


async def run_all(
    suites: Sequence[str] | None = None,
    *,
    base_dir: Any = None,
    persist: bool = False,
    **kwargs: Any,
) -> list[EvalReport]:
    """依次跑多个 suite（``suites=None`` 表示数据目录下全部）。"""
    names = list(suites) if suites else available_suites(base_dir)
    reports: list[EvalReport] = []
    for name in names:
        cases = load_suite(name, base_dir=base_dir)
        report = await run_suite(name, cases=cases, persist=persist, **kwargs)
        reports.append(report)
    return reports


# ---------------------------------------------------------------------------
# 落库
# ---------------------------------------------------------------------------
def persist_report(report: EvalReport) -> int:
    """把报告写入 ``eval_run`` 与 ``eval_case_result``，返回 ``eval_run.id``。"""
    from app.infra.db import session_scope
    from app.infra.models_obs import EvalCaseResult, EvalRun

    finished = report.finished_at or utcnow()
    with session_scope() as db:
        run = EvalRun(
            suite=report.suite,
            status="RUNNING",
            total=report.total_attempts,
            passed=0,
            pass_rate=0.0,
            pass_k=0.0,
            repeat_times=report.repeat,
            avg_cost_cents=0,
            avg_latency_ms=0,
            report=None,
            started_at=report.started_at,
            finished_at=None,
        )
        db.add(run)
        db.flush()
        run_id = int(run.id)

        for case in report.cases:
            db.add(
                EvalCaseResult(
                    run_id=run_id,
                    case_id=case.case_id,
                    question=case.case.question,
                    expected=case.case.expected or None,
                    actual=case.best_answer[:8000] if case.best_answer else None,
                    passed=1 if case.pass_at_k else 0,
                    score=case.best_score,
                    attempts=len(case.attempts),
                    detail=case.to_dict(include_answer=False),
                )
            )

        run.status = "SUCCESS"
        run.passed = report.passed_attempts
        run.pass_rate = report.pass_rate
        run.pass_k = report.pass_pow_k
        run.avg_cost_cents = report.avg_cost_cents
        run.avg_latency_ms = report.avg_latency_ms
        run.report = report.to_dict(include_answers=False)
        run.finished_at = finished

    report.run_id = run_id
    return run_id


# ---------------------------------------------------------------------------
# 展示
# ---------------------------------------------------------------------------
def format_summary(report: EvalReport) -> str:
    """人类可读的跑批摘要（CLI 输出）。"""
    lines = [
        f"suite={report.suite}  cases={report.total_cases}  attempts={report.total_attempts} "
        f"repeat={report.repeat}  asker={report.asker}",
        f"pass@k={report.pass_at_k:.2%}  pass^k={report.pass_pow_k:.2%}  "
        f"attempt_pass_rate={report.pass_rate:.2%}  "
        f"avg_cost={report.avg_cost_cents}分  avg_latency={report.avg_latency_ms}ms",
    ]
    for case in report.cases:
        marks = "".join("P" if attempt.passed else "F" for attempt in case.attempts)
        lines.append(
            f"  [{'PASS' if case.pass_at_k else 'FAIL'}] {case.case_id} "
            f"{marks} score={case.best_score:.2f} cost={case.avg_cost_cents}分 "
            f"latency={case.avg_latency_ms}ms"
        )
        if not case.pass_at_k:
            failed = next((attempt for attempt in case.attempts if not attempt.passed), None)
            if failed is not None:
                lines.append(f"        └ {failed.mode}: {failed.reason[:160]}")
    if report.persist_error:
        lines.append(f"  ! 落库失败: {report.persist_error}")
    elif report.persisted:
        lines.append(f"  → eval_run.id={report.run_id}")
    return "\n".join(lines)


__all__ = [
    "AnswerResult",
    "Asker",
    "AskerFn",
    "AttemptOutcome",
    "CaseOutcome",
    "EvalReport",
    "calc_pass_at_k",
    "calc_pass_pow_k",
    "coerce_answer",
    "find_agent_callable",
    "format_summary",
    "mock_asker",
    "persist_report",
    "resolve_asker",
    "run_all",
    "run_suite",
]
