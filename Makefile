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

.PHONY: help projects available-checks config-check tooling-test public-check contracts-check worker-schema-check worker-contracts-check bff-types-check docs-check tokens-check secret-check web-install web-typecheck web-test web-build app-web-install app-web-lint app-web-format-check app-web-build app-web-test bff-install bff-test bff-build worker-install worker-test worker-build pipeline-install pipeline-test pipeline-smoke pipeline-build service-install service-test service-smoke service-pipeline-test service-pipeline-smoke service-openapi-check service-build api-test api-ai-smoke api-build package-artifacts
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
public-check:
	$(if $(PUBLIC_PYTHON),$(PUBLIC_PYTHON),$(UV) run --no-project --with pyyaml --with openpyxl --with openapi-spec-validator $(PYTHON)) scripts/repo_checks.py public
	PYTHONDONTWRITEBYTECODE=1 $(if $(PUBLIC_PYTHON),$(PUBLIC_PYTHON),$(UV) run --no-project --with pyyaml --with openpyxl --with openapi-spec-validator $(PYTHON)) -m unittest discover -s scripts/tests -p test_doc_system.py -v
contracts-check:
	$(if $(CONTRACT_PYTHON),$(CONTRACT_PYTHON),$(UV) run --no-project --with pyyaml --with openapi-spec-validator $(PYTHON)) scripts/repo_checks.py contracts
worker-schema-check:
	$(WORKER_PYTHON) scripts/repo_checks.py worker-schema
worker-contracts-check:
	$(BFF_PYTHON) scripts/repo_checks.py worker-contracts
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
pipeline-install:
	$(UV) sync --project ai/pipeline --frozen --group dev
pipeline-test:
	$(PIPELINE_PYTHON) -m pytest ai/pipeline/tests
pipeline-smoke:
	$(PIPELINE_PYTHON) ai/pipeline/scripts/ingestion_smoke.py
	$(PIPELINE_PYTHON) ai/pipeline/scripts/extraction_smoke.py
	$(PIPELINE_PYTHON) ai/pipeline/scripts/relation_smoke.py
	$(PIPELINE_PYTHON) ai/pipeline/scripts/dependency_smoke.py
.PHONY: pipeline-graph-smoke
# Requires an explicitly configured, isolated empty Neo4j test database.
pipeline-graph-smoke:
	$(PIPELINE_PYTHON) ai/pipeline/scripts/graph_projection_smoke.py
pipeline-build:
	$(UV) build --project ai/pipeline --out-dir /tmp/zoop-ai-pipeline-build
service-install:
	$(UV) sync --project ai/service --frozen --group dev
service-test:
	$(SERVICE_PYTHON) -m pytest ai/service/tests
service-smoke:
	$(SERVICE_PYTHON) ai/service/scripts/service_smoke.py
# S2 extraction jobs and the S3 relation jobs over the real installed pipeline (needs `make pipeline-install` AND `make service-install`; fails, never skips, without them).
service-pipeline-test:
	$(SERVICE_PYTHON) -m pytest ai/service/pipeline_tests
service-pipeline-smoke:
	$(SERVICE_PYTHON) ai/service/scripts/extraction_service_smoke.py
	$(SERVICE_PYTHON) ai/service/scripts/relation_service_smoke.py
.PHONY: service-graph-smoke
# Requires an explicitly configured, isolated empty Neo4j test database.
service-graph-smoke:
	$(SERVICE_PYTHON) ai/service/scripts/graph_service_smoke.py
service-openapi-check:
	$(SERVICE_PYTHON) ai/service/scripts/export_openapi.py --check
service-build:
	$(UV) build --project ai/service --out-dir /tmp/zoop-ai-service-build
# Spring Boot app (api/): needs JDK 21 (JAVA_HOME). Names carry the api- prefix so they are never confused with prototype/bff-* targets.
api-test:
	$(API_GRADLE) test
api-ai-smoke:
	$(SERVICE_PYTHON) api/scripts/ai_contract_gate.py
.PHONY: api-ai-pipeline-smoke
api-ai-pipeline-smoke:
	$(SERVICE_PYTHON) api/scripts/ai_pipeline_gate.py
api-build:
	$(API_GRADLE) assemble
package-artifacts:
	$(PYTHON) scripts/package_artifacts.py --root . --output "$(ARTIFACT_DIR)" --commit "$(COMMIT)"
