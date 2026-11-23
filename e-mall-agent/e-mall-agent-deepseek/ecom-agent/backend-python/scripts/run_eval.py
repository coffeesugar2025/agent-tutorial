#!/usr/bin/env python
"""评测 CLI：加载 ``eval_data/*.jsonl`` → 跑批 → 打印 pass@k / pass^k / 成本 / 延迟。

用法示例::

    # 离线自检（Mock 回答 + 规则/确定性裁判，不写库、不联网）
    python scripts/run_eval.py --asker mock

    # 指定 suite 与 k 次重复，结果落库（SQLite）
    DATABASE_URL=sqlite:///./var/eval.db AUTO_CREATE_TABLES=true \
        python scripts/run_eval.py --suite shopping service --repeat 3 --persist

    # 只看数据概览
    python scripts/run_eval.py --list

退出码：0 = 全部 suite 达到 ``--min-pass-rate``；1 = 未达标；2 = 没有可用数据。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.eval.dataset import EvalDataError, available_suites, load_suite, summarize  # noqa: E402
from app.eval.judge import PASS_THRESHOLD  # noqa: E402
from app.eval.runner import format_summary, resolve_asker, run_suite  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="电商智能体离线评测")
    parser.add_argument("--suite", nargs="+", default=None, help="要跑的 suite（默认全部）")
    parser.add_argument("--data-dir", default=None, help="评测数据目录（默认 EVAL_SUITES_DIR）")
    parser.add_argument("--repeat", type=int, default=1, help="每个用例重复次数 k（默认 1）")
    parser.add_argument(
        "--asker",
        default="auto",
        choices=["auto", "mock", "agent"],
        help="回答来源：auto 尝试接入 Agent，失败降级 mock",
    )
    parser.add_argument(
        "--judge",
        default="auto",
        choices=["auto", "rules", "mock", "llm"],
        help="判定方式（有 checks 的用例始终走规则）",
    )
    parser.add_argument("--threshold", type=float, default=PASS_THRESHOLD, help="判分通过线")
    parser.add_argument("--limit", type=int, default=None, help="每个 suite 只跑前 N 条")
    parser.add_argument("--concurrency", type=int, default=1, help="并发用例数（默认 1）")
    parser.add_argument("--persist", action="store_true", help="写 eval_run / eval_case_result")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出（便于 CI 解析）")
    parser.add_argument("--list", action="store_true", help="列出数据目录下的 suite 与用例数")
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=0.0,
        help="每个 suite 的 pass@k 下限，低于则退出码 1",
    )
    return parser


def _load_reports(args: argparse.Namespace) -> list:
    names = args.suite or available_suites(args.data_dir)
    if not names:
        return []
    asker = resolve_asker(args.asker)
    reports = []
    for name in names:
        cases = load_suite(name, base_dir=args.data_dir)
        if args.limit is not None:
            cases = cases[: max(args.limit, 0)]
        report = asyncio.run(
            run_suite(
                name,
                cases=cases,
                repeat=args.repeat,
                ask=asker,
                judge_mode=args.judge,
                threshold=args.threshold,
                persist=args.persist,
                concurrency=args.concurrency,
            )
        )
        reports.append(report)
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        names = available_suites(args.data_dir)
        if not names:
            print(f"没有找到评测数据：{args.data_dir or 'eval_data'}")
            return 2
        for name in names:
            cases = load_suite(name, base_dir=args.data_dir)
            info = summarize(cases)
            print(
                f"{name:<10} cases={info['total']:<3} "
                f"rules={info['rulesCases']:<3} llmJudge={info['llmJudgeCases']:<3} "
                f"checks={info['checks']}"
            )
        return 0

    try:
        names = args.suite or available_suites(args.data_dir)
    except EvalDataError as exc:
        print(f"评测数据错误: {exc}", file=sys.stderr)
        return 2
    if not names:
        print("没有可用的评测 suite（检查 EVAL_SUITES_DIR / --data-dir）", file=sys.stderr)
        return 2

    if args.persist:
        # SQLite 演示场景自动建表；MySQL 生产库由 01-schema.sql 建表
        try:
            from app.config import settings

            if settings.is_sqlite:
                from app.infra.db import init_db

                init_db(create_tables=True)
        except Exception as exc:  # noqa: BLE001 - 建表失败交给落库环节报错
            print(f"[warn] 初始化数据库失败（继续跑评测，落库可能失败）: {exc}", file=sys.stderr)

    if not args.json:
        total_cases = 0
        for name in names:
            try:
                info = summarize(load_suite(name, base_dir=args.data_dir))
            except EvalDataError as exc:
                print(f"评测数据错误: {exc}", file=sys.stderr)
                return 2
            total_cases += info["total"]
            print(
                f"[数据] {name}: {info['total']} 条"
                f"（规则 {info['rulesCases']} / LLM judge {info['llmJudgeCases']}）"
            )
        print(f"[数据] 共 {len(names)} 个 suite、{total_cases} 条用例\n")

    try:
        reports = _load_reports(args)
    except EvalDataError as exc:
        print(f"评测数据错误: {exc}", file=sys.stderr)
        return 2

    if args.json:
        payload = {
            "asker": reports[0].asker if reports else args.asker,
            "repeat": args.repeat,
            "judge": args.judge,
            "reports": [report.to_dict(include_answers=False) for report in reports],
            "passAtK": round(
                sum(report.pass_at_k for report in reports) / max(len(reports), 1), 4
            ),
            "passHatK": round(
                sum(report.pass_pow_k for report in reports) / max(len(reports), 1), 4
            ),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for report in reports:
            print(format_summary(report))
            print()

    worst = min((report.pass_at_k for report in reports), default=0.0)
    avg_at_k = sum(report.pass_at_k for report in reports) / max(len(reports), 1)
    avg_hat_k = sum(report.pass_pow_k for report in reports) / max(len(reports), 1)
    if not args.json:
        print(f"[汇总] 平均 pass@k={avg_at_k:.2%} 平均 pass^k={avg_hat_k:.2%}")
    return 0 if worst >= args.min_pass_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
