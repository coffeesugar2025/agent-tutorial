#!/usr/bin/env bash
# 危险操作：删除全部数据卷（数据库、缓存、队列、Milvus 依赖的元数据与对象存储）
set -euo pipefail

cd "$(dirname "$0")/.."

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(docker-compose)
fi

RED=$'\033[1;31m'
YELLOW=$'\033[1;33m'
NC=$'\033[0m'

echo "${RED}============================================================${NC}"
echo "${RED}  警告：此操作会永久删除 MySQL / Redis / RabbitMQ / etcd /${NC}"
echo "${RED}  MinIO 的全部数据卷，且无法撤销！请务必先自行备份。      ${NC}"
echo "${RED}============================================================${NC}"
echo

read -r -p "${YELLOW}第一次确认：输入 yes 继续 → ${NC}" answer
if [[ "${answer,,}" != "yes" ]]; then
  echo "已取消。"
  exit 0
fi

read -r -p "${YELLOW}第二次确认：输入 RESET 销毁全部数据 → ${NC}" answer
if [[ "$answer" != "RESET" ]]; then
  echo "确认失败，已取消。"
  exit 0
fi

echo "正在停止服务并删除数据卷 ..."
"${COMPOSE[@]}" down -v --remove-orphans
echo "数据卷已清空。下次执行 bash scripts/deploy.sh 将重新初始化种子数据。"
