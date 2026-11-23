# Python(FastAPI / LangChain 1.5) 后端镜像
# 构建上下文：项目根目录的 backend/
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# curl 用于容器健康检查
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# requirements-prod.txt 由另一路并行任务生成；不存在时通配符不会匹配，安装步骤做容错
COPY requirements.txt ./
COPY requirements-prod.txt* ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ -f requirements-prod.txt ]; then pip install --no-cache-dir -r requirements-prod.txt || true; fi

# 非 root 运行
RUN useradd --uid 10001 --create-home --shell /bin/sh appuser \
    && mkdir -p /app && chown -R appuser:appuser /app
COPY --chown=appuser:appuser . .
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=10 \
    CMD curl -fsS http://127.0.0.1:8000/api/health >/dev/null || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
