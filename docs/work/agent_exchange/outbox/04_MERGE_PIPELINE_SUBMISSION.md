# TZ04 merge pipeline submission

WEB_ORCH_REPORT: SUBMISSION 04_MERGE_PIPELINE
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 392d787c8d84dc2472b91d64704fd947e688d6da
WEB_ORCH_CHECKS: PASS

## Implementation

Implementation commit: `392d787c8d84dc2472b91d64704fd947e688d6da`.

Modified:

- `src/grace_control/services/merge_service.py`

Created:

- `src/grace_control/services/merge_admission_service.py`
- `src/grace_control/services/merge_guard_service.py`
- `src/grace_control/services/merge_mutation_service.py`
- `src/grace_control/services/merge_cleanup_service.py`
- `src/grace_control/services/merge_recovery_service.py`

`merge_service.py` decreased from 1296 to 668 physical lines. The original
`merge_packet` was 6576 Grace-estimated tokens (`len(source) // 4`, 592
physical lines); the facade coordinator is now 2461 estimated tokens (264
physical lines).

Largest functions in the touched/new merge modules:

- `merge_service.py`: `merge_packet` — 2461 estimated tokens.
- `merge_admission_service.py`: `admit` — 715.
- `merge_guard_service.py`: `prepare` — 2096.
- `merge_mutation_service.py`: `execute` — 1145.
- `merge_cleanup_service.py`: `cleanup_worktree_for_merge` — 471;
  `cleanup_packet_branches` — 469.
- `merge_recovery_service.py`: `block_stale_packet` — 711.

## Responsibility and compatibility

| Previous responsibility | New owner |
| --- | --- |
| Runtime safety, fencing, deterministic order, merge lease admission | `MergeAdmissionService` |
| Target branch/base inspection, packet contract snapshot, stale-base recheck and consistency metadata | `MergeGuardService` |
| Fenced checkout/fetch/merge/push and conflict classification | `MergeMutationService` |
| Stale/conflict `BLOCKED_RECOVERABLE` routing and evidence/cleanup coordination | `MergeRecoveryService` |
| Fenced attempt-branch/worktree cleanup | `MergeCleanupService` |
| Public lifecycle coordination and stable result construction | `MergeService` |

Existing `GitService`, `MergeCoordinatorService`, `IntegrationRecheckService`,
`PacketService`, `ParallelLeaseService`, and `build_packet_contract` remain the
authoritative helpers; their business rules were reused, not copied.

`MergeService`, `MergeResult`, `is_merge_slot_wait`, the public
`merge_packet(...)` signature/result shape, and `cleanup_worktree(...)` seam
remain available at their existing import path. Existing private helper seams
remain as delegating compatibility methods. The demonstrated module-level
`GitService` monkeypatch still works because the facade constructs the patched
adapter and passes it to every owner. No behavioural test assertion was
weakened and no tests were changed or deleted.

Packet states/transitions, merge lease release, event/log names, artifact and
PacketRun evidence keys, target branch selection, stale-base/no-change/conflict
handling, rollback/cleanup, and IntegrationRecheckService ordering remain
unchanged. No DB/schema/API/config/state-machine files were touched.

## Verification

- `.venv/bin/python -m pytest tests/test_tz04_serialized_merge.py -q` — 12 passed.
- `.venv/bin/python -m pytest tests/test_tz05_stale_base_recheck.py -q` — 8 passed.
- `.venv/bin/python -m pytest tests/test_tz06_multiworker_integration.py -q` — 12 passed.
- `.venv/bin/python -m pytest tests/grace_control/core/test_post_refactor_audit_fixes.py -q` — 19 passed.
- `.venv/bin/python -m pytest tests/grace_control/services/test_queue_service.py -q` — 27 passed, 1 failed baseline node.
- `.venv/bin/python -m pytest tests/grace_control/api/test_admin_controls_stage06.py -q` — 17 passed.
- `.venv/bin/python -m pytest tests/test_w07_worker_error_handling.py -q` — 18 passed.
- `make test` — 1584 passed, 2 skipped, 33 failed.
- `make lint` — environment failure: `.venv/bin/python: No module named ruff`.
- `.venv/bin/python -m py_compile` on `merge_service.py` and all five new merge modules — PASS.
- `scripts/grace_lint.py` targeted at `merge_service.py` and all five new merge modules — PASS.
- `git diff --check` — PASS.
- Full `python3 scripts/grace_lint.py src/grace_control` remains non-zero from repository-wide legacy violations; current count is 1138 versus 1143 on clean parent, with no touched merge-module violations.

The queue failure is exactly `test_rework_lineage_end_to_end_unblocks_dependent_wave`, identical to clean parent. The broad clean-parent run with the same `tests/grace_control/ -q` arguments produced `1584 passed, 2 skipped, 33 failed`; the exact 33 `FAILED` node set is identical. The seven direct-suite failure sets are also identical to clean parent. No allowlist changes were made, and no follow-up TZ was started.
