# Submission — TZ 01 LINT GUARDRAILS

WEB_ORCH_REPORT: SUBMISSION 01_LINT_GUARDRAILS
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 5aab22ca6e66a9f862d16d7b50957ff487f8bd39
WEB_ORCH_CHECKS: PASS

Implemented only the requested lint-guardrail changes:

- `_check_functions()` keeps one AST walk and computes the existing
  `len(source) // 4` estimate before the private-name guard, so `GRC012`
  applies to public, private and async functions. `GRC010/GRC011` remain
  limited to public functions; `--skip-function-contracts` skips only those
  contract checks.
- Added private oversized, async oversized, private-contract exemption and
  exact 4000/4001 boundary tests. Existing public oversized coverage remains.
- Added the missing checker contract for `load_allowlist`, removed the stale
  `packet_executor.py` `GRC108` allowlist rationale, and added only narrowly
  scoped self-referential allowlist entries for the checker’s textual rule
  implementations. No `GRC005` or `GRC012` allowlist entry was added.

Checks:

- `.venv/bin/python -m pytest tests/grace_control/core/test_grace_lint.py -q` —
  **38 passed**.
- `.venv/bin/python scripts/grace_lint.py src/grace_control/tools/grace_lint/checker.py` — **PASS**.
- Changed-file Ruff, `python3 -m py_compile` and `git diff --check` — **PASS**.
- `make lint` could not start its lint gates because `.venv/bin/python` has no
  `ruff` module. The supported system Ruff equivalent reports 452 pre-existing
  repository violations; changed checker/test files pass targeted Ruff.

The corrected repository scan exposes these existing `GRC012` findings; they
were not suppressed or refactored in this packet:

- `src/grace_control/adapters/packet_executor.py:369` — `execute`, ~4343;
- `src/grace_control/adapters/packet_executor.py:1459` — `_call_executor`, ~6062;
- `src/grace_control/core/plan_compiler.py:422` — `compile_plan`, ~4152;
- `src/grace_control/services/admin_control_center.py:1083` — `_packet_page`, ~4094;
- `src/grace_control/services/merge_service.py:127` — `merge_packet`, ~6577.
