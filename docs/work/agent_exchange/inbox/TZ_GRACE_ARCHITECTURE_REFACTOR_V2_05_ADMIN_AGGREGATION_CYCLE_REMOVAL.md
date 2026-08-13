# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_05_ADMIN_AGGREGATION_CYCLE_REMOVAL — Packet 05: eliminate aggregation wiring cycles

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_05_ADMIN_AGGREGATION_CYCLE_REMOVAL`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent source: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative detail: Architecture Refactor V2 Wave 3 — Admin aggregation cycle/post-construction wiring removal only.
- Previous new-cycle packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_04_ADMIN_CONTROL_CENTER_DEPENDENCY_INVERSION` is ACCEPTED.
- Historical agent-exchange packets from earlier cycles are evidence only. Do not edit/reuse their submission/review files.

Implement only this named packet. Do not start lifecycle extraction, typed Admin read models, dead-code cleanup, CI consolidation, broad mutation refactoring, or any later wave.

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

This new cycle verifies/refines a repository that may already contain the earlier accepted Wave 3 implementation.

1. Current synced `main` is authoritative.
2. Audit actual current code first; do not recreate old cycles/setter wiring because historical TZs describe it.
3. If every acceptance criterion is already satisfied, run the full verification and submit a **verified no-op** using synced `HEAD` as `WEB_ORCH_COMMIT`.
4. Do not manufacture a source diff merely to produce an implementation commit.
5. If a gap exists, make only the smallest in-scope correction, commit/push it, and report the actual implementation SHA.

## Objective

Ensure the Admin aggregation read graph is complete and acyclic at construction time. There must be no post-construction private dependency injection such as:

```python
self._packet._artifact_service = ...
self._packet._session_service = ...
self._pipeline._artifact_service = ...
```

Target architecture:

```text
AdminAggregationService                 # stable thin compatibility facade
    -> PacketRunResolver                # shared packet/run selector owner
    -> AdminArtifactReadService         # explicit resolver dependency
    -> AdminLogsReadService             # explicit resolver dependency
    -> AdminPipelineReadService         # explicit narrow evidence dependency
    -> AdminPacketReadService           # explicit final collaborators
    -> AdminFeatureReadService
    -> AdminOverviewReadService
```

No child -> facade -> sibling cycle, no late setter/private-field wiring, no lambda/global/service-locator workaround.

## Frozen invariants

Preserve:

- public `AdminAggregationService` import, constructor compatibility and public method signatures/DTO shapes;
- packet/run selector semantics: canonical `PacketRun.id`, legacy composed selector if still supported, numeric `run_number`, invalid selector behavior;
- artifact/evidence/log/session behavior and filesystem safety;
- pipeline/stage/state-machine/recovery projections and feature summaries;
- API routes/OpenAPI contracts;
- DB schema/Alembic;
- mutation/security behavior;
- packet lifecycle/execution/reviewer/recovery/merge semantics.

Do not introduce `BaseService`, service locator, dependency bag, manager factory, broad admin protocol, new GRC005/GRC012 allowlist entry, or replacement control CLI.

## Audit before edits

Inspect at minimum current versions of:

```text
src/grace_control/services/admin_aggregation_service.py
src/grace_control/services/admin_packet_run_resolver.py
src/grace_control/services/admin_packet_read_service.py
src/grace_control/services/admin_artifact_read_service.py
src/grace_control/services/admin_logs_read_service.py
src/grace_control/services/admin_pipeline_read_service.py
src/grace_control/services/admin_read_ports.py
src/grace_control/services/admin_feature_read_service.py
src/grace_control/services/admin_overview_read_service.py

tests/grace_control/architecture/test_admin_aggregation_dependency_graph.py
tests/grace_control/services/test_admin_aggregation_service.py
tests/grace_control/api/test_admin_pipeline_contract.py
tests/grace_control/api/test_admin_router.py
```

Some preferred files may not exist if current implementation chose an equivalent narrow design. Treat current code as authoritative and verify responsibilities, not filenames alone.

Run structural inventory:

```bash
rg -n '\._artifact_service\s*=|\._session_service\s*=|\._pipeline_service\s*=|\._run_resolver\s*=' \
  src/grace_control/services/admin_*.py || true

rg -n 'resolve_run|PacketRunResolver|AdminPacketReadService\(|AdminArtifactReadService\(|AdminLogsReadService\(|AdminPipelineReadService\(' \
  src/grace_control/services tests/grace_control || true
```

Interpret every hit. Constructor-owned assignment inside the receiving object's own `__init__` is valid; post-construction writes into another object are forbidden.

## Required target state

### 1. One lower-level packet/run resolver

`PacketRunResolver` or an equivalent single lower-level collaborator must own shared packet/run resolution semantics.

It must not depend on `AdminAggregationService`, `AdminPacketReadService`, artifact/log/pipeline services, FastAPI, or filesystem code.

Resolution semantics must preserve the accepted current behavior, including canonical persisted run ID, any supported legacy composed selector, numeric run number scoped to packet, and invalid selector behavior.

