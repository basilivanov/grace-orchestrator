# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_AGGREGATION_CYCLE_REMOVAL — Packet 5: eliminate aggregation wiring cycles

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_AGGREGATION_CYCLE_REMOVAL`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent programme: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative implementation detail: `docs/work/WORKER_GRACE_ARCHITECTURE_REFACTOR_V2.md`, **Wave 3 only**.
- Previous named packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_CONTROL_CENTER_DEPENDENCY_INVERSION` is ACCEPTED.
- Implement **only Admin Aggregation cycle/post-construction wiring removal** in this packet.
- Do **not** start lifecycle router/service extraction, typed DTO work, dead-code cleanup, CI consolidation, mutation-service mixin refactor, or any later wave.

This packet is self-contained. Do not invent or start another packet. Only Architect ACCEPT authorizes the next named TZ.

## Mandatory sync before work

Before inspecting implementation files or editing anything:

```bash
cd /opt/grace-orchestrator
git switch main
git fetch origin main
git merge --ff-only origin/main
git status --short
git rev-parse HEAD
```

Record synced base SHA and initial `git status --short` in the submission.

Preserve unrelated pre-existing untracked files, including `.env.bak-mini-endpoint-20260705170600` and `parse_list.py` if still present. Do not use `git reset --hard` or `git clean`.

Do not create `state.json`, lock files, orchestration metadata, or any repository-side web-orch state.

---

# Objective

Remove the current private post-construction dependency injection in `AdminAggregationService` and make the admin read graph complete and acyclic at construction time.

Current live shape on the accepted base includes:

```python
self._pipeline = AdminPipelineReadService()
self._packet = AdminPacketReadService(self._size_calc, self._pipeline)
self._artifacts = AdminArtifactReadService(self._packet.resolve_run)
self._logs = AdminLogsReadService(self._packet.resolve_run)
self._packet._artifact_service = self._artifacts
self._packet._session_service = self._logs
self._pipeline._artifact_service = self._artifacts
```

This is forbidden after this packet.

The target is a one-way constructor graph with explicit lower-level collaborators. No setter-style/private-field dependency wiring after object construction.

## Invariants

1. Preserve public `AdminAggregationService` import, constructor compatibility and existing public method signatures/DTO shapes.
2. Preserve packet/run selector semantics: canonical run ID, legacy composed ID, numeric run number and existing missing-selector behavior.
3. Preserve artifact/evidence/log/session behavior and filesystem safety.
4. Preserve pipeline/stage/state-machine/recovery projections and feature summaries.
5. No DB schema changes.
6. No API route or response contract changes.
7. No mutation behavior changes; this packet is read-path architecture only.
8. Do not move unrelated business logic into the facade.
9. Do not create generic `BaseService`, service locator, dependency dict/bag, manager factory, or broad protocol mirroring the entire admin facade.
10. No new GRC005/GRC012 allowlist entries. Files remain <=1000 physical lines; touched source target <=800 where practical.

## Current files to inspect before editing

At minimum inspect:

```text
src/grace_control/services/admin_aggregation_service.py
src/grace_control/services/admin_packet_read_service.py
src/grace_control/services/admin_artifact_read_service.py
src/grace_control/services/admin_logs_read_service.py
src/grace_control/services/admin_pipeline_read_service.py
src/grace_control/services/admin_feature_read_service.py
src/grace_control/services/admin_overview_read_service.py

tests/grace_control/services/test_admin_aggregation_service.py
tests/grace_control/api/test_admin_router.py
tests/grace_control/api/test_admin_pipeline_contract.py
```

Also locate every active assignment/reference to:

```text
_artifact_service
_session_service
resolve_run
AdminPacketReadService(
AdminArtifactReadService(
AdminLogsReadService(
AdminPipelineReadService(
```

Do not guess ownership from filenames; map the actual call graph first.

---

# Required implementation

## 1. Extract `PacketRunResolver`

Create:

`src/grace_control/services/admin_packet_run_resolver.py`

Class:

`PacketRunResolver`

