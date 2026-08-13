# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_03_ADMIN_CROSS_PROJECT_COMPOSITION — Packet 03: explicit cross-project composition

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_03_ADMIN_CROSS_PROJECT_COMPOSITION`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent source: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative detail: Architecture Refactor V2 Wave 2 — cross-project composition only.
- Previous new-cycle packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_02_CONTROL_CLI_REMOVAL` is ACCEPTED.
- Historical agent-exchange packets from earlier cycles are evidence only; do not edit/reuse their submission/review files.

Implement only this named packet. Do not start Control Center dependency inversion, Admin aggregation-cycle removal, lifecycle extraction, typed read models, dead-code cleanup, or CI consolidation.

## Mandatory fast-forward sync

Before inspecting implementation files or editing anything:

```bash
cd /opt/grace-orchestrator
git switch main
git fetch origin --prune
git pull --ff-only origin main
git status --short --branch
git rev-parse HEAD
```

Record synced base SHA and initial status. Preserve unrelated untracked files. Do not use `git reset --hard`, `git clean`, destructive checkout, repo-side `state.json`, lock files, or orchestration metadata.

## Current-state rule

This new cycle verifies/refines a repository that may already contain an earlier accepted implementation of this architecture.

1. Current synced `main` is authoritative.
2. Do not recreate mixins or old dependency shapes merely because the parent TZ describes the historical starting point.
3. Audit the actual current code first.
4. If every acceptance criterion is already satisfied, perform the required verification and submit a **verified no-op** using the synced `HEAD` as `WEB_ORCH_COMMIT`.
5. Do not manufacture a source diff merely to have one.
6. If a gap exists, make only the smallest in-scope correction, commit/push it, and report the real implementation SHA.

## Objective

Ensure cross-project Admin reads use explicit composition rather than hidden mixin contracts.

Required target shape:

```text
AdminCrossProjectService                 # stable thin facade
    -> CrossProjectTransport             # selection/fan-out/request/error isolation
    -> AdminCrossProjectOverviewService  # overview/diagnostics projections
    -> AdminCrossProjectQueryService     # events/logs/search projections
```

No overview/query mixins. No child projection service may rely on hidden facade members such as `_registry`, `_request`, `_fanout`, or `_select_contexts` as undeclared local API.

## Frozen product/architecture invariants

Preserve:

- public class/import `AdminCrossProjectService`;
- current constructor compatibility (`registry`, optional client factory, concurrency/timeouts as currently supported);
- public methods and argument/return behavior for projects overview, attention, diagnostics, events, logs, and search;
- JSON/DTO shapes;
- registry ordering, disabled-project behavior, explicit-all and unknown-project behavior;
- bounded concurrency and deterministic result ordering;
- per-project error isolation, capability-unavailable handling, and identity-mismatch handling;
- project-local API/runtime boundary: no direct cross-project DB/filesystem/Git reads;
- HTTP routes/OpenAPI, templates, mutation/security behavior, DB schema, packet lifecycle, merge/recovery semantics.

Do not introduce `BaseService`, service locator, dependency bag, manager factory, global registry, or new GRC005/GRC012 allowlist entries.

## Audit before edits

Inspect at minimum current versions of:

```text
src/grace_control/services/admin_cross_project_service.py
src/grace_control/services/admin_cross_project_transport.py
src/grace_control/services/admin_cross_project_overview_service.py
src/grace_control/services/admin_cross_project_query_service.py
src/grace_control/services/admin_cross_project_helpers.py
src/grace_control/services/project_client.py
src/grace_control/config/project_registry.py
src/grace_control/api/routers/admin_hub.py
src/grace_control/services/admin_control_center.py

tests/grace_control/architecture/test_admin_cross_project_composition.py
tests/grace_control/api/test_admin_cross_project_observability.py
tests/grace_control/api/test_admin_hub_project_foundation.py
```

Also search for historical mixin/private-contract remnants:

```bash
rg -n 'AdminCrossProject.*Mixin|admin_cross_project_.*_mixin|self\._registry|self\._request|self\._fanout|self\._select_contexts' \
  src/grace_control/services tests/grace_control || true
```

Interpret hits by owner; `CrossProjectTransport` may legitimately own its own `_registry` and transport helpers.

## Required target-state checks

### 1. Explicit transport owner

`CrossProjectTransport` must own the cross-project transport boundary:

- registry/context access;
- context selection;
- client factory;
- connect/read timeout policy;
- bounded fan-out;
- one-project request dispatch;
- response normalization;
- per-project transport/client failure isolation;
- identity/capability normalization required by current behavior.

