WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_TYPED_ADMIN_READ_MODELS
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 003d3c659e5cea64c5b1e8aa797e2d9a99b0c773
WEB_ORCH_CHECKS: PASS

Synced base

- Synced base SHA: `9fe14505e5fffe08a08b40b0e428c4b0d6367ef8`.
- Initial `git status --short`: only the pre-existing untracked
  `.env.bak-mini-endpoint-20260705170600` and `parse_list.py`; both were
  preserved and were not included in either commit.
- The implementation commit was pushed to `origin/main`.

Changed files

- `src/grace_control/services/admin_read_models.py`
- `src/grace_control/services/admin_cross_project_helpers.py`
- `src/grace_control/services/admin_cross_project_overview_service.py`
- `src/grace_control/services/admin_overview_read_service.py`
- `src/grace_control/services/admin_packet_read_service.py`
- `src/grace_control/services/admin_pipeline_read_service.py`
- `tests/grace_control/services/test_admin_read_models.py`
- `tests/grace_control/architecture/test_admin_read_models_boundary.py`

Typed models and exact serialized keys

- `CrossProjectCoverage`: `projects_total`, `projects_responded`,
  `projects_failed`, `projects_disabled`, `projects_partial`, `partial`.
- `AttentionItem`: `severity`, `project_key`, `project_name`, `kind`,
  `entity_type`, `entity_id`, `title`, `reason`, `timestamp`, `detail_url`.
- `ProjectHealthSnapshot`: `supervisor_alive`, `api_alive`, `workers_alive`,
  `db_ok`, `code_sha`, `version`.
- `WorkerSnapshot` (Admin only): `id`, `status`, `current_packet_id`,
  `last_heartbeat`, `started_at`, `current_elapsed`.
- `PacketRunSummary`: `run_id`, `run_number`, `worker_id`, `executor_id`,
  `model`, `status`, `duration_ms`, `started_at`, `finished_at`,
  `elapsed_seconds`, `is_running`, `tokens_in`, `tokens_out`, `cost_usd`,
  `base_sha`, `integration_base_sha`.
- `PipelineStageView`: `key`, `label`, `status`, `started_at`, `finished_at`,
  `duration_ms`, `meta`, `target_tab`.

All models are frozen and slotted and expose explicit `to_dict()` methods.
Service/API boundaries continue to return ordinary JSON-safe dictionaries.
The smaller `_coverage_from_results()` contract remains exactly the existing
three-key shape: `projects_total`, `projects_responded`, `projects_failed`.
The packet-detail `runs_summary` subset was intentionally not widened to the
rich packet-runs contract.

Boundary distinctions and pipeline evidence

Admin `WorkerSnapshot` remains distinct from the Packet 6 lifecycle worker
shape: Admin uses `id` and `current_elapsed`, while lifecycle continues to use
`worker_id` and its existing response contract. No lifecycle source or JSON
shape was changed.

Characterization of the current pipeline construction showed that all repeated
operator pipeline stage cards share the same eight-key shape above. They now
serialize through `PipelineStageView`. The separate `derive_stages()` StageRun
telemetry rows remain local because they are a different heterogeneous,
20-field telemetry contract and are not silently normalized in this packet.

Verification

- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/services/test_admin_read_models.py tests/grace_control/services/test_admin_aggregation_service.py tests/grace_control/api/test_admin_router.py tests/grace_control/api/test_admin_pipeline_contract.py tests/grace_control/api/test_admin_cross_project_observability.py tests/grace_control/architecture/test_admin_read_models_boundary.py`: **104 passed**.
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api/test_admin_control_center_stage07.py tests/grace_control/api/test_admin_control_center_stage07_matrix.py`: **5 passed, 1 skipped**.
- `PYTHONPATH=src .venv/bin/pytest -q tests/supervisor/test_lifecycle_api.py`: **8 passed**.
- `python3 scripts/grace_lint.py` on all changed Python files/tests: **PASS**.
- `ruff check` on all changed Python files/tests: **PASS**.
- `python3 -m py_compile` on all changed Python files: **PASS**.
- `git diff --check`: **PASS**.

The pytest runs emitted only existing dependency/deprecation warnings; no
environment-only topology timeout or unrelated failure occurred. No Wave 6+
work was started.