Move the shared run-resolution behavior currently living in `AdminPacketReadService.resolve_run()` into this lower-level collaborator.

Required behavior must remain equivalent:

```python
resolve_run(db, packet_id, run_id) -> PacketRun | None
```

It must preserve, in order/semantics, resolution by:

- canonical persisted `PacketRun.id` scoped to `packet_id`;
- legacy composed selector `f"{packet_id}-{selector}"` as currently supported;
- numeric `run_number` scoped to `packet_id`;
- invalid/non-numeric selector -> `None`.

If another shared packet lookup truly belongs here, add it only with demonstrated multi-service use. Do not turn this into an admin repository/service locator.

`PacketRunResolver` must not depend on `AdminAggregationService`, `AdminPacketReadService`, artifact/log/pipeline services, FastAPI, or filesystem code.

## 2. Make artifact/log services depend on the resolver explicitly

Refactor:

- `AdminArtifactReadService`
- `AdminLogsReadService`

Preferred constructor shape:

```python
AdminArtifactReadService(run_resolver: PacketRunResolver)
AdminLogsReadService(run_resolver: PacketRunResolver)
```

A narrow callable is acceptable only if it is clearly simpler and remains statically explicit, but the packet's preferred design is one shared `PacketRunResolver` instance.

Do not make either service depend on `AdminPacketReadService` merely to reach `resolve_run`.

## 3. Remove packet service's optional post-wired collaborators

`AdminPacketReadService` currently accepts optional artifact/session collaborators and can function with late mutation.

Refactor it so all collaborators actually required by its methods are constructor-injected and final for the object's lifetime.

Important:

- `get_packet_sessions()` must keep the current DTO/fallback semantics.
- If session reads are wholly owned by `AdminLogsReadService`, inject a narrow session reader dependency explicitly.
- Do not instantiate a second conflicting owner merely to avoid constructor work.
- Do not write `self._artifact_service = ...` or `self._session_service = ...` outside `__init__`.

If `AdminPacketReadService` no longer needs artifact access after examining the real code, remove that dependency instead of retaining an unused parameter.

## 4. Remove pipeline artifact late wiring

`AdminPipelineReadService` currently has optional `artifact_service` state and receives it after construction.

Make its evidence dependency explicit at construction.

Preferred options, in order:

1. Inject a narrow `ArtifactEvidenceReader` protocol implemented by the existing artifact reader.
2. If evidence projection is small and genuinely shared, extract a lower-level evidence reader used by both pipeline and artifact services.

Do **not** solve this by:

- creating the pipeline and setting `_artifact_service` later;
- adding a setter;
- using a lambda that closes over an object assigned later;
- introducing a global/service locator;
- making pipeline depend on `AdminAggregationService`.

## 5. Add narrow read protocol only if it earns its existence

If pipeline only needs `get_packet_evidence`, create:

`src/grace_control/services/admin_read_ports.py`

with a small protocol such as:

```python
class ArtifactEvidenceReader(Protocol):
    def get_packet_evidence(
        self,
        db: Session,
        packet_id: str,
        run_id: str | None = None,
    ) -> dict[str, Any]: ...
```

If packet session composition needs a protocol, add only that one method contract.

Do not put every admin read method into this module.

## 6. Rebuild `AdminAggregationService.__init__` as one-way constructor composition

The final constructor must build dependencies in an order that is complete immediately.

A valid target shape is conceptually:

```text
size_calc
resolver
artifacts(resolver)
logs(resolver)
pipeline(artifact evidence reader)
packet(size_calc, pipeline, session reader, ...only real deps...)
features(size_calc, pipeline)
overview
```

The exact order may vary with the final narrow contracts, but there must be no post-construction private collaborator writes.

`AdminAggregationService` remains a thin compatibility facade and delegates its existing public methods to the focused owners.

## 7. Remove obsolete resolver ownership from packet service

After introducing `PacketRunResolver`, remove `AdminPacketReadService.resolve_run()` unless a real external consumer remains.

Before deletion, prove callers with repository search. If a real external caller exists, either migrate it to the resolver or retain only a temporary direct delegation **with evidence in the submission**. Do not retain it solely because old tests mention it.

