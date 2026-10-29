# App-local tools own their dependencies; this file only routes commands.
.DEFAULT_GOAL := help
PYTHON ?= python3
UV ?= uv
PNPM ?= pnpm
CONFIG_PYTHON ?=
DOC_PYTHON ?=
CONTRACT_PYTHON ?=
PUBLIC_PYTHON ?=
BFF_PYTHON ?= prototype/bff/.venv/bin/python
WORKER_PYTHON ?= ai/worker/.venv/bin/python
PIPELINE_PYTHON ?= ai/pipeline/.venv/bin/python
SERVICE_PYTHON ?= ai/service/.venv/bin/python
API_GRADLE ?= ./api/gradlew -p api --console=plain
ARTIFACT_DIR ?= /tmp/zoop-release-artifacts
COMMIT ?=

.PHONY: help projects available-checks config-check tooling-test chat-live-spike-report chat-operations-readiness public-check contracts-check worker-schema-check worker-contracts-check evaluation-verification-check bff-types-check docs-check tokens-check secret-check web-install web-typecheck web-test web-build app-web-install app-web-lint app-web-format-check app-web-build app-web-test bff-install bff-test bff-build worker-install worker-test worker-build pipeline-install pipeline-test pipeline-smoke pipeline-build service-install service-test service-smoke service-pipeline-test service-pipeline-smoke service-openapi-check service-build api-test api-ai-smoke api-ai-chat-smoke api-build package-artifacts
help:
	@$(PYTHON) scripts/repo_checks.py help
projects:
	@$(PYTHON) scripts/repo_checks.py projects
available-checks:
	@$(PYTHON) scripts/repo_checks.py available
config-check:
	$(if $(CONFIG_PYTHON),$(CONFIG_PYTHON),$(UV) run --no-project --with pyyaml $(PYTHON)) scripts/repo_checks.py config

tooling-test:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s scripts/tests -v
CHAT_LIVE_SPIKE_EVIDENCE ?=
CHAT_LIVE_SPIKE_REPORT ?=
chat-live-spike-report:
	@test -n "$(CHAT_LIVE_SPIKE_EVIDENCE)" || { printf '%s\n' 'Set CHAT_LIVE_SPIKE_EVIDENCE to the approved content-free evidence JSON.'; exit 2; }
	$(PYTHON) scripts/chat_live_spike_report.py "$(CHAT_LIVE_SPIKE_EVIDENCE)" $(if $(CHAT_LIVE_SPIKE_REPORT),--output "$(CHAT_LIVE_SPIKE_REPORT)")
CHAT_OPERATIONS_MANIFEST ?=
CHAT_OPERATIONS_REPORT ?=
chat-operations-readiness:
	@test -n "$(CHAT_OPERATIONS_MANIFEST)" || { printf '%s\n' 'Set CHAT_OPERATIONS_MANIFEST to the content-free readiness manifest.'; exit 2; }
	@test -n "$(CHAT_LIVE_SPIKE_EVIDENCE)" || { printf '%s\n' 'Set CHAT_LIVE_SPIKE_EVIDENCE to the approved content-free evidence JSON.'; exit 2; }
	$(PYTHON) scripts/chat_operations_readiness.py "$(CHAT_OPERATIONS_MANIFEST)" "$(CHAT_LIVE_SPIKE_EVIDENCE)" $(if $(CHAT_OPERATIONS_REPORT),--output "$(CHAT_OPERATIONS_REPORT)")
public-check:
	$(if $(PUBLIC_PYTHON),$(PUBLIC_PYTHON),$(UV) run --no-project --with pyyaml --with openpyxl --with openapi-spec-validator $(PYTHON)) scripts/repo_checks.py public
	PYTHONDONTWRITEBYTECODE=1 $(if $(PUBLIC_PYTHON),$(PUBLIC_PYTHON),$(UV) run --no-project --with pyyaml --with openpyxl --with openapi-spec-validator $(PYTHON)) -m unittest discover -s scripts/tests -p test_doc_system.py -v
