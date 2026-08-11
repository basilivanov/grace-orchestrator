# TZ02 Packet Execution — resubmission

## Scope

Only `docs/work/agent_exchange/inbox/02_PACKET_EXECUTION_REVIEW.md` was addressed. No next task was started.

## Implementation

`c9f8e58701a4ddec05ce1757992ab55384153f5a` is pushed to `origin/main`.

The review headroom blocker is closed with two coherent responsibility boundaries:

- `PacketExecutionWorkspaceService` owns target/layout resolution, workspace mode safety, preflight/worktree/scoped-copy construction, and rework-seed replay.
- `PacketExecutionCompletionService` owns verifier/reviewer routing, terminal persistence, replay metadata, patch capture, cleanup, and rework packet creation.
- The existing dedicated preflight, runtime, post-execution, rerun, and observability services remain authoritative for their existing responsibilities.
- `PacketExecutionAdapter`, `ExecutionResult`, `_call_executor`, and the compatibility helper re-exports remain available from `grace_control.adapters.packet_executor`.
- Existing module-level gate/database/rework symbols remain available so old callers and test patch points continue to work.

Readable `opencode`, `origin`, and `state_root` identifiers were restored. Narrow GRC103/GRC106/GRC109 allowlist entries document only the moved compatibility/metadata false positives. GraceLint rule semantics were not changed, and no GRC005/GRC012 suppression was added.

## Final size and function estimates

Estimates are `len(source) // 4` for the function source.

| Module | Physical lines | Largest function | Estimate |
| --- | ---: | --- | ---: |
| `packet_executor.py` | 764 | `execute` | 2683 |
| `packet_execution_completion_service.py` | 789 | `route_after` | 2960 |
| `packet_execution_observability_service.py` | 296 | `capture_evidence` | 617 |
| `packet_execution_post_service.py` | 289 | `enforce_scope` | 2523 |
| `packet_execution_preflight_service.py` | 178 | `prepare` | 1516 |
| `packet_execution_rerun_service.py` | 107 | `dispatch` | 500 |
| `packet_execution_runtime_service.py` | 413 | `run` | 2226 |
| `packet_execution_workspace_service.py` | 633 | `prepare` | 2331 |

The compatibility `_prepare_workspace` facade in `packet_execution_runtime_service.py` is 140 estimated tokens; the actual workspace preparation path is `PacketExecutionWorkspaceService.prepare` at 2331 estimated tokens.

## Verification

- Focused execution/runtime suite: `106 passed, 585 warnings`.
- Final full suite on `c9f8e587`: `1585 passed, 2 skipped, 32 failed, 2744 warnings`.
- Parent baseline `1b6e56d66db285d0c09be4c91fa8b1d9690bbbb1` in a clean temporary worktree, using the same test arguments and shared `.venv`: `1585 passed, 2 skipped, 32 failed, 2780 warnings`.
- The sorted SHA-256 of the final and baseline failure-node lists is identical: `c9af3dfb82262a3c01c13e902df6688338f1fe5220a317c0accdfd5aedf7fdfe`. The `comm` comparison was empty, so no new failure was introduced by TZ02.

The identical stable failure list for both baseline and resubmission is:

```text
tests/grace_control/config/test_w3_config_cleanup.py::test_agent_profile_minimal_repo_fields
tests/grace_control/config/test_w3_config_cleanup.py::test_agent_profile_prompt_content
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
tests/grace_control/services/test_feature_planning_store.py::test_regenerate_plan_resets_state
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

- Targeted `scripts/grace_lint.py` for all eight execution modules: PASS.
- `python3 -m py_compile` for all eight execution modules: PASS.
- `git diff --check`: PASS.
- `make lint`: BLOCKED by the existing environment dependency gap, exact output:

  ```text
  .venv/bin/python -m ruff check src/grace_control/
  /opt/grace-orchestrator/.venv/bin/python: No module named ruff
  make: *** [Makefile:33: lint] Error 1
  ```

  The repository-supported alternate `scripts/grace_lint.py` checks passed per file above; `make lint` itself is not claimed as passed.

No behavioral assertion was weakened; selftest ordering, context gate, rerun one-shot routing, workspace/base resolution, no-change and existing-commit handling, scope/diagnostic routing, evidence/persistence keys, cleanup, and terminal statuses remain covered by the focused/full comparison.

WEB_ORCH_REPORT: RESUBMISSION 02_PACKET_EXECUTION
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: c9f8e58701a4ddec05ce1757992ab55384153f5a
WEB_ORCH_CHECKS: PASS
