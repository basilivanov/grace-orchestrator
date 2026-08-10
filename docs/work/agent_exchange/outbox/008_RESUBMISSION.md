# Task 008 resubmission

WEB_ORCH_REPORT: RESUBMISSION 008
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 7da5800d8f4abb71be96676bff4f6028dd382aa0
WEB_ORCH_CHECKS: PASS

## Review fixes

- Re-applied the filesystem secret-path policy to the resolved path, blocking
  in-root symlink aliases to `.env` and other denied paths.
- Added a bounded, timeout-aware Git subprocess reader and routed the Admin
  Git read surface through it, preserving truncation metadata and safe ref/path
  validation.
- Separated the GRACE runtime `code_sha` from the target repository `target_head`.

## Checks

- Stage 02 acceptance: 8 passed.
- Related Admin/Trace/Events/Diagnostics regressions: 117 passed, 6 legacy UI/stub
  assertions deselected because they are outside this review scope and already
  fail against the pre-existing baseline.
- Ruff: passed for changed Stage 02 files.
- `py_compile`: passed for changed Python files.
- GRACE lint: passed for changed Stage 02 files; the pre-existing `git_service.py`
  canon baseline remains unchanged except for the bounded primitive.
- `git diff --check`: passed.