contracts-check:
	$(if $(CONTRACT_PYTHON),$(CONTRACT_PYTHON),$(UV) run --no-project --with pyyaml --with openapi-spec-validator $(PYTHON)) scripts/repo_checks.py contracts
worker-schema-check:
	$(WORKER_PYTHON) scripts/repo_checks.py worker-schema
worker-contracts-check:
	$(BFF_PYTHON) scripts/repo_checks.py worker-contracts
evaluation-verification-check:
	$(WORKER_PYTHON) -B scripts/repo_checks.py evaluation-verification
bff-types-check:
	PNPM=$(PNPM) $(BFF_PYTHON) scripts/repo_checks.py bff-types
docs-check:
	$(if $(DOC_PYTHON),$(DOC_PYTHON),$(UV) run --no-project --with pyyaml --with openpyxl $(PYTHON)) scripts/repo_checks.py docs
tokens-check:
	$(PYTHON) scripts/repo_checks.py tokens
secret-check:
	$(PYTHON) scripts/repo_checks.py secrets

web-install:
	$(PNPM) --dir prototype/web install --frozen-lockfile
web-typecheck:
	$(PNPM) --dir prototype/web typecheck
web-test:
	$(PNPM) --dir prototype/web test
web-build:
	$(PNPM) --dir prototype/web build
# Production frontend (root web/, pnpm 10 per web/package.json packageManager). Names carry the app-web- prefix so they are never confused with the prototype/web targets above.
# HUSKY=0 keeps web's prepare script from installing git hooks during install.
app-web-install:
	HUSKY=0 $(PNPM) --dir web install --frozen-lockfile
app-web-lint:
	$(PNPM) --dir web lint
app-web-format-check:
	$(PNPM) --dir web format:check
app-web-build:
	$(PNPM) --dir web build
app-web-test:
	$(PNPM) --dir web test
bff-install:
	$(UV) sync --project prototype/bff --frozen --group dev
bff-test:
	$(UV) run --project prototype/bff --no-sync python -m pytest prototype/bff/tests
bff-build:
	$(UV) build --project prototype/bff --out-dir /tmp/zoop-bff-build
worker-install:
	$(UV) sync --project ai/worker --frozen --group dev
worker-test:
	$(WORKER_PYTHON) -m pytest ai/worker/tests
worker-build:
	$(UV) build --project ai/worker --out-dir /tmp/zoop-ai-build
# Native, replay-only pipeline (collection, ingestion, S2-2, S3, S4, graph, handoff): public dependencies only, no private Git access or token.
pipeline-install:
	$(UV) sync --project ai/pipeline --frozen --group dev
pipeline-test:
	$(PIPELINE_PYTHON) -m pytest ai/pipeline/tests -n 4 --dist loadfile --durations=30
pipeline-smoke:
	time $(PIPELINE_PYTHON) ai/pipeline/scripts/ingestion_smoke.py
	time $(PIPELINE_PYTHON) ai/pipeline/scripts/round_smoke.py
	time $(PIPELINE_PYTHON) ai/pipeline/scripts/collection_smoke.py
	time $(PIPELINE_PYTHON) ai/pipeline/scripts/extraction_smoke.py
	time $(PIPELINE_PYTHON) ai/pipeline/scripts/round_enqueue_smoke.py
	time $(PIPELINE_PYTHON) ai/pipeline/scripts/relation_smoke.py
	time $(PIPELINE_PYTHON) ai/pipeline/scripts/dependency_smoke.py
	time $(PIPELINE_PYTHON) ai/pipeline/scripts/graph_handoff_smoke.py
	time $(PIPELINE_PYTHON) ai/pipeline/scripts/handoff_exposure_smoke.py
	time $(PIPELINE_PYTHON) ai/pipeline/scripts/issue_summary_smoke.py
.PHONY: pipeline-collection-demo
# Keeps synthetic loopback collection, prepared documents and exports; never collects external news.
COLLECTION_DEMO_DIR ?= /tmp/zoop-collection-demo
pipeline-collection-demo:
	$(PIPELINE_PYTHON) ai/pipeline/scripts/collection_smoke.py --output-dir "$(COLLECTION_DEMO_DIR)"
