#!/usr/bin/env bash
# 用真实 JDK17 + 官方 1.24.0 jar 对 main 源码做 javac 编译（不依赖 Maven 完整依赖树）。
# 用途：在 CI / 本地快速发现语法与 import 错误；完整构建仍用 mvn clean test。
set -euo pipefail
JH="${JAVA_HOME:-$(dirname $(dirname $(readlink -f $(which javac))))}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JARS="${JARS_DIR:-$ROOT/.verify-jars}"
mkdir -p "$JARS" /tmp/agent-classes
B="https://mirrors.cloud.tencent.com/nexus/repository/maven-public"
coords=(
"dev/langchain4j/langchain4j-core/1.24.0/langchain4j-core-1.24.0.jar"
"dev/langchain4j/langchain4j/1.24.0/langchain4j-1.24.0.jar"
"dev/langchain4j/langchain4j-open-ai/1.24.0/langchain4j-open-ai-1.24.0.jar"
"dev/langchain4j/langchain4j-spring-boot-starter/1.24.0-beta34/langchain4j-spring-boot-starter-1.24.0-beta34.jar"
"org/springframework/boot/spring-boot/3.3.6/spring-boot-3.3.6.jar"
"org/springframework/boot/spring-boot-autoconfigure/3.3.6/spring-boot-autoconfigure-3.3.6.jar"
"org/springframework/spring-context/6.1.15/spring-context-6.1.15.jar"
"org/springframework/spring-beans/6.1.15/spring-beans-6.1.15.jar"
"org/springframework/spring-core/6.1.15/spring-core-6.1.15.jar"
"org/springframework/spring-web/6.1.15/spring-web-6.1.15.jar"
"org/springframework/spring-webmvc/6.1.15/spring-webmvc-6.1.15.jar"
"org/springframework/amqp/spring-amqp/3.1.6/spring-amqp-3.1.6.jar"
"org/springframework/amqp/spring-rabbit/3.1.6/spring-rabbit-3.1.6.jar"
"io/micrometer/micrometer-core/1.13.6/micrometer-core-1.13.6.jar"
"com/fasterxml/jackson/core/jackson-annotations/2.17.3/jackson-annotations-2.17.3.jar"
"org/slf4j/slf4j-api/2.0.16/slf4j-api-2.0.16.jar"
"jakarta/servlet/jakarta.servlet-api/6.0.0/jakarta.servlet-api-6.0.0.jar"
)
for c in "${coords[@]}"; do
  f="$JARS/$(basename "$c")"; [ -s "$f" ] || curl -fsSL --max-time 30 -o "$f" "$B/$c"
done
"$JH/bin/javac" -proc:none -nowarn -cp "$JARS/*" -d /tmp/agent-classes \
  $(find "$ROOT/src/main/java" -name '*.java')
echo "JAVAC COMPILE: PASS (main sources, JDK17 + langchain4j 1.24.0)"