If `AdminPacketReadService.resolve_run()` remains only as a compatibility delegate, prove the real active caller. Do not keep duplicate resolution logic.

### 2. Artifact/log readers use the resolver explicitly

`AdminArtifactReadService` and `AdminLogsReadService` must receive/use the shared lower-level resolver explicitly. They must not depend on `AdminPacketReadService` merely to resolve runs.

### 3. Packet service has complete constructor dependencies

Every collaborator actually required by `AdminPacketReadService` must be injected during construction and remain final for the object's lifetime. No optional field that is populated later by `AdminAggregationService`.

Preserve current packet/session DTO and fallback behavior. Remove unused dependencies instead of retaining placeholders.

### 4. Pipeline evidence dependency is explicit

`AdminPipelineReadService` must receive its evidence/artifact dependency at construction through a narrow explicit collaborator or read port.

No setter, no post-construction `_artifact_service` assignment, no late-bound lambda closing over an object assigned later, no global lookup.

A protocol such as `ArtifactEvidenceReader` is acceptable only when it stays narrow and represents the actual method dependency. Do not mirror the whole facade.

### 5. Aggregation composition is one-way

`AdminAggregationService.__init__` must construct a complete graph in dependency order. It may store child collaborators on itself, but must never assign private dependency fields on an already-constructed child.

It remains a thin facade/delegator and must not absorb focused child business logic.

### 6. No indirect cycle workaround

Reject any architecture equivalent to:

```text
packet -> artifacts -> packet
pipeline -> artifacts -> pipeline
child -> AdminAggregationService -> sibling child
```

Also reject setter methods, mutable dependency registries, globals, generic callback bags, or delayed wiring used to disguise the cycle.

## Architecture guard

A durable guard must prove directly or equivalently:

1. `AdminAggregationService.__init__` performs no post-construction private collaborator writes into child services.
2. Packet/artifact/log/pipeline services expose no setter-style collaborator injection.
3. Artifact/log run resolution does not depend on `AdminPacketReadService`.
4. The shared resolver has no forbidden higher-level admin-service imports.
5. Dependency-field assignment in the touched graph occurs only in the owning object's `__init__`.
6. Pipeline evidence dependency is constructor-explicit.

Preferred path:

`tests/grace_control/architecture/test_admin_aggregation_dependency_graph.py`

If an equivalent strong guard already exists and passes, do not duplicate it.

## Required verification

Run at minimum available equivalents of:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_admin_aggregation_dependency_graph.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/services/test_admin_aggregation_service.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_pipeline_contract.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_router.py
```

Discover and run current artifact/log/session tests that exercise the touched graph.

Then run:

```bash
make lint
make docs-check
make hygiene
python3 -m py_compile <changed-python-files-if-any>
git diff --check
```

For baseline-aware lint, report canonical `make lint` success separately from raw Ruff/GraceLint debt.

Run final structural searches:

```bash
rg -n '\._artifact_service\s*=|\._session_service\s*=|\._pipeline_service\s*=|\._run_resolver\s*=' \
  src/grace_control/services/admin_*.py || true

rg -n 'resolve_run|PacketRunResolver' src/grace_control/services tests/grace_control || true
```

Explain every surviving assignment/reference and prove dependency ownership.

## Submission protocol

If corrections are required, commit and push them and use the full 40-character implementation SHA. If current `main` already satisfies the packet, use synced `HEAD` and explicitly state `verified no-op`.

Create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_05_ADMIN_AGGREGATION_CYCLE_REMOVAL_SUBMISSION.md`

It MUST begin exactly:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_05_ADMIN_AGGREGATION_CYCLE_REMOVAL
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-40-character-implementation-sha>
WEB_ORCH_CHECKS: PASS
```

Then include:

- synced base SHA and initial status;
- implementation SHA or verified-no-op statement;
- final constructor dependency graph;
- shared resolver ownership/selector compatibility evidence;
- structural scan proving zero post-construction wiring;
- any retained compatibility resolver delegate and exact caller;
- exact targeted test counts/check results;
- changed paths, or `none` for verified no-op.

Do not create/start the next packet. Wait for Architect ACCEPT/REVIEW.

## Acceptance criteria

Architect ACCEPT requires all of:

1. `AdminAggregationService` has zero post-construction private collaborator injection.
2. One lower-level resolver owns shared packet/run selection semantics.
3. Artifact/log readers do not depend on packet service for run resolution.
4. Pipeline evidence dependency is explicit at construction.
5. Packet service receives every real collaborator at construction or removes unused dependencies.
6. No setter/lambda/global/service-locator workaround recreates the cycle.
7. Public aggregation method/DTO behavior remains compatible.
8. Packet/run selector semantics remain compatible.
9. Artifact/evidence/log/session/filesystem-safety behavior remains compatible.
10. Pipeline/state-machine/recovery/feature projections remain compatible.
11. No API/DB/lifecycle/packet-state/merge semantic drift occurs.
12. No later architecture wave or lint allowlist expansion is mixed in.
13. Architecture/regression checks pass and are truthfully reported.
14. Submission follows the exact named-file protocol with a full SHA.
