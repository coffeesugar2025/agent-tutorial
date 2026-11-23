#!/usr/bin/env bash
# 冒烟检查：等待服务就绪后逐一探测关键端点，输出 PASS / FAIL / WARN
set -euo pipefail

cd "$(dirname "$0")/.."

# 从 .env 安全读取单个键（不 source）
env_value() {
  local key="$1" default="$2" val
  val="$(grep -E "^${key}=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r' || true)"
  printf '%s' "${val:-$default}"
}

FRONTEND="http://localhost:$(env_value FRONTEND_PORT 80)"
PYTHON="http://localhost:$(env_value PYTHON_BACKEND_PORT 8000)"
JAVA="http://localhost:$(env_value JAVA_BACKEND_PORT 8080)"
RABBIT="http://localhost:$(env_value RABBITMQ_MGMT_PORT 15672)"
MILVUS="http://localhost:$(env_value MILVUS_METRICS_PORT 9091)"
RABBIT_USER="$(env_value RABBITMQ_USER ecom)"
RABBIT_PASS="$(env_value RABBITMQ_PASSWORD rabbit123456)"

# 返回 HTTP 状态码，失败时输出 000
http_code() {
  curl -sS -o /dev/null -w '%{http_code}' --max-time 8 "$@" 2>/dev/null || printf '000'
}

check() {
  local name="$1" url="$2"; shift 2
  local code
  code="$(http_code "$@" "$url")"
  if [[ "$code" =~ ^2 ]]; then
    printf 'PASS  %-22s %s\n' "$name" "$url"
    return 0
  fi
  printf 'FAIL  %-22s %s (HTTP %s)\n' "$name" "$url" "$code"
  return 1
}

echo "等待服务就绪（最多 120 秒）..."
ready=0
for _ in $(seq 1 60); do
  if [[ "$(http_code "${FRONTEND}/api/health")" =~ ^2 ]]; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" -ne 1 ]]; then
  echo "FAIL  服务未在 120 秒内就绪，请检查 docker compose ps 与日志。"
  exit 1
fi
echo "服务已就绪，开始探测。"
echo

failed=0

# 1. Python 后端健康检查（经前端网关，同时验证反向代理）
check "Python /api/health" "${FRONTEND}/api/health" || failed=$((failed + 1))
check "Python 直连健康"   "${PYTHON}/api/health"   || failed=$((failed + 1))

# 2. 商品列表接口（验证种子数据与 API 可用性）
check "商品列表"         "${FRONTEND}/api/products" || failed=$((failed + 1))

# 3. 基础设施聚合健康端点：当前两套后端可能尚未实现，404 记为 WARN 而非 FAIL
code_py="$(http_code "${FRONTEND}/api/infra/health")"
code_java="$(http_code "${JAVA}/api/infra/health")"
if [[ "$code_py" =~ ^2 || "$code_java" =~ ^2 ]]; then
  printf 'PASS  %-22s %s\n' "基础设施健康" "${FRONTEND}/api/infra/health"
elif [[ "$code_py" == "404" || "$code_java" == "404" ]]; then
  printf 'WARN  %-22s 后端尚未实现 /api/infra/health（不影响核心功能）\n' "基础设施健康"
else
  printf 'FAIL  %-22s Python=%s Java=%s\n' "基础设施健康" "$code_py" "$code_java"
  failed=$((failed + 1))
fi

# 4. Java 后端（actuator 不可用时回退到 /api/health）
code_java_health="$(http_code "${JAVA}/actuator/health")"
if [[ "$code_java_health" =~ ^2 ]]; then
  printf 'PASS  %-22s %s\n' "Java 后端健康" "${JAVA}/actuator/health"
else
  check "Java 后端健康" "${JAVA}/api/health" || failed=$((failed + 1))
fi

# 5. RabbitMQ 管理页（需 Basic Auth）
check "RabbitMQ 管理页" "${RABBIT}/" -u "${RABBIT_USER}:${RABBIT_PASS}" || failed=$((failed + 1))

# 6. Milvus 内部健康检查端口
check "Milvus healthz" "${MILVUS}/healthz" || failed=$((failed + 1))

echo
if [[ "$failed" -gt 0 ]]; then
  echo "结果：${failed} 项失败。请检查 docker compose logs 定位问题。"
  exit 1
fi
echo "结果：全部关键端点通过。"
