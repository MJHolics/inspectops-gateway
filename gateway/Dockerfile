# 빌드 단계
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml .
RUN mvn -B -ntp dependency:go-offline
COPY src ./src
RUN mvn -B -ntp -DskipTests package

# 실행 단계 — JRE만
FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /src/target/inspectops-gateway-0.1.0.jar app.jar
EXPOSE 8080
# 컨테이너 메모리 한도를 기준으로 힙을 잡는다 (K8s limits와 맞물림)
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "/app/app.jar"]
