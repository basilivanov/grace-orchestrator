# Resubmission — TZ 01 LINT GUARDRAILS review

WEB_ORCH_REPORT: RESUBMISSION 01_LINT_GUARDRAILS
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 4b4774e3e2eac98ed3b0c119a22c88a71461e7ec
WEB_ORCH_CHECKS: PASS

Implemented only the requested review fix:

- Gated the `GRC012` violation with `_rule_enabled("GRC012", rules_enabled)`.
  Default all-rules behavior still reports oversized public/private sync and
  async functions, while private functions remain exempt from `GRC010/GRC011`.
- Added deterministic coverage proving an oversized private helper is omitted
  when only `GRC100` is selected and reported when `GRC012` is selected.

Checks:

- `.venv/bin/python -m pytest tests/grace_control/core/test_grace_lint.py -q` —
  **39 passed**.
- `.venv/bin/python scripts/grace_lint.py src/grace_control/tools/grace_lint/checker.py` — **PASS**.
- `git diff --check` — **PASS**.
- `make lint` — the repository default `.venv/bin/python` cannot import Ruff.
  Re-run as `make lint PYTHON=python3` reaches Ruff and reports 452 existing
  repository violations; no unrelated files were changed and no
  `GRC005/GRC012` suppression was added.