HANDOFF_PACKAGE_DIR ?=
.PHONY: pipeline-handoff-package pipeline-handoff-package-verify
# Retained synthetic handoff, created in a new location; no Neo4j, cloud or model calls.
pipeline-handoff-package:
	@test -n "$(HANDOFF_PACKAGE_DIR)" || { echo "set HANDOFF_PACKAGE_DIR=/abs/real/new-dir"; exit 2; }
	$(PIPELINE_PYTHON) ai/pipeline/scripts/graph_handoff_smoke.py --write-package "$(HANDOFF_PACKAGE_DIR)"
pipeline-handoff-package-verify:
	@test -n "$(HANDOFF_PACKAGE_DIR)" || { echo "set HANDOFF_PACKAGE_DIR=/abs/real/package-dir"; exit 2; }
	$(PIPELINE_PYTHON) ai/pipeline/scripts/graph_handoff_smoke.py --verify-package "$(HANDOFF_PACKAGE_DIR)"
.PHONY: pipeline-graph-smoke
# Requires an explicitly configured, isolated empty Neo4j test database.
pipeline-graph-smoke:
	$(PIPELINE_PYTHON) ai/pipeline/scripts/graph_projection_smoke.py
.PHONY: pipeline-graph-tls-smoke
# Local only, explicit opt-in: creates its own throwaway PKI and private loopback Neo4j containers from the digest-pinned, already pulled neo4j:5.26.32 image
# (never pulls, never touches foreign containers), proves preflight/init and the full graph smoke over bolt+s, and removes exactly what it created.
pipeline-graph-tls-smoke:
	$(PIPELINE_PYTHON) ai/pipeline/scripts/graph_tls_smoke.py --manage-containers
pipeline-build:
	$(UV) build --project ai/pipeline --out-dir /tmp/zoop-ai-pipeline-build
service-install:
	$(UV) sync --project ai/service --frozen --group dev
service-test:
	$(SERVICE_PYTHON) -m pytest ai/service/tests -n 4 --dist load --durations=30
service-smoke:
	$(SERVICE_PYTHON) ai/service/scripts/service_smoke.py
# S2 extraction jobs and the S3 relation jobs over the real installed pipeline (needs `make pipeline-install` AND `make service-install`; fails, never skips, without them).
service-pipeline-test:
	$(SERVICE_PYTHON) -m pytest ai/service/pipeline_tests
service-pipeline-smoke:
	$(SERVICE_PYTHON) ai/service/scripts/extraction_service_smoke.py
	$(SERVICE_PYTHON) ai/service/scripts/relation_service_smoke.py
.PHONY: service-graph-smoke service-handoff-smoke
# Requires an explicitly configured, isolated empty Neo4j test database.
service-graph-smoke:
	$(SERVICE_PYTHON) ai/service/scripts/graph_service_smoke.py
# The read-only handoff routes over the real installed zoop-ai-handoff and an actual two-S3-job synthetic world (needs `make pipeline-install` AND `make service-install`; no Neo4j; fails, never skips).
service-handoff-smoke:
	$(SERVICE_PYTHON) ai/service/scripts/handoff_service_smoke.py
service-openapi-check:
	$(SERVICE_PYTHON) ai/service/scripts/export_openapi.py --check
service-build:
	$(UV) build --project ai/service --out-dir /tmp/zoop-ai-service-build
# Spring Boot app (api/): needs JDK 21 (JAVA_HOME). Names carry the api- prefix so they are never confused with prototype/bff-* targets.
api-test:
	$(API_GRADLE) test
api-ai-smoke:
	$(SERVICE_PYTHON) api/scripts/ai_contract_gate.py
# Real Java ChatModelStages -> ai/service -> installed zoop-ai-chat over an authored replay fixture (needs `make service-install`;
# no model call, no PostgreSQL; fails, never skips).
api-ai-chat-smoke:
	$(SERVICE_PYTHON) api/scripts/ai_chat_gate.py
