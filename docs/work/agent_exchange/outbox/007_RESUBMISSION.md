WEB_ORCH_REPORT: RESUBMISSION 007
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: be11c38ad2a8ceb18458c8c5fbc8bbd4983331d4
WEB_ORCH_CHECKS: PASS

Review fix-up commit `be11c38ad2a8ceb18458c8c5fbc8bbd4983331d4`.

- Replaced the per-client `max_active == 1` assertion with a shared barrier: serial fan-out cannot pass because both independent fake APIs must enter before either is released.
- Added failure-isolation coverage to the barrier test: alpha returns a typed timeout while beta remains online.
- Added concurrent ASGI requests for `/api/admin-hub/projects/alpha/health` and `/api/admin-hub/projects/beta/health`, proving independent registry/runtime identities with no context leakage.

Checks: focused Hub and single-project Admin suite — **72 passed**; Ruff, `py_compile`, GRACE lint and `git diff --check` — PASS. Only the review-required test file changed; no Task008 work started.