## 8. Architecture guard

Add:

`tests/grace_control/architecture/test_admin_aggregation_dependency_graph.py`

It must fail if:

1. `AdminAggregationService.__init__` performs post-construction assignment to a collaborator's private dependency, including patterns equivalent to:
   - `self._packet._artifact_service = ...`
   - `self._packet._session_service = ...`
   - `self._pipeline._artifact_service = ...`
2. `AdminPacketReadService`, `AdminArtifactReadService`, `AdminLogsReadService`, or `AdminPipelineReadService` exposes setter-style collaborator injection.
3. artifact/log run resolution depends on `AdminPacketReadService` instead of the lower-level resolver.
4. `PacketRunResolver` imports any higher-level admin facade/service it must not depend on.
5. collaborator assignment happens outside `__init__` for dependency fields in the touched graph.

Prefer AST/introspection checks over fragile global string matching.

---

# Explicit structural verification

Run searches equivalent to:

```bash
rg -n '\._artifact_service\s*=|\._session_service\s*=|\._pipeline_service\s*=|\._run_resolver\s*=' \
  src/grace_control/services/admin_*.py

rg -n 'resolve_run|PacketRunResolver|AdminPacketReadService\(' \
  src/grace_control/services tests/grace_control
```

Interpret every hit manually.

Expected final state:

- dependency fields are assigned only inside the owning object's `__init__`;
- zero post-construction collaborator writes from `AdminAggregationService`;
- one shared lower-level run-resolution owner;
- no facade -> child -> facade cycle;
- no pipeline <-> artifact construction cycle.

---

# Required regression proof

At minimum run the tests that cover aggregation, packet detail, pipeline, artifacts, logs/sessions and admin API contracts. Include exact commands/counts in the submission.

Required focused commands should include available equivalents of:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/services/test_admin_aggregation_service.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_pipeline_contract.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_router.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_admin_aggregation_dependency_graph.py
```

Also run any existing artifact/log/session tests found by repository search.

Then run on every changed Python file:

```bash
ruff check <changed-python-files>
python3 scripts/grace_lint.py <changed-python-files>
python3 -m py_compile <changed-python-files>
git diff --check
```

If repository-wide baseline lint remains non-zero, report it as pre-existing and prove all touched files pass. Do not broaden this packet into unrelated cleanup.

---

# Acceptance criteria

PASS only if all are true:

1. `AdminAggregationService` has zero post-construction private collaborator injection.
2. `PacketRunResolver` is the single lower-level owner of shared packet-run selection semantics.
3. Artifact/log readers no longer depend on packet service to resolve runs.
4. Pipeline receives its evidence dependency explicitly at construction.
5. Packet service receives every required collaborator explicitly or removes unused dependencies.
6. No setter/lambda/global/service-locator workaround recreates the cycle indirectly.
7. Existing public `AdminAggregationService` method signatures and DTO behavior remain compatible.
8. Packet/run selector semantics remain compatible.
9. Artifact/evidence/log/session/filesystem safety behavior remains compatible.
10. Pipeline/state-machine/recovery/feature projections remain compatible.
11. No DB/API schema changes.
12. No later architecture wave started.
13. Architecture guard passes.
14. Relevant regression tests pass or only exact documented pre-existing failures remain.
15. Changed files pass Ruff, GRACE lint, py_compile and `git diff --check`.
16. No new lint/size allowlist exception is added.

---

# Required submission protocol

After implementation, commit and push to `origin/main`.

Create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_AGGREGATION_CYCLE_REMOVAL_SUBMISSION.md`

The submission must begin with these exact lines:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_AGGREGATION_CYCLE_REMOVAL
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <commit-sha>
WEB_ORCH_CHECKS: PASS
```

Then report:

- synced base SHA and initial status;
- exact changed files;
- final constructor dependency graph;
- whether any compatibility resolver method remains and why;
- exact removal evidence for post-construction writes;
- exact tests/checks and results;
- implementation commit SHA.

Do not create the next packet. Do not create additional agent-exchange files.
