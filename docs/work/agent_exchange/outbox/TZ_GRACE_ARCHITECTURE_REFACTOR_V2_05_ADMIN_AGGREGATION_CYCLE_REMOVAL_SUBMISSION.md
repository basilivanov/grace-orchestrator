WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_05_ADMIN_AGGREGATION_CYCLE_REMOVAL
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: ffc8daff7046ccf9f03456b7b7d8949b08ab1f0a
WEB_ORCH_CHECKS: PASS

## Sync and implementation

- Synced base SHA: `ffc8daff7046ccf9f03456b7b7d8949b08ab1f0a`.
- Initial status: `## main...origin/main`; unrelated untracked files were preserved.
- `git fetch origin --prune` and `git pull --ff-only origin main` completed successfully; origin was already up to date.
- Implementation: **verified no-op**. The synced `HEAD` already satisfies Packet 05, so no source diff was manufactured.
- Implementation SHA: `ffc8daff7046ccf9f03456b7b7d8949b08ab1f0a`.

## Final dependency graph

- `AdminAggregationService.__init__` constructs the complete graph in dependency order: `SizeCalculator`, overview service, one `PacketRunResolver`, artifact/log readers using that resolver, pipeline using the explicit artifact evidence reader, packet using size/pipeline/log collaborators, and feature using size/pipeline.
- The aggregation facade remains a thin delegator with the existing public constructor, methods, argument shapes and DTO behavior.
- `PacketRunResolver` is a lower-level collaborator with no Admin facade, focused-service, FastAPI or filesystem dependencies.
- `AdminArtifactReadService` and `AdminLogsReadService` receive and call `PacketRunResolver` directly; neither depends on `AdminPacketReadService` for run resolution.
- `AdminPipelineReadService` receives its narrow `ArtifactEvidenceReader` dependency at construction.
- `AdminPacketReadService` receives its required size, pipeline and logs collaborators at construction; no optional late-bound dependency remains.

## Structural scan and compatibility

- No post-construction private collaborator writes from `AdminAggregationService` were found.
- No setter-style injection exists in packet, artifact, logs, pipeline or feature services.
- Final assignment scan found only constructor-owned fields: `_run_resolver` in artifact/log readers, `_pipeline_service` in packet/feature readers, plus the root's child construction assignments.
- `resolve_run` references are centralized in `PacketRunResolver`; the compatibility facade delegate `_run_for_selector` calls that resolver and has no duplicate resolution logic. No active external caller requiring a second resolver was found in the current test/source audit.
- Selector compatibility is covered for canonical persisted run ID, legacy composed selector, numeric packet-scoped run number and invalid selector behavior.
- Artifact/evidence/log/session/filesystem safety, pipeline/state/recovery/feature projections, API routes and DTO contracts were unchanged.
- No later lifecycle/read-model/dead-code/CI wave or lint allowlist change was started.

## Checks

- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_admin_aggregation_dependency_graph.py` — PASS, 4 passed.
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/services/test_admin_aggregation_service.py` — PASS, 44 passed.
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_pipeline_contract.py` — PASS, 4 passed.
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_router.py` — PASS, 35 passed.
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/services/test_admin_packet_run_resolver.py` — PASS, 4 passed.
- `.venv/bin/python -m py_compile` on the seven aggregation/read-graph production modules — PASS.
- `make lint` — PASS; baseline-aware gate reports Ruff `1020` and GraceLint `3249`, matching the reviewed baseline.
- `make docs-check` — PASS; 3 files in sync.
- `make hygiene` — PASS.
- `git diff --check` — PASS; no source diff was present.

Changed paths: `none` (verified no-op).

No next packet was started.
