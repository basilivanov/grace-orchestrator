# 06_ADMIN_CONTROLS_ROUTER resubmission

WEB_ORCH_REPORT: RESUBMISSION 06_ADMIN_CONTROLS_ROUTER
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 911b724f995758e7414ef6cdd67efc973a1f121b
WEB_ORCH_CHECKS: PASS

## Review fixes

Only the review blocker was addressed:

- `request.app.__dict__["state"]` is now the supported `request.app.state` access.
- Split-string maintenance lookups are now direct `_maintenance_control_service.state()` and `.state_directory_summary(...)` calls.
- Added one narrow, documented `GRC103` allowlist entry for this router's read-only app/service state access. No `GRC005` or `GRC012` suppression was added, and no identifier obfuscation remains in the touched facade.

Changed files are limited to `src/grace_control/api/routers/admin_controls.py` and `.grace/lint_allowlist.yaml`. Routes, aliases, signatures, response/status behavior, audit flow, maintenance safety and OpenAPI dispatch are unchanged.

## Verification

- Focused Stage 06, Stage 06 review seams, Stage 07/matrix, admin-router, OpenAPI, maintenance and legacy compatibility tests: **106 passed, 1 skipped**.
- Parent/resubmission route comparison: exactly 10 declarations; `(path, method)` sets and route function signatures equal.
- Parent/resubmission generated-doc/OpenAPI diagnostics: normalized output equal; both show only the existing drift in `docs/openapi.json`, `docs/state-diagram.md`, and `docs/packet-states.md`.
- Targeted Ruff: PASS.
- Targeted `python3 scripts/grace_lint.py` for all five router modules, including the allowlist: PASS.
- Targeted `py_compile`: PASS.
- `git diff --check`: PASS.

No tests or assertions were weakened. No next task is proposed.
