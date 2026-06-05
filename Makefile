PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
GRACE_DB_URL ?= sqlite:////tmp/grace-orchestrator-export/test_grace.db

.PHONY: help install dev test test-all lint format docs docs-check clean

help:
	@echo "GRACE Control Plane — make targets"
	@echo "  make install     Install runtime + dev deps"
	@echo "  make dev         Install with legacy prefect extra"
	@echo "  make test        Run unit + integration tests"
	@echo "  make test-all    Run all tests (no deselects)"
	@echo "  make lint        Run ruff + grace_lint"
	@echo "  make format      Black + isort"
	@echo "  make docs        Regenerate docs/openapi.json, state-diagram.md, packet-states.md"
	@echo "  make docs-check  Fail (exit 1) if generated docs drift from disk — for CI"
	@echo "  make clean       Remove generated docs + caches"

install:
	$(PIP) install -e .

dev:
	$(PIP) install -e ".[legacy,dev]"

test:
	GRACE_DB_URL=$(GRACE_DB_URL) $(PYTHON) -m pytest tests/grace_control/ \
		--deselect tests/grace_control/core/test_recovery_real_db.py::test_full_multiwave_acceptance_recovery_real_db \
		-q

test-all:
	GRACE_DB_URL=$(GRACE_DB_URL) $(PYTHON) -m pytest tests/grace_control/ -q

lint:
	$(PYTHON) -m ruff check src/grace_control/
	$(PYTHON) scripts/grace_lint.py src/

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

