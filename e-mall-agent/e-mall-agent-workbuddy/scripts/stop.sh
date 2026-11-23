#!/usr/bin/env bash
# 停止全部服务（保留数据卷；需要清库请使用 reset-data.sh）
set -euo pipefail

cd "$(dirname "$0")/.."

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(docker-compose)
fi

echo "正在停止电商智能体全部服务（数据卷保留）..."
"${COMPOSE[@]}" down --remove-orphans
echo "已停止。如需彻底清空数据库与缓存数据，请运行 bash scripts/reset-data.sh"