.PHONY: api-ai-pipeline-smoke
api-ai-pipeline-smoke:
	$(SERVICE_PYTHON) api/scripts/ai_pipeline_gate.py
# Real installed zoop-ai-handoff/-ingest -> built jar -> PostgreSQL and evidence HTTP reads; no provider/model calls. Only the isolated smoke harness activates a synthetic version. Needs `make pipeline-install api-build` first (not run
# automatically; fails, never skips) and DB_URL/DB_USERNAME/DB_PASSWORD for a dedicated EMPTY loopback database (no default; the script refuses a non-empty one and never cleans it).
# Optional: GRAPH_IMPORT_PSQL_CONTAINER (docker exec psql instead of host psql), GRAPH_IMPORT_DB_USER, GRAPH_IMPORT_DB_NAME (default to DB_USERNAME and the DB_URL database).
API_JAR ?= api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar
.PHONY: api-graph-handoff-import-smoke
api-graph-handoff-import-smoke:
	$(PIPELINE_PYTHON) api/scripts/graph_handoff_import_smoke.py --jar $(API_JAR) --handoff-cli "$(CURDIR)/ai/pipeline/.venv/bin/zoop-ai-handoff" --ingest-cli "$(CURDIR)/ai/pipeline/.venv/bin/zoop-ai-ingest" $(if $(GRAPH_IMPORT_PSQL_CONTAINER),--psql-container $(GRAPH_IMPORT_PSQL_CONTAINER)) $(if $(GRAPH_IMPORT_DB_USER),--db-user $(GRAPH_IMPORT_DB_USER)) $(if $(GRAPH_IMPORT_DB_NAME),--db-name $(GRAPH_IMPORT_DB_NAME))
# Real admin HTTP -> durable PostgreSQL queue -> installed S2/S3 replay. Requires a built jar, frozen AI environments and
# a cached PostgreSQL image. Output must be a fresh directory outside the checkout; no provider calls or public activation.
.PHONY: api-analyze-plan-smoke
api-analyze-plan-smoke:
	@test -n "$(ANALYZE_PLAN_SMOKE_OUTPUT)" || { printf '%s\n' 'Set ANALYZE_PLAN_SMOKE_OUTPUT to a fresh directory outside the checkout.'; exit 2; }
	$(SERVICE_PYTHON) api/scripts/analyze_plan_queue_smoke.py --jar "$(API_JAR)" --output "$(ANALYZE_PLAN_SMOKE_OUTPUT)"
# Temporary local graph API with bundled fixtures. Requires a built jar and a locally cached PostgreSQL image; never pulls.
.PHONY: api-graph-dev
api-graph-dev:
	$(PYTHON) api/scripts/local_graph_dev.py --jar "$(API_JAR)" $(if $(LOCAL_GRAPH_DEV_PORT),--server-port $(LOCAL_GRAPH_DEV_PORT)) $(if $(LOCAL_GRAPH_DEV_IMAGE),--image $(LOCAL_GRAPH_DEV_IMAGE))
api-build:
	$(API_GRADLE) assemble
package-artifacts:
	$(PYTHON) scripts/package_artifacts.py --root . --output "$(ARTIFACT_DIR)" --commit "$(COMMIT)"

# Local read-only PR discovery; state and acknowledgements stay outside the repository.
PR_WATCH_STATE ?= $(HOME)/.local/state/zoop-pr-watchdog
PR_WATCH_INTERVAL ?= 300
.PHONY: pr-watch-once pr-watch-status pr-watch
pr-watch-once:
	$(PYTHON) scripts/pr_watchdog.py --state-dir "$(PR_WATCH_STATE)" --once
pr-watch-status:
	$(PYTHON) scripts/pr_watchdog.py --state-dir "$(PR_WATCH_STATE)" --status
pr-watch:
	$(PYTHON) scripts/pr_watchdog.py --state-dir "$(PR_WATCH_STATE)" --interval "$(PR_WATCH_INTERVAL)" --watch
