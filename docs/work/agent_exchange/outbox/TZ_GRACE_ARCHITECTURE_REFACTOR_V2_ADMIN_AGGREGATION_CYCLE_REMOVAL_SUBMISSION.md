WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_ADMIN_AGGREGATION_CYCLE_REMOVAL
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 5569ac67eb2288df2274e4140c7406c11e1a1bfb
WEB_ORCH_CHECKS: PASS

## Sync

- Synced base SHA: `1fe174d7d98930e3fae8c884f2f70783f65c7369`.
- Initial `git status --short` contained only the preserved untracked files:
  `.env.bak-mini-endpoint-20260705170600` and `parse_list.py`.
- `git switch main`, `git fetch origin main`, and `git merge --ff-only origin/main` completed successfully before implementation.

## Changed files

- `src/grace_control/services/admin_aggregation_service.py`
- `src/grace_control/services/admin_artifact_read_service.py`
- `src/grace_control/services/admin_logs_read_service.py`
- `src/grace_control/services/admin_packet_read_service.py`
- `src/grace_control/services/admin_pipeline_read_service.py`
- `src/grace_control/services/admin_packet_run_resolver.py`
- `src/grace_control/services/admin_read_ports.py`
- `tests/grace_control/architecture/test_admin_aggregation_dependency_graph.py`
- `tests/grace_control/services/test_admin_packet_run_resolver.py`

## Final dependency graph

```text
SizeCalculator ───────────────────────────────┐
PacketRunResolver ──> ArtifactReadService ──> PipelineReadService
       │                         │                    │
       └──────────────────────> LogsReadService       │
                                      │               │
                                      └───────────────┘
                                                     │
SizeCalculator ───────────────────────────────────> PacketReadService
                                                     │
SizeCalculator ───────────────────────────────────> FeatureReadService
OverviewReadService ─────────────────────────────> AggregationService
```

The effective construction order in `AdminAggregationService.__init__` is:

```text
size_calc → resolver → artifacts(resolver) → logs(resolver)
→ pipeline(artifacts) → packet(size_calc, pipeline, logs)
→ features(size_calc, pipeline) → overview
```

All collaborator fields are assigned by their owning constructor. The
aggregation root performs no post-construction writes to child private fields.

## Resolver compatibility

`AdminPacketReadService.resolve_run()` was removed after repository search found
no external consumer. `PacketRunResolver.resolve_run(db, packet_id, run_id)` is
now the shared lower-level owner and preserves canonical ID, legacy composed ID,
numeric run number, and invalid-selector semantics. The existing private
`AdminAggregationService._run_for_selector()` compatibility helper remains as a
thin delegate to the shared resolver; it does not own lookup logic.

## Removal evidence

- `AdminAggregationService.__init__` contains no assignments equivalent to
  `self._packet._artifact_service = ...`, `self._packet._session_service = ...`,
  or `self._pipeline._artifact_service = ...`.
- `AdminArtifactReadService` and `AdminLogsReadService` receive one shared
  `PacketRunResolver`, and call `resolve_run` on it directly.
- `AdminPipelineReadService` receives `ArtifactEvidenceReader` explicitly.
- `AdminPacketReadService` receives `PacketSessionReader` explicitly.
- The AST architecture guard verifies no child-private root wiring, no
  setter-style collaborator injection, no packet-service resolver dependency,
  no high-level resolver imports, and dependency-field assignments only in
  `__init__` across the touched graph.
- Structural scan of `src/grace_control/services/admin_*.py` shows dependency
  assignments only in owning constructors; there are no post-construction
  collaborator writes from the aggregation root.

## Checks

- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/services/test_admin_aggregation_service.py` — 44 passed.
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_pipeline_contract.py` — 4 passed.
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_router.py` — 35 passed.
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_admin_aggregation_dependency_graph.py` — 4 passed.
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/services/test_admin_packet_run_resolver.py` — 4 passed.
- Session regression tests — 38 passed.
- `tests/ui/test_admin_ui_sizes.py` — 7 passed, 2 skipped.
- Combined relevant regression command — 136 passed, 2 skipped.
- `ruff check` on every changed Python file — PASS.
- `python3 scripts/grace_lint.py` on every changed Python file — PASS.
- `python3 -m py_compile` on every changed Python file — PASS.
- `git diff --check` — PASS.

Implementation commit: `5569ac67eb2288df2274e4140c7406c11e1a1bfb`.
