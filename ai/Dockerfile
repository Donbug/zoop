ARG UV_VERSION=0.13.6

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:3.12-slim-trixie AS builder

COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /opt/zoop

# Install the S1 worker using its locked production dependencies.
COPY worker/pyproject.toml worker/uv.lock ./worker/
COPY worker/src ./worker/src

RUN uv sync \
    --project worker \
    --frozen \
    --no-dev \
    --no-editable

# Install the internal HTTP service using its locked production dependencies.
# The worker project remains available because the service lock references it
# as a development-only local source.
COPY service/pyproject.toml service/uv.lock ./service/
COPY service/src ./service/src

RUN uv sync \
    --project service \
    --frozen \
    --no-dev \
    --no-editable

# Read-only observation and handoff routes execute the installed native pipeline.
COPY pipeline/pyproject.toml pipeline/uv.lock ./pipeline/
COPY pipeline/src ./pipeline/src

RUN uv sync \
    --project pipeline \
    --frozen \
    --no-dev \
    --no-editable

FROM python:3.12-slim-trixie AS runtime

RUN groupadd --system zoop \
    && useradd \
        --system \
        --gid zoop \
        --home-dir /nonexistent \
        --shell /usr/sbin/nologin \
        zoop \
    && mkdir -p \
        /var/lib/zoop-ai/service \
        /var/lib/zoop-ai/worker \
    && chown -R zoop:zoop /var/lib/zoop-ai \
    && chmod 0700 \
        /var/lib/zoop-ai/service \
        /var/lib/zoop-ai/worker

WORKDIR /opt/zoop

COPY --from=builder --chown=zoop:zoop \
    /opt/zoop/worker/.venv \
    /opt/zoop/worker/.venv

COPY --from=builder --chown=zoop:zoop \
    /opt/zoop/service/.venv \
    /opt/zoop/service/.venv

COPY --from=builder --chown=zoop:zoop \
    /opt/zoop/pipeline/.venv \
    /opt/zoop/pipeline/.venv

COPY --chown=zoop:zoop \
    worker/fixtures/contracts/synthetic-document/grants.json \
    /opt/zoop/fixtures/synthetic-document/grants.json

COPY --chown=zoop:zoop \
    worker/fixtures/contracts/synthetic-document/replay.json \
    /opt/zoop/fixtures/synthetic-document/replay.json

ENV PATH="/opt/zoop/service/.venv/bin:/opt/zoop/worker/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ZOOP_AI_SERVICE_PORT=8000 \
    ZOOP_AI_SERVICE_STATE_DIR=/var/lib/zoop-ai/service \
    ZOOP_AI_WORKER_STATE_DIR=/var/lib/zoop-ai/worker \
    ZOOP_AI_SERVICE_WORKER_COMMAND=/opt/zoop/worker/.venv/bin/zoop-ai \
    ZOOP_AI_SERVICE_GRANTS=/opt/zoop/fixtures/synthetic-document/grants.json \
    ZOOP_AI_SERVICE_REPLAY=/opt/zoop/fixtures/synthetic-document/replay.json


USER zoop

EXPOSE 8000

HEALTHCHECK \
    --interval=30s \
    --timeout=5s \
    --start-period=30s \
    --retries=3 \
    CMD ["python", "-c", "import socket; connection = socket.create_connection(('127.0.0.1', 8000), 3); connection.close()"]

ENTRYPOINT ["/opt/zoop/service/.venv/bin/zoop-ai-service"]
