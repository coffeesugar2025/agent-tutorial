#!/usr/bin/env python3
"""双后端契约一致性校验：静态比对两端声明的路由 + 可选在线探测。

用法：
  python3 tests/contract/check_contract.py                      # 静态
  python3 tests/contract/check_contract.py --live              # 需两端已启动
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "tests/contract/openapi-contract.json").read_text(encoding="utf-8"))


def python_paths() -> set[str]:
    out = set()
    for f in (ROOT / "backend-python/app/api").glob("*.py"):
        s = f.read_text(encoding="utf-8")
        for m in re.finditer(r'@router\.(?:get|post|delete|put)\("([^"]+)"', s):
            p = m.group(1)
            # 拼回 router 前缀
            prefix = "/v3" if "routes_v3" in f.name else ("/v2" if "routes_ext" in f.name else "")
            if f.name == "routes.py":
                prefix = ""
            out.add(prefix + p)
    return out


def java_paths() -> set[str]:
    out = set()
    for f in (ROOT / "backend-java/src/main/java").rglob("*.java"):
        s = f.read_text(encoding="utf-8")
        base = ""
        mm = re.search(r'@RequestMapping\("([^"]+)"\)', s)
        if mm:
            base = mm.group(1)
        for m in re.finditer(r'@(?:Get|Post|Put|Delete)Mapping([^\n]*)', s):
            pm = re.search(r'"(/[^"]*)"', m.group(1))
            out.add(base + (pm.group(1) if pm else ""))
    return out


def main() -> int:
    py, jv = python_paths(), java_paths()
    shared = {x["path"] for x in CONTRACT["shared_paths"]}
    missing_py = sorted(shared - py)
    missing_jv = sorted(shared - jv)
    print(f"contract paths: {len(shared)}  python routes: {len(py)}  java routes: {len(jv)}")
    print("missing in python:", missing_py or "none")
    print("missing in java  :", missing_jv or "none")
    if "--live" in sys.argv:
        import urllib.request
        for base, name in (("http://localhost:8000", "python"),
                           ("http://localhost:8080", "java")):
            try:
                r = urllib.request.urlopen(base + "/v3/capabilities", timeout=3)
                print(f"  live {name}: HTTP {r.status}")
            except Exception as exc:
                print(f"  live {name}: unavailable ({type(exc).__name__})")
    ok = not missing_py and not missing_jv
    print("NOTE: 仅校验路径存在性，不校验响应字段取值或业务语义")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
