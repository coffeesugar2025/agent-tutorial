#!/usr/bin/env bash
# =============================================================================
# 星图商城 · 查看日志
#
#   ./scripts/logs.sh                     # 全栈日志，跟踪模式，尾部 200 行
#   ./scripts/logs.sh backend-python      # 只看某个服务
#   ./scripts/logs.sh --tail 50 --no-follow mysql redis
#   ./scripts/logs.sh --infra milvus
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${DEPLOY_DIR}"

COMPOSE_FILE="docker-compose.yml"
FOLLOW=1
TAIL=200
SERVICES=()

usage() {
  cat <<'EOF'
用法: ./scripts/logs.sh [--infra] [--tail N] [--no-follow] [service...]

  --infra      使用中间件编排文件
  --tail N     显示末尾 N 行，默认 200
  --no-follow  不跟踪（一次性输出后退出）
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --infra) COMPOSE_FILE="docker-compose.infra.yml"; shift ;;
    --tail) TAIL="${2:-200}"; shift 2 ;;
    --no-follow) FOLLOW=0; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "[ERROR] 未知参数: $1" >&2; usage >&2; exit 2 ;;
    *) SERVICES+=("$1"); shift ;;
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

FOLLOW_ARGS=()
if [[ ${FOLLOW} -eq 1 ]]; then
  FOLLOW_ARGS=(-f)
fi

if [[ ${#SERVICES[@]} -gt 0 ]]; then
  "${DC[@]}" -f "${COMPOSE_FILE}" logs ${FOLLOW_ARGS[@]+"${FOLLOW_ARGS[@]}"} --tail "${TAIL}" "${SERVICES[@]}"
else
  "${DC[@]}" -f "${COMPOSE_FILE}" logs ${FOLLOW_ARGS[@]+"${FOLLOW_ARGS[@]}"} --tail "${TAIL}"
fi
