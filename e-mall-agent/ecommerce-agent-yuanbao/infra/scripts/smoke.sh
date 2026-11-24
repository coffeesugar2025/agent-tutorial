#!/usr/bin/env bash
# 从仓库任意位置执行：bash infra/scripts/smoke.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
echo "repo root: $ROOT"
echo "== 1. infra health =="
for u in "http://localhost:9000/minio/health/live" "http://localhost:15672" "http://localhost:9090/-/healthy"; do
  curl -sf "$u" >/dev/null 2>&1 && echo "  OK $u" || echo "  SKIP $u (未就绪)"
done
echo "== 2. python backend =="
curl -sf http://localhost:8000/health | head -c 300; echo
echo "== 3. java backend =="
curl -sf http://localhost:8080/health | head -c 300; echo
echo "== 4. 双后端路径契约 =="
python3 "$ROOT/tests/contract/check_contract.py" --live
echo "== 5. 前端 =="
curl -sf http://localhost:8081/ | grep -q '<div id="app"' && echo "  OK frontend"
