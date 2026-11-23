# syntax=docker/dockerfile:1
# ---------- 构建阶段 ----------
FROM node:20-alpine AS build
WORKDIR /app

COPY package.json ./
# 仓库内可能没有 lockfile，因此用 install；有 lock 时可改为 npm ci
RUN npm install --no-audit --no-fund

COPY . .
# 构建期注入的基地址：nginx 部署下默认走同源 /api/v1
ARG VITE_API_BASE=/api/v1
ARG VITE_BACKEND_PYTHON=http://localhost:8000/api/v1
ARG VITE_BACKEND_JAVA=http://localhost:8080/api/v1
ENV VITE_API_BASE=$VITE_API_BASE \
    VITE_BACKEND_PYTHON=$VITE_BACKEND_PYTHON \
    VITE_BACKEND_JAVA=$VITE_BACKEND_JAVA
RUN npm run build

# ---------- 运行阶段 ----------
FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8088
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -q --spider http://127.0.0.1:8088/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
