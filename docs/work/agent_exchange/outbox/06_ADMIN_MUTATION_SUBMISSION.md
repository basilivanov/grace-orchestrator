WEB_ORCH_REPORT: SUBMISSION 06_ADMIN_MUTATION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 86060bf6d59aab7b4a20c6338327f1d7e67a506a
WEB_ORCH_CHECKS: PASS

# TZ 06_ADMIN_MUTATION

Implemented and pushed the guarded mutation-facade refactor.

## Responsibility map and structure

- `admin_mutation_service.py`: stable `AdminMutationService` facade, reduced
  from 931 to 190 physical lines. It retains construction and ordinary action
  execution/audit flow.
- `admin_mutation_catalog.py` (239 lines): capability catalog, disabled
  behavior, entity-state reads and state-aware availability.
- `admin_mutation_validation.py` (250 lines): pure project/action/entity/
  confirmation validation, bounded parameters, request IDs and base DTOs.
- `admin_mutation_transport.py` (146 lines): selected-project identity guard
  and exactly-one mutation transport attempt.
- `admin_mutation_result.py` (195 lines): success/failure/wait/planned,
  identity and unknown-outcome normalization, including the exact
  `UNKNOWN_OUTCOME_MESSAGE`.
- `admin_mutation_openapi.py` (182 lines): safe path, method/discovery,
  parameter and strong-confirmation gates for discovered OpenAPI mutations.

The facade MRO retains `available_controls`, `execute`, `execute_openapi`,
`_read_entity_state` and `_call_project` on `AdminMutationService`; existing
instance/class monkeypatch targets continue to resolve through the facade.
`self._hub`, `hub._registry`, `hub._request` and the mutation-boundary
`hub._client_factory(context)` remain the transport boundaries. The stable
module exports `AdminMutationService`, `normalize_mutation_result` and
`UNKNOWN_OUTCOME_MESSAGE` unchanged.

Largest touched functions by `len(source) // 4`:

- `normalize_mutation_result`: 1092
- `execute_openapi`: 828
- `execute`: 791
- `_call_project`: 678
- `available_controls`: 543
- `_control_availability`: 426
- `_read_entity_state`: 308

All touched/new modules are below 1000 lines and every function is below the
4000 estimated-token limit. No routers, schemas, DB, settings, state, UI,
acceptance or cross-project files were changed. No tests or behavioral
assertions were changed, and no allowlist entry was added.

## Verification

- Focused mutation/Control Center/router/OpenAPI suite: **66 passed, 1
  skipped**. This includes Stage 06, Stage 06 review, Stage 07, Stage 07
  matrix, admin router and OpenAPI path tests.
- `python3 -m py_compile` for facade and all five owners: PASS.
- Targeted Ruff for facade and all five owners: PASS.
- Targeted `python3 scripts/grace_lint.py`: PASS.
- `git diff --check`: PASS.
- AST comparison against the clean parent: `missing_methods=[]`,
  `ast_mismatches=[]` for the public methods, private seams and all moved pure
  helpers; no signature or function-body drift.
