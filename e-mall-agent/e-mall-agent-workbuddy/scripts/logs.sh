#!/usr/bin/env bash
# 跟随日志：bash scripts/logs.sh [service]  不带参数则跟随全部服务
set -euo pipefail

cd "$(dirname "$0")/.."

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(docker-compose)
fi

if [[ $# -eq 0 ]]; then
  echo "跟随全部服务日志（Ctrl+C 退出）..."
  "${COMPOSE[@]}" logs -f --tail=100
else
  echo "跟随服务 [$*] 的日志（Ctrl+C 退出）..."
  "${COMPOSE[@]}" logs -f --tail=100 "$@"
fi
