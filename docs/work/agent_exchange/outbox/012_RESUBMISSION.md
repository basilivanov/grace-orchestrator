# RESUBMISSION 012 — Stage 06 review fixes

WEB_ORCH_REPORT: RESUBMISSION 012
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 1d68960ce78982cd5c30df6e04a9df0bbd8ca7d8
WEB_ORCH_CHECKS: PASS

Implemented only the requested review fixes:

- uncertain/malformed maintenance ownership now yields an empty safe candidate set; real cleanup preserves the terminal-looking worktree while complete evidence still permits stale cleanup;
- Hub mutations verify registry/runtime identity before mutation transport, and local controls derive canonical runtime identity instead of trusting the request body;
- canonical requested/completed/failed audit persistence is strict and visible as `AUDIT_INTEGRITY_FAILURE` when it cannot be written;
- OpenAPI mutation parameters preserve declared path and query values, with missing/undeclared selectors rejected before dispatch.

Checks:

- focused Stage 06 and review regressions: `22 passed`;
- relevant isolation/read/UI/explorer/auth/maintenance/packet/merge/supervisor suite: `154 passed, 2 skipped`;
- Ruff: PASS;
- `py_compile`: PASS;
- `git diff --check`: PASS;
- changed/new-file GRACE lint: PASS.

The full repository GRACE lint still reports pre-existing legacy canon violations outside this change scope.
