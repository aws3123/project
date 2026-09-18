FROM maven:3.9.9-eclipse-temurin-17 AS dependencies

WORKDIR /workspace
COPY pom.xml ./
RUN mvn -B -ntp dependency:go-offline

FROM dependencies AS build

COPY src ./src
RUN mvn -B -ntp -DskipTests package \
    && find target -maxdepth 1 -type f -name '*.jar' -print -quit | xargs -r -I{} cp "{}" /tmp/app.jar

FROM eclipse-temurin:17.0.14_7-jre-jammy AS runtime

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 sentinel \
    && useradd --system --uid 10001 --gid sentinel --home-dir /app --shell /usr/sbin/nologin sentinel

WORKDIR /app
COPY --from=build --chown=sentinel:sentinel /tmp/app.jar /app/app.jar

USER sentinel
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
