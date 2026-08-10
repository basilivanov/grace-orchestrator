# Review 007 — Admin Control Center Stage 01

Status: CHANGES REQUIRED

Implementation commit reviewed: `6ad8d36f75593fc1b8616fc4f40bbe5c2ee1cfc2`.

The Stage 01 architecture is generally aligned with TZ01: project registry/context separation, no request-time global project switching, project-local API transport, failure-isolated service fan-out, disabled-project skipping, identity comparison, required `/api/admin-hub/*` routes, and backward-compatible empty default registry are present.

## Required fixes

### 1. The concurrency acceptance test does not actually prove concurrent fan-out

`test_health_fanout_is_concurrent_and_isolated` currently records `active/max_active` separately inside each `_FakeProjectApi` instance and asserts each client reached `max_active == 1`.

That assertion also passes if the Hub executes alpha completely and only then executes beta. Therefore it does not prove the TZ01 requirement:

> cross-project fan-out is concurrent, not serial

Replace/add a deterministic concurrency proof that would fail under sequential execution. Do not use a brittle wall-clock threshold. Suitable approaches include a shared active counter/barrier/event across both fake project APIs, where both calls must be simultaneously entered before either is released.

The test must also continue proving failure isolation (for example alpha timeout/offline while beta remains healthy).

### 2. Prove request-scoped isolation with actual concurrent Hub HTTP requests

`test_project_context_is_immutable_and_request_scoped` currently calls `AdminProjectService.get_project_health()` directly. The task explicitly requires proving that two concurrent requests resolve different immutable contexts with no leakage.

Add an ASGI-level test that sends two concurrent requests through the Hub routes for two different project keys (for example alpha and beta health/detail), using independent fake project APIs/identities, and assert each response contains only its own project context/identity. The test should fail if project selection were implemented through shared mutable selected-project state.

## Scope

Do not redesign Stage 01 or start Stage 02. If the stronger tests expose an implementation bug, fix only that bug. Otherwise test-only changes are sufficient.

Re-run the focused Hub tests plus the relevant existing single-project Admin regressions and the required Ruff / `py_compile` / GRACE lint / `git diff --check` checks.

Then update/create:

`docs/work/agent_exchange/outbox/007_RESUBMISSION.md`

Include the new implementation/test commit SHA and concise check results. Do not start Task 008.