WEB_ORCH_REPORT: RESUBMISSION 006
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 22766e56d1a9942cc9a024d395963a8d2c6632ee
WEB_ORCH_CHECKS: PASS

Review fixes are complete. Registered worktrees now fail closed when DB
ownership is unavailable or uncertain. Parallel ACCEPTED merges require the
exact parallel lease fencing identity before any target mutation. The TZ006
integration proof now covers real concurrent Workers/API routes, file-backed
SQLite, real git worktrees, serialized target mutations, waits, dependencies,
stale-base outcomes, crash recovery, and concurrency=1.

Checks: TZ03/TZ04/TZ05/TZ06 plus worker/supervisor/crash set — 80 passed;
migration/schema/executor/recovery set — 82 passed; TZ006 — 12 passed;
py_compile, Ruff, applicable GRACE lint, and git diff --check — PASS.
Report commit: 0b2da27.
