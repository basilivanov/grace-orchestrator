# W08 — Recovery Controller and Proactive Stuck Scanner

Status: READY

Parent TZ: `docs/work/TZ_GRACE_ORCHESTRATOR_RUNTIME_SCOPE_CONTEXT_HARDENING.md`

## Goal

Make stuck runtime states self-detecting and safely recoverable without manual DB edits.

## Scope

- `src/grace_control/core/recovery_controller.py`
- `src/grace_control/core/lease_manager.py`
- `src/grace_control/services/feature_planning_service.py`
- health/API routers
- startup/background task wiring
- `tests/`

## Tasks

1. Add background scanner for expired leases, stale worker heartbeat, stuck RUNNING packets, and recoverable blocks.
2. Detect inconsistent states:
   - RUNNING packet with expired lease;
   - worker heartbeat stale;
   - worker has current packet but no lease;
   - lease exists but packet not RUNNING;
   - feature has no progress;
   - PLAN_FAILED repairable cases.
3. Auto-apply only deterministic safe recovery.
4. Keep LLM repair disabled or guarded by explicit config.
5. Fix plan repair path so compiler rejection can be reported/repaired instead of becoming unreachable.
6. Emit recovery events and diagnostics for every decision.

## Acceptance

- Stale RUNNING packets are detected by scanner.
- Dead workers become inactive.
- Orphan leases are cleaned safely.
- Recoverable blocked packets produce actionable diagnostics.
- Unsafe LLM repair is not auto-applied by default.

## Required tests

- `test_stuck_running_with_expired_lease_recovered_by_scanner`
- `test_worker_stale_heartbeat_marks_worker_inactive`
- `test_lease_without_running_packet_is_cleaned`
- `test_blocked_recoverable_emits_recovery_waiting_event`
- `test_try_approve_or_repair_plan_handles_compiler_rejection`
- `test_recovery_scanner_does_not_apply_unsafe_llm_repair_by_default`

## Submission

Create `docs/work/Feat_1/exchange/inbox/W08_001_SUBMISSION.md` when done.