- OpenAPI/route semantic tests passed; no route or schema file changed.
- `make test`: **1584 passed, 2 skipped, 33 failed**. The clean parent run
  with the same command, environment and arguments produced the identical
  counts and exact failure-node/output set:

  ```text
  tests/grace_control/config/test_w3_config_cleanup.py::test_agent_profile_minimal_repo_fields
  tests/grace_control/config/test_w3_config_cleanup.py::test_agent_profile_prompt_content
  tests/grace_control/core/test_execution_environment_vertical_slice.py::test_architect_prompt_contains_environment_facts
  tests/grace_control/runtime/test_opencode_attach_runtime.py::TestAttachRuntimeMode::test_packet_timeout_does_not_kill_server
  tests/grace_control/runtime/test_opencode_runtime_adapter.py::TestExecutionBackend::test_backend_maps_result
  tests/grace_control/runtime/test_opencode_runtime_adapter.py::TestExecutionBackend::test_backend_with_observability_writes_artifacts_and_events
  tests/grace_control/runtime/test_opencode_runtime_adapter.py::TestExecutionBackend::test_backend_with_observability_writes_jsonl_format
  tests/grace_control/services/test_context_builder_safety.py::TestRunContextBuilderMutationGuard::test_mutation_guard_raises_on_dirty_repo
  tests/grace_control/services/test_context_builder_safety.py::TestMutationGuardBlocksArchitect::test_exception_path_skips_architect
  tests/grace_control/services/test_feature_planning_service.py::test_run_architect_persists_resolved_mini_swe_profile
  tests/grace_control/services/test_feature_planning_service.py::test_run_architect_uses_disposable_standalone_clone
  tests/grace_control/services/test_feature_planning_store.py::TestFeaturePlanningStore::test_run_context_builder
  tests/grace_control/services/test_feature_planning_store.py::TestFeaturePlanningStore::test_run_architect
  tests/grace_control/services/test_feature_planning_store.py::TestFeaturePlanningStore::test_approve_plan_sets_queued_and_readies_first_wave
  tests/grace_control/services/test_feature_planning_store.py::TestFeaturePlanningStore::test_regenerate_plan_resets_state
  tests/grace_control/services/test_feature_planning_store.py::TestFeaturePlanningStore::test_context_builder_sets_stdout_stderr_paths
  tests/grace_control/services/test_feature_planning_store.py::TestFeaturePlanningStore::test_architect_sets_stdout_stderr_paths
  tests/grace_control/services/test_feature_planning_store.py::TestFeaturePlanningStore::test_approve_creates_ready_first_wave_draft_rest
  tests/grace_control/services/test_feature_planning_store.py::TestFeaturePlanningStore::test_packets_use_canonical_pkt_uid
  tests/grace_control/services/test_feature_planning_store.py::TestFeaturePlanningStore::test_approve_plan_event_includes_approval_mode
  tests/grace_control/services/test_queue_service.py::test_rework_lineage_end_to_end_unblocks_dependent_wave
  tests/grace_control/services/test_session_hardening.py::test_session_resume_used_false_when_resume_safe_false
  tests/grace_control/services/test_session_hardening.py::test_session_resume_used_true_when_all_gates_pass
  tests/grace_control/services/test_session_hardening.py::test_session_resume_used_false_when_resume_mode_never
  tests/grace_control/services/test_session_resume_followup.py::TestAgentProfileResumeFields::test_coder_deepseek_flash_has_resume_fields
  tests/grace_control/services/test_session_resume_followup.py::TestAgentRunServiceSessionExtractionIntegration::test_cli_backend_agy_command_extracts_conversation_id
  tests/grace_control/services/test_session_resume_followup.py::TestAgentRunServiceSessionExtractionIntegration::test_cli_backend_opencode_command_extracts_session_id
  tests/grace_control/services/test_session_resume_phase2.py::TestResumeFlagInjection::test_resume_injects_session_flag
  tests/grace_control/services/test_session_resume_phase2.py::TestResumeFlagInjection::test_fork_injects_fork_flag
  tests/grace_control/services/test_session_resume_phase2.py::TestResumeFlagInjection::test_agy_conversation_flag
  tests/grace_control/services/test_session_store.py::TestFindLatest::test_finds_latest_for_role
  tests/grace_control/services/test_session_store.py::TestFindLatest::test_filters_by_executor_id
  tests/grace_control/services/test_session_store.py::TestFindForFork::test_finds_any_completed
  ```

- `make lint`: current and clean parent both stop at
  `.venv/bin/python: No module named ruff`; targeted Ruff above passes.
- `make docs-check`: current and clean parent both report drift in exactly
  `docs/openapi.json`, `docs/state-diagram.md` and `docs/packet-states.md`.

Mutation semantics remain unchanged: one explicit project only, fail-closed
capability/state catalog, required confirmation and typed strong confirmation,
runtime identity mismatch/unavailable distinction, no retry after ambiguous
transport, exact unknown-outcome DTO/message, planned/wait handling, bounded
request/actor propagation, masking, safe OpenAPI discovery/path/parameter
gates, and no direct Hub-side project DB/filesystem/Git/process mutation.
No follow-up task or router refactor was started.
