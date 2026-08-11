# Task 012 submission — Admin Control Center Stage 06

WEB_ORCH_REPORT: SUBMISSION 012
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: af2e5a6146a8ff46fa9e45368c0607905890a11d
WEB_ORCH_CHECKS: PASS

Implemented the Stage 06 project-scoped mutation boundary with selected-project isolation, unique request IDs, no automatic mutation retry, normalized unknown outcomes, control-token authorization, same-origin protection, server-side confirmation, recursive secret masking and project-local audit events.

Added capability/state-aware controls, packet retry/cancel/merge delegation, maintenance dry-run and fail-closed lease protection, supervisor status/restart/reload handling, explicit OpenAPI mutation mode, bounded same-project dispatch and visible failed/WAIT outcomes. Unsupported or planned controls remain unavailable rather than reporting success.

Checks: focused Stage 06/auth/Control Center suite 36 passed, 2 skipped; relevant Task 007–011 regressions 69 passed; Ruff PASS; py_compile PASS; new/Stage 06 GRACE lint PASS; git diff --check PASS. Full changed-file GRACE lint reports only pre-existing legacy violations in app_factory/auth/settings/admin_control_center. The unrelated full packet API suite retains 4 pre-existing failures and 14 passed.
