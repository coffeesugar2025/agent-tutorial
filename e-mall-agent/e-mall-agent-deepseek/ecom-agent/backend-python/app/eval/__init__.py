"""离线评测模块：数据集 → 判定 → 跑批 → 落库。

对外只暴露四个层次：

* :mod:`app.eval.dataset`：``eval_data/*.jsonl`` 用例加载与校验；
* :mod:`app.eval.judge`：规则断言 + LLM rubric 评分 + 分数归一；
* :mod:`app.eval.runner`：pass@k / pass^k / 成本 / 延迟统计，写 ``eval_run`` 与
  ``eval_case_result``；
* 本包：常用入口的再导出，便于 ``from app.eval import run_suite``。
"""

from app.eval.dataset import (
    EvalCase,
    EvalDataError,
    available_suites,
    load_all,
    load_cases,
    load_suite,
    resolve_data_dir,
)
from app.eval.judge import (
    PASS_THRESHOLD,
    RUBRIC,
    CheckOutcome,
    JudgeOutcome,
    evaluate_checks,
    judge_case,
    normalize_score,
)
from app.eval.runner import (
    AnswerResult,
    Asker,
    AttemptOutcome,
    CaseOutcome,
    EvalReport,
    calc_pass_at_k,
    calc_pass_pow_k,
    format_summary,
    mock_asker,
    resolve_asker,
    run_all,
    run_suite,
)

__all__ = [
    "PASS_THRESHOLD",
    "RUBRIC",
    "AnswerResult",
    "Asker",
    "AttemptOutcome",
    "CaseOutcome",
    "CheckOutcome",
    "EvalCase",
    "EvalDataError",
    "EvalReport",
    "JudgeOutcome",
    "available_suites",
    "calc_pass_at_k",
    "calc_pass_pow_k",
    "evaluate_checks",
    "format_summary",
    "judge_case",
    "load_all",
    "load_cases",
    "load_suite",
    "mock_asker",
    "normalize_score",
    "resolve_asker",
    "resolve_data_dir",
    "run_all",
    "run_suite",
]
