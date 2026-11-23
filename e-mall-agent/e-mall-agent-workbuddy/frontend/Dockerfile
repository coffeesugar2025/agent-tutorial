# Vue3 前端：node:22-alpine 构建静态产物 → nginx:alpine 托管 + 反向代理
# 构建上下文：项目根目录（.），因为需要同时读取 frontend/ 与 docker/frontend/
FROM node:22-alpine AS build

ARG VITE_API_BASE=/api
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ---------------- 运行阶段 ----------------
FROM nginx:alpine

ENV UPSTREAM_BACKEND=backend-python:8000

# 官方 entrypoint 会在启动时把模板中的 ${UPSTREAM_BACKEND} 替换后写入 /etc/nginx/conf.d/
COPY docker/frontend/nginx.conf.template /etc/nginx/templates/default.conf.template

COPY --from=build /app/dist/ /usr/share/nginx/html/

# frontend/public/config.js（内容：window.__APP_CONFIG__ = { API_BASE_URL: '' }）
# 已随 npm run build 复制到 dist/config.js，部署时挂载替换该文件即可切换后端。
# 不要在镜像里覆盖它，否则会丢失正确的 API_BASE_URL 键名。

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
