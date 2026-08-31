# backend/Dockerfile
FROM maven:3.9-eclipse-temurin-17 AS builder
WORKDIR /workspace
COPY pom.xml ./
COPY src ./src
RUN mvn -q -DskipTests package

FROM eclipse-temurin:17-jre
RUN apt-get update \
    && apt-get install -y --no-install-recommends wget \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /workspace/target/*.jar /app/app.jar
EXPOSE 8080
ENTRYPOINT ["java","-jar","/app/app.jar"]
