# RESUBMISSION 013 — Stage 07 review fixes

WEB_ORCH_REPORT: RESUBMISSION 013
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 98b5037d1ef12115761988598a53378818a28bc1
WEB_ORCH_CHECKS: PASS

Implemented only the requested review fixes in `98b5037d1ef12115761988598a53378818a28bc1`:

- Inventoried live mutating `/api/admin/*` routes. Read-only `read-token`
  requests receive 403 with zero packet, feature or audit state change;
  confirmed legacy retry/cancel/archive/unarchive aliases delegate through the
  canonical project-local control and audit gate, while unsupported destructive
  aliases remain explicitly unavailable and audited.
- Restored bounded row-based Global Logs totals, kept byte size separate, and
  added stable internal line ordering so opaque continuation pages contain no
  duplicates, skips or phantom empty pages.
- Strengthened the real Chromium acceptance path to observe a production HTMX
  poll, preserve project/deep-link/viewer state, verify follow-off and
  away-from-bottom follow-on behavior, and execute a typed confirmation whose
  state change and canonical audit timeline are visible.
- Updated `docs/work/REPORT_GRACE_ADMIN_CONTROL_CENTER_V3.md` with the review
  fix-up architecture and checks.

Checks:

- Stage 07 topology/matrix/browser suite: `6 passed`.
- Security/admin/lifecycle regression suite: `64 passed`.
- Related Admin/Hub/API/auth/OpenAPI, packet/merge/worker,
  maintenance/filesystem/Git and supervisor suites: `216 passed`.
- Ruff, `python3 -m py_compile`, applicable changed/new-file GRACE lint and
  `git diff --check`: PASS.

The full legacy canon lint still reports pre-existing findings in the untouched
legacy router/test modules; no unrelated canon refactor was included.
