FROM eclipse-temurin:21-jdk-alpine AS builder

WORKDIR /workspace

COPY api/gradlew ./
COPY api/gradle ./gradle
COPY api/settings.gradle api/build.gradle ./

RUN chmod +x gradlew

COPY api/src ./src

RUN ./gradlew bootJar --no-daemon \
    && JAR_FILE="$(find build/libs -maxdepth 1 -type f -name '*.jar' ! -name '*-plain.jar' -print -quit)" \
    && test -n "$JAR_FILE" \
    && cp "$JAR_FILE" /tmp/app.jar

FROM eclipse-temurin:21-jre-jammy AS java
FROM python:3.12-slim-trixie AS runtime

ENV JAVA_HOME=/opt/java/openjdk PATH=/opt/java/openjdk/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=java /opt/java/openjdk /opt/java/openjdk
COPY deployment/briefing/requirements.txt /opt/zoop/requirements.txt
RUN pip install --no-cache-dir --requirement /opt/zoop/requirements.txt \
    && groupadd --gid 101 zoop && useradd --uid 100 --gid 101 --system --no-create-home zoop
COPY ai/pipeline/src /opt/zoop/ai/pipeline/src
RUN printf '%s\n' '#!/usr/local/bin/python3' 'import sys' 'sys.path.insert(0,"/opt/zoop/ai/pipeline/src")' 'from zoop_ai_pipeline.ingestion_cli import main' 'raise SystemExit(main())' > /usr/local/bin/zoop-ai-ingest \
    && chmod 0555 /usr/local/bin/zoop-ai-ingest \
    && chown 100:101 /tmp && chmod 0700 /tmp

WORKDIR /app

COPY --from=builder --chown=zoop:zoop /tmp/app.jar ./app.jar

USER 100:101

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "/app/app.jar"]
