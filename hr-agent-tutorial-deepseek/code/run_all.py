"""依次运行 code/ 下所有章节脚本，确认教程代码都能跑通。

用法：
    python code/run_all.py
    python code/run_all.py --only 02,08
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="只运行指定序号，逗号分隔，如 02,08")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    only = {item.strip() for item in args.only.split(",") if item.strip()}

    scripts = sorted(CODE_DIR.glob("ch[0-9][0-9]_*.py"))
    if only:
        scripts = [path for path in scripts if path.name[2:4] in only]
    if not scripts:
        print("没有找到章节脚本")
        return 1

    failed: list[str] = []
    for script in scripts:
        print(f"\n{'=' * 70}\n>>> {script.name}\n{'=' * 70}", flush=True)
        try:
            result = subprocess.run(
                [sys.executable, "-u", str(script)],
                cwd=CODE_DIR.parent,
                timeout=args.timeout,
            )
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT {script.name}（超过 {args.timeout}s）")
            failed.append(script.name)
            continue
        if result.returncode != 0:
            failed.append(script.name)

    print(f"\n{'=' * 70}", flush=True)
    print(f"完成：{len(scripts) - len(failed)}/{len(scripts)} 通过")
    if failed:
        print("失败：" + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
