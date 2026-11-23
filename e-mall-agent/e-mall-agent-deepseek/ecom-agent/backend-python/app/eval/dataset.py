"""评测数据集：从 ``eval_data/*.jsonl`` 加载用例。

每行一个 JSON 对象（空行与以 ``#`` 开头的注释行会被忽略）::

    {"id": "s-001", "suite": "shopping", "question": "帮我找 3000 以内的拍照手机",
     "expected": "推荐……", "checks": [{"type": "contains", "value": "推荐"}],
     "maxSteps": 6}

设计要点：

* 只依赖标准库与 :mod:`app.config`，脚本 / CI / 单元测试可直接使用；
* ``checks`` 为空表示该用例交给 LLM judge 按 rubric 打分，否则全部由规则断言决定；
* 加载即校验：``id`` 必填且同一份文件内唯一，check 类型必须在白名单内；
* 支持 ``suite`` 缺省：取文件名（``service.jsonl`` → ``service``）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import PROJECT_ROOT, settings

logger = logging.getLogger(__name__)

# 规则断言的类型白名单（与 judge.evaluate_checks 保持一致）
CHECK_TYPES: tuple[str, ...] = ("contains", "not_contains", "regex")

DEFAULT_MAX_STEPS = 6


class EvalDataError(ValueError):
    """评测数据格式错误（带文件名与行号，便于快速定位）。"""


@dataclass
class EvalCase:
    """一条评测用例（不可变语义，但仍允许附加标签方便扩展）。"""

    id: str
    suite: str
    question: str
    expected: str = ""
    checks: list[dict[str, str]] = field(default_factory=list)
    max_steps: int = DEFAULT_MAX_STEPS
    tags: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def case_id(self) -> str:
        """别名：部分调用方习惯 ``case_id``。"""
        return self.id

    @property
    def has_checks(self) -> bool:
        return bool(self.checks)

    @property
    def check_types(self) -> list[str]:
        return [str(check.get("type", "")) for check in self.checks]

    def to_dict(self) -> dict[str, Any]:
        """序列化（eval_run.report / API 输出，camelCase 与前端一致）。"""
        payload: dict[str, Any] = {
            "id": self.id,
            "suite": self.suite,
            "question": self.question,
            "expected": self.expected,
            "checks": [dict(check) for check in self.checks],
            "maxSteps": self.max_steps,
        }
        if self.tags:
            payload["tags"] = list(self.tags)
        return payload


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _parse_checks(raw: Any, *, where: str) -> list[dict[str, str]]:
    """校验并归一 ``checks`` 字段。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise EvalDataError(f"{where}: checks 必须是数组")
    checks: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise EvalDataError(f"{where}: checks[{index}] 必须是对象")
        check_type = _coerce_str(item.get("type")).strip().lower()
        if not check_type:
            raise EvalDataError(f"{where}: checks[{index}] 缺少 type")
        if check_type not in CHECK_TYPES:
            raise EvalDataError(
                f"{where}: checks[{index}] 不支持的类型 {check_type!r}（允许 {list(CHECK_TYPES)}）"
            )
        value = _coerce_str(item.get("value"))
        if not value:
            raise EvalDataError(f"{where}: checks[{index}] 缺少 value")
        checks.append({"type": check_type, "value": value})
    return checks


def parse_case(payload: Any, *, suite: str, source: str = "", line: int = 0) -> EvalCase:
    """把一行 JSON 解析为 :class:`EvalCase`。"""
    where = f"{source or '<memory>'}:{line}" if line else (source or "<memory>")
    if not isinstance(payload, dict):
        raise EvalDataError(f"{where}: 用例必须是 JSON 对象")

    case_id = _coerce_str(payload.get("id")).strip()
    question = _coerce_str(payload.get("question")).strip()
    if not case_id:
        raise EvalDataError(f"{where}: 缺少 id")
    if not question:
        raise EvalDataError(f"{where}: 用例 {case_id} 缺少 question")

    steps_raw = payload.get("maxSteps", payload.get("max_steps", DEFAULT_MAX_STEPS))
    try:
        max_steps = max(int(steps_raw), 1)
    except (TypeError, ValueError) as exc:
        raise EvalDataError(f"{where}: 用例 {case_id} 的 maxSteps 不是整数") from exc

    tags_raw = payload.get("tags") or []
    tags = [_coerce_str(tag).strip() for tag in tags_raw if _coerce_str(tag).strip()] if isinstance(tags_raw, list) else []

    return EvalCase(
        id=case_id,
        suite=_coerce_str(payload.get("suite")).strip() or suite,
        question=question,
        expected=_coerce_str(payload.get("expected")),
        checks=_parse_checks(payload.get("checks"), where=f"{where}:{case_id}"),
        max_steps=max_steps,
        tags=tags,
        source=source,
    )


