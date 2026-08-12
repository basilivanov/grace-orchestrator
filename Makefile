PYTHON ?= $(shell if test -x .venv/bin/python; then echo .venv/bin/python; elif command -v python3 >/dev/null 2>&1; then command -v python3; else command -v python; fi)
PIP ?= $(shell if test -x .venv/bin/pip; then echo .venv/bin/pip; elif command -v pip3 >/dev/null 2>&1; then command -v pip3; else command -v pip; fi)
GRACE_DB_URL ?= sqlite:////tmp/grace-orchestrator-export/test_grace.db
GRACE_PLANNING_LOGS_ROOT ?= /tmp/grace-orchestrator-export/planning_logs
CI_LINT_SCOPE := src/grace_control tests scripts
CI_LINT_BASELINE := .grace/ci_lint_baseline.json

.PHONY: help install dev test test-live lint hygiene format docs docs-check ci clean

help:
	@echo "GRACE Control Plane — make targets"
	@echo "  make install     Install runtime + dev deps"
	@echo "  make dev         Install dev deps"
	@echo "  make test        Run deterministic CI tests (external/live excluded)"
	@echo "  make test-live   Run external tests + live scenarios (requires a running system)"
	@echo "  make lint        Run Ruff + GraceLint over the supported CI scope"
	@echo "  make hygiene     Run the canonical repository-hygiene gate"
	@echo "  make ci          Run all CI gates (test + lint + docs-check + hygiene)"
	@echo "  make format      Black + isort"
	@echo "  make docs        Regenerate docs/openapi.json, state-diagram.md, packet-states.md"
	@echo "  make docs-check  Fail (exit 1) if generated docs drift — for CI"
	@echo "  make clean       Remove generated docs + caches"

install:
	$(PIP) install -e .

dev:
	$(PIP) install -e ".[dev]"

test:
	@mkdir -p "$(GRACE_PLANNING_LOGS_ROOT)"
	GRACE_DB_URL=$(GRACE_DB_URL) GRACE_PLANNING_LOGS_ROOT=$(GRACE_PLANNING_LOGS_ROOT) $(PYTHON) -m pytest tests -m "not external and not live" -q

test-live:
	@echo "Running external/live pytest tests and standalone live scenarios; an API/worker/browser environment is required."
	$(PYTHON) -m pytest tests -m "external or live" -q
	@for test_file in tests/live/test_*.py; do \
		echo "--- $$test_file"; \
		PYTHONPATH=src $(PYTHON) "$$test_file"; \
	done

lint:
	$(PYTHON) scripts/ci_lint_baseline.py --baseline $(CI_LINT_BASELINE) --scope $(CI_LINT_SCOPE)

hygiene:
	$(PYTHON) scripts/ci_repo_hygiene.py

ci: test lint docs-check hygiene

format:
	$(PYTHON) -m black src/grace_control/ tests/grace_control/
	$(PYTHON) -m isort src/grace_control/ tests/grace_control/

docs:
	GRACE_DB_URL=$(GRACE_DB_URL) $(PYTHON) scripts/generate_docs.py

docs-check:
	GRACE_DB_URL=$(GRACE_DB_URL) $(PYTHON) scripts/generate_docs.py --check

clean:
	rm -f docs/openapi.json docs/state-diagram.md docs/packet-states.md
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
