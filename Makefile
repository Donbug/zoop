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
WORKER_PYTHON ?= $(BFF_PYTHON)
ARTIFACT_DIR ?= /tmp/zoop-release-artifacts
COMMIT ?=

.PHONY: help projects available-checks config-check tooling-test public-check contracts-check worker-contracts-check bff-types-check docs-check tokens-check secret-check web-install web-typecheck web-test web-build bff-install bff-test bff-build worker-install worker-test worker-build package-artifacts
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
bff-install:
	$(UV) sync --project prototype/bff --frozen --group dev
bff-test:
	$(UV) run --project prototype/bff --no-sync python -m pytest prototype/bff/tests
bff-build:
	$(UV) build --project prototype/bff --out-dir /tmp/zoop-bff-build
worker-test:
	PYTHONPATH=prototype/ai-worker/src $(WORKER_PYTHON) -m pytest prototype/ai-worker/tests
worker-install:
	$(UV) sync --project prototype/ai-worker --frozen --group dev --no-install-project
worker-build:
	$(UV) build --project prototype/ai-worker --out-dir /tmp/zoop-ai-build
package-artifacts:
	$(PYTHON) scripts/package_artifacts.py --root . --output "$(ARTIFACT_DIR)" --commit "$(COMMIT)"
