# =============================================================================
# 前端镜像：多阶段构建（Node 构建 → nginx 托管静态产物）
#
# 构建上下文是仓库根目录（见 docker-compose.yml: context: ..），
# 所以这里从 frontend/ 拷贝源码。运行时 nginx 配置由 compose 以 bind mount
# 注入（./nginx/nginx.conf → /etc/nginx/conf.d/default.conf），此处不 COPY 配置，
# 保证「一份配置、改完 reload 即生效」。
#
# 若前端工程自带专用 Dockerfile（多环境构建、CDN 前缀等），
# 把 compose 里 frontend.build 改回 context: ../frontend 即可，本文件可弃用。
# =============================================================================
# syntax=docker/dockerfile:1

FROM node:20-alpine AS build

WORKDIR /app

ENV NPM_CONFIG_FUND=false \
    NPM_CONFIG_AUDIT=false \
    CI=true

# 先整目录拷贝再 npm ci：npm ci 会删除已有 node_modules，
# 因此宿主机遗留的 node_modules 不会污染镜像（避免 esbuild 等原生包架构不符）
COPY frontend/ ./

RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

RUN npm run build

# ---------------------------------------------------------------------------
# 运行阶段：Vite 默认产物目录为 dist
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

ENV TZ=Asia/Shanghai

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/healthz || exit 1
