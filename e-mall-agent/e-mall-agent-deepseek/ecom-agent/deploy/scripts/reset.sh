#!/usr/bin/env bash
# =============================================================================
# 星图商城 · 重置演示环境
#
# 会删除全部数据卷（MySQL 数据、Milvus 向量、MinIO 文件、Redis、MQ），
# 然后重新执行 01-schema.sql / 02-seed.sql 并重建镜像。
#
#   ./scripts/reset.sh            # 二次确认后执行
#   ./scripts/reset.sh --yes      # 跳过确认（CI 用）
#   ./scripts/reset.sh --yes --infra   # 只重置中间件
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${DEPLOY_DIR}"

COMPOSE_FILE="docker-compose.yml"
ASSUME_YES=0

usage() {
  cat <<'EOF'
用法: ./scripts/reset.sh [--yes] [--infra]

  --yes      跳过交互确认
  --infra    只重置中间件编排
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --infra) COMPOSE_FILE="docker-compose.infra.yml"; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[ERROR] 未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
done

DC=()
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
else
  echo "[ERROR] 需要 Docker Compose（docker compose 或 docker-compose）" >&2
  exit 1
fi

dc() { "${DC[@]}" -f "${COMPOSE_FILE}" "$@"; }

echo "编排文件: ${COMPOSE_FILE}"
echo "即将删除以下数据卷："
docker volume ls --format '{{.Name}}' | grep -E '^xingtu-(mysql|redis|rabbitmq|etcd|minio|milvus)-data$' || true

if [[ ${ASSUME_YES} -ne 1 ]]; then
  printf '确认继续？输入 yes 回车: '
  read -r answer || answer=""
  if [[ "${answer}" != "yes" ]]; then
    echo "[ABORT] 已取消"
    exit 0
  fi
fi

echo "[1/3] 停止并删除容器与数据卷"
dc down -v --remove-orphans

echo "[2/3] 清理遗留命名卷"
for v in xingtu-mysql-data xingtu-redis-data xingtu-rabbitmq-data \
         xingtu-etcd-data xingtu-minio-data xingtu-milvus-data; do
  docker volume rm "${v}" >/dev/null 2>&1 || true
done

echo "[3/3] 重新构建并启动"
if [[ "${COMPOSE_FILE}" == "docker-compose.infra.yml" ]]; then
  dc up -d
else
  dc up -d --build
fi

dc ps
echo
echo "[OK] 重置完成。MySQL 初始化脚本会重新执行 01-schema.sql → 02-seed.sql。"
echo "     默认账号 admin / alice / bob，密码统一 Passw0rd!"
