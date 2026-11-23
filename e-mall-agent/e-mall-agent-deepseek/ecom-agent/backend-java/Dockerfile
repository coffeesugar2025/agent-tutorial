# =============================================================================
# 星图商城 · 电商智能体平台  Java 后端镜像
#
# 构建（在 backend-java 目录）：docker build -t xingtu/ecom-backend-java:dev .
# 或由 deploy/docker-compose.yml 的 backend-java 服务自动构建（context=../backend-java）。
#
# 说明：
#   1. 多阶段构建：maven 镜像内打包，运行时只保留 JRE + fat jar。
#   2. 运行镜像装 curl：docker-compose 的 healthcheck 依赖 curl 访问 /health。
#   3. 非 root 运行；SERVER_PORT 由编排注入（默认 8080）。
#   4. JVM 参数通过 JAVA_TOOL_OPTIONS 覆盖，compose 里默认 -Xms512m -Xmx1024m。
# =============================================================================

# ---------- 构建阶段 ----------
FROM maven:3.9-eclipse-temurin-17 AS build

WORKDIR /build

# 先拷 pom 再拷源码，依赖层可被 Docker 缓存复用
COPY pom.xml ./
COPY src ./src

RUN mvn -B -ntp clean package -DskipTests

# ---------- 运行阶段 ----------
FROM eclipse-temurin:17-jre-jammy AS runtime

ENV TZ=Asia/Shanghai \
    LANG=C.UTF-8 \
    SERVER_PORT=8080 \
    JAVA_TOOL_OPTIONS="-Xms256m -Xmx768m"

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=build --chown=app:app /build/target/ecom-agent-java.jar /app/app.jar

USER app

EXPOSE 8080

# start-period 覆盖 MySQL/Redis/RabbitMQ 的连接建立时间
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=10 \
    CMD curl -fsS "http://127.0.0.1:${SERVER_PORT}/health" || exit 1

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
