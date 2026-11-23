#!/usr/bin/env bash
# 一键部署：检查 .env → 拉取/构建镜像 → 后台启动 → 打印访问地址
set -euo pipefail

cd "$(dirname "$0")/.."

# 从 .env 安全读取单个键（不 source，避免 URL 中的 & ? 等特殊字符被 shell 解释）
env_value() {
  local key="$1" default="$2" val
  val="$(grep -E "^${key}=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r' || true)"
  printf '%s' "${val:-$default}"
}

# 兼容 docker compose v2 插件与独立 docker-compose
if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
else
  COMPOSE=(docker-compose)
fi

if [[ ! -f .env ]]; then
  echo "[提示] 未找到 .env，已根据 .env.example 生成；生产环境请先修改口令后再部署。"
  cp .env.example .env
fi

echo "[1/3] 拉取基础镜像（本地构建镜像不存在时忽略失败） ..."
"${COMPOSE[@]}" pull || true

echo "[2/3] 构建应用镜像 ..."
"${COMPOSE[@]}" build

echo "[3/3] 启动全部服务 ..."
"${COMPOSE[@]}" up -d

echo
echo "部署完成，访问地址："
echo "  前端控制台      http://localhost:$(env_value FRONTEND_PORT 80)"
echo "  Python API 文档 http://localhost:$(env_value PYTHON_BACKEND_PORT 8000)/docs"
echo "  Java API        http://localhost:$(env_value JAVA_BACKEND_PORT 8080)/actuator/health"
echo "  RabbitMQ 管理页 http://localhost:$(env_value RABBITMQ_MGMT_PORT 15672)"
echo "  MinIO 控制台    http://localhost:$(env_value MINIO_CONSOLE_PORT 9001)"
echo
echo "查看状态：${COMPOSE[*]} ps     查看日志：bash scripts/logs.sh [service]"
echo "冒烟检查：bash scripts/smoke.sh"
