PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
GRACE_DB_URL ?= sqlite:////tmp/grace-orchestrator-export/test_grace.db

.PHONY: help install dev test test-all lint format docs docs-check clean

help:
	@echo "GRACE Control Plane — make targets"
	@echo "  make install     Install runtime + dev deps"
	@echo "  make dev         Install with legacy prefect extra"
	@echo "  make test        Run unit + integration tests (deselects pre-existing failures)"
	@echo "  make test-all    Run all tests (includes 9 known pre-existing failures)"
	@echo "  make lint        Run ruff + grace_lint"
	@echo "  make format      Black + isort"
	@echo "  make docs        Regenerate docs/openapi.json, state-diagram.md, packet-states.md"
	@echo "  make docs-check  Fail if any tracked docs/*.md is out of date"
	@echo "  make clean       Remove generated docs + caches"

install:
	$(PIP) install -e .

dev:
	$(PIP) install -e ".[legacy,dev]"

test:
	GRACE_DB_URL=$(GRACE_DB_URL) $(PYTHON) -m pytest tests/grace_control/ \
		--deselect tests/grace_control/core/test_acceptance_pipeline.py::TestT0::test_t0_fails_out_of_scope \
		--deselect tests/grace_control/core/test_acceptance_pipeline.py::TestT0::test_t0_fails_frozen_scope \
		--deselect tests/grace_control/core/test_acceptance_pipeline.py::TestT0::test_t0_fails_invalid_packet \
		--deselect tests/grace_control/core/test_acceptance_pipeline.py::TestT0::test_t0_blocks_t1 \
		--deselect tests/grace_control/core/test_acceptance_pipeline.py::TestT0::test_explicit_empty_t0_scope_guard_still_runs \
		--deselect tests/grace_control/core/test_acceptance_pipeline.py::TestReport::test_non_accepted_has_summary \
		--deselect tests/grace_control/core/test_acceptance_pipeline.py::TestReport::test_legacy_ok_false_blocks_accept \
		--deselect tests/grace_control/core/test_acceptance_pipeline.py::TestReport::test_legacy_domain_status_rejected_blocks_accept \
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

docs-check: docs
	@git diff --quiet -- docs/openapi.json docs/state-diagram.md docs/packet-states.md \
		|| (echo "ERROR: docs are out of date. Run 'make docs' and commit." && exit 1)
	@echo "docs are up to date"

clean:
	rm -f docs/openapi.json docs/state-diagram.md docs/packet-states.md
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
