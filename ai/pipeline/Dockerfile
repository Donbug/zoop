# Collector image. Build context is ai/pipeline/ (the lock installs without ../worker):
#   docker build -f ai/pipeline/Dockerfile --build-arg ZOOP_COLLECTOR_IMAGE_REVISION=$(git rev-parse HEAD) ai/pipeline
ARG UV_VERSION=0.13.6
ARG NODE_IMAGE=node:22-bookworm-slim

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# Retained-HTML extractor dependencies (locked); the runtime copies only node_modules and the node binary.
FROM ${NODE_IMAGE} AS defuddle
WORKDIR /defuddle
COPY src/zoop_ai_pipeline/_defuddle/package.json src/zoop_ai_pipeline/_defuddle/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM python:3.12-slim-trixie AS builder
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/opt/zoop-collector/venv
WORKDIR /build
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable --group container

FROM python:3.12-slim-trixie AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 collector \
    && useradd --uid 10001 --gid collector --home-dir /home/collector --create-home --shell /usr/sbin/nologin collector \
    && install -d -o collector -g collector -m 0700 /var/lib/zoop-collector \
    && install -d -o collector -g collector -m 0755 /etc/zoop-collector

COPY --from=builder /opt/zoop-collector/venv /opt/zoop-collector/venv
COPY --from=defuddle /usr/local/bin/node /usr/local/bin/node
COPY --from=defuddle /defuddle/node_modules /opt/zoop-collector/venv/lib/python3.12/site-packages/zoop_ai_pipeline/_defuddle/node_modules
RUN node --version

ARG ZOOP_COLLECTOR_IMAGE_REVISION=unknown
ENV PATH="/opt/zoop-collector/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ZOOP_COLLECTOR_IMAGE_REVISION=${ZOOP_COLLECTOR_IMAGE_REVISION} \
    ZOOP_COLLECTOR_STATE_ROOT=/var/lib/zoop-collector \
    ZOOP_COLLECTOR_CONFIG_DIR=/etc/zoop-collector \
    ZOOP_STATE_DIR=/var/lib/zoop-reserved/application \
    ZOOP_AI_WORKER_STATE_DIR=/var/lib/zoop-reserved/worker

USER collector
WORKDIR /home/collector
STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/bin/tini", "--", "zoop-ai-collector"]
CMD ["run"]