def load_cases(path: str | Path, *, suite: str | None = None) -> list[EvalCase]:
    """从单个 jsonl 文件加载用例（保持文件内顺序）。"""
    file_path = Path(path)
    if not file_path.exists():
        raise EvalDataError(f"评测数据文件不存在: {file_path}")
    suite_name = suite or file_path.stem
    cases: list[EvalCase] = []
    seen: dict[str, int] = {}
    with file_path.open("r", encoding="utf-8-sig") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EvalDataError(f"{file_path}:{line_no}: JSON 解析失败（{exc.msg}）") from exc
            case = parse_case(payload, suite=suite_name, source=str(file_path), line=line_no)
            if case.id in seen:
                raise EvalDataError(
                    f"{file_path}:{line_no}: 用例 id 重复 {case.id!r}（首次出现在第 {seen[case.id]} 行）"
                )
            seen[case.id] = line_no
            cases.append(case)
    logger.debug("加载评测用例 %s 条: %s", len(cases), file_path)
    return cases


def resolve_data_dir(base_dir: str | Path | None = None) -> Path:
    """评测数据目录：显式参数 > ``EVAL_SUITES_DIR``，相对路径按项目根解析。"""
    raw = Path(base_dir) if base_dir else Path(settings.eval_suites_dir or "eval_data")
    if raw.is_absolute():
        return raw
    return PROJECT_ROOT / raw


def available_suites(base_dir: str | Path | None = None) -> list[str]:
    """列出可用的 suite 名称（``*.jsonl`` 文件名，按字典序）。"""
    directory = resolve_data_dir(base_dir)
    if not directory.is_dir():
        return []
    return sorted(path.stem for path in directory.glob("*.jsonl") if path.is_file())


def _suite_path(name: str, base_dir: str | Path | None = None) -> Path:
    """把 suite 名称或路径解析为具体文件。"""
    candidate = Path(name)
    if candidate.suffix == ".jsonl" and (candidate.is_file() or candidate.is_absolute()):
        return candidate
    directory = resolve_data_dir(base_dir)
    if candidate.suffix == ".jsonl":
        return directory / candidate.name
    if candidate.is_file():  # 相对路径直接命中
        return candidate
    return directory / f"{name}.jsonl"


def load_suite(name: str, *, base_dir: str | Path | None = None) -> list[EvalCase]:
    """加载单个 suite（``shopping`` / ``shopping.jsonl`` / 绝对路径均可）。"""
    path = _suite_path(name, base_dir)
    return load_cases(path, suite=Path(name).stem)


def load_all(*, base_dir: str | Path | None = None) -> dict[str, list[EvalCase]]:
    """加载数据目录下全部 suite。"""
    directory = resolve_data_dir(base_dir)
    result: dict[str, list[EvalCase]] = {}
    for suite in available_suites(base_dir):
        result[suite] = load_cases(directory / f"{suite}.jsonl", suite=suite)
    return result


def summarize(cases: list[EvalCase]) -> dict[str, Any]:
    """用例概览（CLI / 测试断言用）。"""
    by_suite: dict[str, int] = {}
    checks = 0
    for case in cases:
        by_suite[case.suite] = by_suite.get(case.suite, 0) + 1
        checks += len(case.checks)
    return {
        "total": len(cases),
        "bySuite": by_suite,
        "rulesCases": sum(1 for case in cases if case.has_checks),
        "llmJudgeCases": sum(1 for case in cases if not case.has_checks),
        "checks": checks,
    }


__all__ = [
    "CHECK_TYPES",
    "DEFAULT_MAX_STEPS",
    "EvalCase",
    "EvalDataError",
    "available_suites",
    "load_all",
    "load_cases",
    "load_suite",
    "parse_case",
    "resolve_data_dir",
    "summarize",
]
