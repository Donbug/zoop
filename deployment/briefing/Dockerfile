ARG API_IMAGE=zoop-api:ci
FROM ${API_IMAGE} AS api
FROM eclipse-temurin:21-jre-jammy AS java
FROM python:3.12-slim-trixie

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    JAVA_HOME=/opt/java/openjdk PATH=/opt/java/openjdk/bin:$PATH \
    PYTHONPATH=/opt/zoop/briefing/scripts:/opt/zoop/briefing/ai/service/src \
    BRIEFING_SERVER_WORK_ROOT=/mnt/zoop-ops/briefing-server-v1 \
    BRIEFING_USAGE_ARTIFACT_ROOT=/mnt/zoop-artifacts
WORKDIR /opt/zoop/briefing
COPY --from=java /opt/java/openjdk /opt/java/openjdk
COPY --from=api /app/app.jar ./app.jar
COPY deployment/briefing/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --requirement requirements.txt
COPY scripts/*.py ./scripts/
COPY ai/service/src/zoop_ai_service/grants.py ./ai/service/src/zoop_ai_service/grants.py
COPY ai/service/src/zoop_ai_service/__init__.py ./ai/service/src/zoop_ai_service/__init__.py
COPY api/src/main/resources/briefing/prompts ./api/src/main/resources/briefing/prompts
COPY deployment/briefing/entrypoint.py ./entrypoint.py
USER 100:101
ENTRYPOINT ["python","/opt/zoop/briefing/entrypoint.py"]
