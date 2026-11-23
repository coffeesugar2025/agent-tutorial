#!/usr/bin/env bash
# =============================================================================
# 星图商城 · 一键启动
#
#   ./scripts/up.sh                # 全栈（中间件 + 两套后端 + 前端）
#   ./scripts/up.sh --build        # 全栈，强制重建镜像（首次启动用这个）
#   ./scripts/up.sh --infra        # 只启中间件（本地裸跑后端时用）
#
# 退出码：0 成功；1 环境不满足；2 参数错误
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${DEPLOY_DIR}"

COMPOSE_FILE="docker-compose.yml"
DO_BUILD=0

usage() {
  cat <<'EOF'
用法: ./scripts/up.sh [--infra] [--build]

  --infra    只启动中间件（mysql redis rabbitmq etcd minio milvus）
  --build    启动前重建镜像（代码变更 / 首次启动时使用）
  -h, --help 显示本帮助

常用:
  ./scripts/up.sh --build          # 全栈首次启动
  ./scripts/up.sh --infra          # 本地用 uv/mvn 跑后端
  ./scripts/logs.sh backend-python # 跟踪后端日志
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --infra) COMPOSE_FILE="docker-compose.infra.yml"; shift ;;
    --build) DO_BUILD=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[ERROR] 未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
done

command -v docker >/dev/null 2>&1 || {
  echo "[ERROR] 未找到 docker，请先安装 Docker Desktop / Docker Engine" >&2
  exit 1
}

# 优先用 compose 插件（docker compose），没有则回退到独立二进制（docker-compose）
DC=()
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
  echo "[WARN] 未检测到 'docker compose' 插件，回退到 docker-compose" >&2
else
  echo "[ERROR] 需要 Docker Compose（docker compose 或 docker-compose）" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "[INFO] 未发现 .env，已从 .env.example 生成（默认 MOCK_LLM=true，可离线体验）"
  cp .env.example .env
fi

dc() { "${DC[@]}" -f "${COMPOSE_FILE}" "$@"; }

echo "[INFO] 编排文件: ${COMPOSE_FILE}"
if [[ ${DO_BUILD} -eq 1 ]]; then
  dc up -d --build
else
  dc up -d
fi

echo
dc ps

# 从 .env 读取对外端口（不要 source，值里可能含空格）
env_val() {
  local key="$1" fallback="$2" line
  line="$(grep -E "^${key}=" .env | tail -n1 || true)"
  if [[ -z "${line}" ]]; then
    printf '%s' "${fallback}"
  else
    printf '%s' "${line#*=}"
  fi
}

FRONTEND_PORT="$(env_val FRONTEND_PORT 8088)"
APP_PORT_PYTHON="$(env_val APP_PORT_PYTHON 8000)"
APP_PORT_JAVA="$(env_val APP_PORT_JAVA 8080)"
MINIO_CONSOLE_PORT="$(env_val MINIO_CONSOLE_PORT 9001)"
RABBITMQ_MGMT_PORT="$(env_val RABBITMQ_MGMT_PORT 15672)"

cat <<EOF

==================== 启动完成 ====================
前端             http://localhost:${FRONTEND_PORT}
Python 后端      http://localhost:${APP_PORT_PYTHON}/health
Java 后端        http://localhost:${APP_PORT_JAVA}/health
RabbitMQ 控制台  http://localhost:${RABBITMQ_MGMT_PORT}  (ecom / ecom123)
MinIO 控制台     http://localhost:${MINIO_CONSOLE_PORT}  (minioadmin / minioadmin123)

首次启动 Milvus 约需 60-120s，期间后端会因依赖未就绪自动重试。
查看日志: ./scripts/logs.sh --tail 100
重置数据: ./scripts/reset.sh --yes
=================================================
EOF