Do not duplicate this logic in facade/overview/query services.

### 2. Overview projection service

`AdminCrossProjectOverviewService` must receive/use explicit transport composition and own overview/diagnostics/attention projection behavior without pretending transport members are its own hidden fields.

Preserve coverage math, disabled cards, aggregate semantics, ordering, malformed response handling and DTO keys.

### 3. Query projection service

`AdminCrossProjectQueryService` must receive/use explicit transport composition for events/logs/search.

Preserve project ordering, bounds/cursors, regex/filter validation, route selection, merged-row attribution, capability handling and search ordering.

### 4. Thin stable facade

`AdminCrossProjectService` must use composition and delegate its public methods. It must not inherit overview/query mixins and must not reimplement fan-out/request logic merely for compatibility.

A narrow compatibility property/field required by an already-live consumer may remain only if it does not recreate reverse hidden dependencies; document it explicitly.

### 5. Old mixin production files absent

Production files/classes equivalent to:

```text
admin_cross_project_overview_mixin.py
admin_cross_project_query_mixin.py
AdminCrossProjectOverviewMixin
AdminCrossProjectQueryMixin
```

must not exist as active compatibility shims.

### 6. Control Center next step remains frozen

Do not refactor Control Center child-service -> facade/private-state dependencies in this packet. That is the next bounded Wave 2 packet.

## Architecture guard

A durable guard must prove directly or equivalently:

1. `AdminCrossProjectService` does not inherit `*Mixin` production classes.
2. No active cross-project overview/query mixin production classes/files remain.
3. Overview/query services depend through `self._transport`, not hidden local `_registry/_request/_fanout/_select_contexts` contracts.
4. `CrossProjectTransport` remains the transport owner.
5. Public facade methods remain present.

If the existing guard already proves these and passes, do not duplicate it.

## Required verification

Run current relevant tests plus at minimum:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_admin_cross_project_composition.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_cross_project_observability.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_hub_project_foundation.py
```

Run Control Center compatibility regressions that consume the facade when present, without refactoring their architecture.

Also run:

```bash
make lint
make docs-check
make hygiene
python3 -m py_compile <changed-python-files-if-any>
git diff --check
```

For baseline-aware lint, distinguish canonical `make lint` success from raw Ruff/GraceLint non-zero baseline diagnostics.

Run structural searches after implementation/audit:

```bash
rg -n 'class AdminCrossProject.*Mixin|AdminCrossProjectOverviewMixin|AdminCrossProjectQueryMixin' src tests || true
rg -n 'self\._registry|self\._request|self\._fanout|self\._select_contexts' \
  src/grace_control/services/admin_cross_project_* || true
```

Explain any legitimate transport-owned hits.

## Submission protocol

If corrections are required, commit and push them and use the full 40-character implementation SHA. If current `main` already satisfies the packet, use the synced `HEAD` SHA and explicitly state `verified no-op`.

Create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_03_ADMIN_CROSS_PROJECT_COMPOSITION_SUBMISSION.md`

The file MUST begin exactly:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_03_ADMIN_CROSS_PROJECT_COMPOSITION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-40-character-implementation-sha>
WEB_ORCH_CHECKS: PASS
```

Then include:

- synced base SHA and initial status;
- implementation SHA or verified-no-op statement;
- current composition/transport ownership evidence;
- facade compatibility evidence;
- mixin/private-contract scan results;
- exact tests/checks and counts;
- changed paths, or `none` for verified no-op;
- any compatibility seam intentionally retained and why.

Do not create/start the next packet. Wait for Architect ACCEPT/REVIEW.

## Acceptance criteria

Architect ACCEPT requires all of:

1. `AdminCrossProjectService` uses explicit composition, not mixin inheritance.
2. `CrossProjectTransport` is the single transport/selection/fan-out/request owner.
3. Overview/query services depend on explicit transport and pure helpers, not hidden facade state.
4. Old production mixin files/classes are absent.
5. Public constructor/method/API DTO behavior remains compatible.
6. Bounded concurrency, ordering, disabled/offline/partial/identity/capability semantics remain intact.
7. No direct cross-project DB/filesystem/Git access is introduced.
8. Control Center dependency inversion is not started here.
9. Architecture/regression checks pass and are truthfully reported.
10. No API/DB/lifecycle/packet-state/merge semantic drift or lint allowlist expansion is introduced.
11. Submission follows the exact named-file protocol with a full SHA.
