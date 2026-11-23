# ---------- build ----------
FROM maven:3.9.9-eclipse-temurin-17 AS build
WORKDIR /workspace
COPY pom.xml ./
COPY .mvn ./.mvn
COPY mvnw ./
RUN ./mvnw -B -q dependency:go-offline || true
COPY src ./src
RUN ./mvnw -B -DskipTests package

# ---------- runtime ----------
FROM eclipse-temurin:17-jre
WORKDIR /app
RUN groupadd -r ecom && useradd -r -g ecom ecom
COPY --from=build /workspace/target/ecom-java-backend-0.1.0.jar /app/app.jar
USER ecom
EXPOSE 8080
ENV SERVER_PORT=8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD wget -q -O - http://localhost:8080/api/health || exit 1
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
