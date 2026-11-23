#!/usr/bin/env bash
# =============================================================================
# 星图商城 · 停止服务
#
#   ./scripts/down.sh              # 停止并删除容器，保留数据卷
#   ./scripts/down.sh --volumes    # 同时删除数据卷（数据全清）
#   ./scripts/down.sh --purge      # 删容器 + 删卷 + 删本项目镜像
#   ./scripts/down.sh --infra      # 只停中间件
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${DEPLOY_DIR}"

COMPOSE_FILE="docker-compose.yml"
REMOVE_VOLUMES=0
PURGE=0

usage() {
  cat <<'EOF'
用法: ./scripts/down.sh [--infra] [--volumes] [--purge]

  --infra    只处理中间件编排文件
  --volumes  删除数据卷（不可恢复，慎用）
  --purge    删除数据卷 + 本项目镜像
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --infra) COMPOSE_FILE="docker-compose.infra.yml"; shift ;;
    --volumes|-v) REMOVE_VOLUMES=1; shift ;;
    --purge) REMOVE_VOLUMES=1; PURGE=1; shift ;;
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

if [[ ${REMOVE_VOLUMES} -eq 1 ]]; then
  echo "[WARN] 将删除数据卷（mysql/redis/rabbitmq/etcd/minio/milvus 全部数据）"
  dc down -v
else
  dc down
fi

if [[ ${PURGE} -eq 1 ]]; then
  echo "[INFO] 删除本项目镜像前缀 xingtu/ecom-*"
  while IFS= read -r img; do
    [[ -z "${img}" ]] && continue
    docker rmi -f "${img}" >/dev/null 2>&1 || true
  done < <(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^xingtu/ecom-' || true)
fi

echo "[OK] 已停止（编排文件: ${COMPOSE_FILE}）"
