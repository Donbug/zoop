FROM eclipse-temurin:21-jdk-alpine AS builder

WORKDIR /workspace

COPY gradlew ./
COPY gradle ./gradle
COPY settings.gradle build.gradle ./

RUN chmod +x gradlew

COPY src ./src

RUN ./gradlew bootJar --no-daemon \
    && JAR_FILE="$(find build/libs -maxdepth 1 -type f -name '*.jar' ! -name '*-plain.jar' -print -quit)" \
    && test -n "$JAR_FILE" \
    && cp "$JAR_FILE" /tmp/app.jar

FROM eclipse-temurin:21-jre-alpine AS runtime

RUN addgroup -S zoop \
    && adduser -S -G zoop zoop

WORKDIR /app

COPY --from=builder --chown=zoop:zoop /tmp/app.jar ./app.jar

USER zoop

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "/app/app.jar"]