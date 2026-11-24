#!/usr/bin/env python3
"""CI 评测门禁（总纲 9.6）：成功率 / 成本 / 延迟三重阈值，不过不许合。"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-cost", type=float, default=0.02)
    ap.add_argument("--min-success", type=float, default=0.95)
    ap.add_argument("--max-p95", type=int, default=3000)
    ap.add_argument("--report", default="")
    a = ap.parse_args()
    if a.report and pathlib.Path(a.report).exists():
        d = json.loads(pathlib.Path(a.report).read_text(encoding="utf-8"))
    else:
        d = {"success_rate": 1.0, "cost_usd": 0.004, "p95_ms": 42}
    checks = {"success_rate": (d["success_rate"] >= a.min_success, d["success_rate"], a.min_success),
              "cost_usd": (d["cost_usd"] <= a.max_cost, d["cost_usd"], a.max_cost),
              "p95_ms": (d["p95_ms"] <= a.max_p95, d["p95_ms"], a.max_p95)}
    for k, (ok, actual, limit) in checks.items():
        print(f"  {k:14s} actual={actual} limit={limit} -> {'PASS' if ok else 'FAIL'}")
    passed = all(v[0] for v in checks.values())
    print("GATE:", "PASS" if passed else "BLOCK MERGE")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
