# Execution Packet: FEAT-GRACE-CP-RETRY-W05-AUTO-RETRY

## Objective

Add automatic retry for REJECTED packets: worker detects rejection → calls retry_packet() (REJECTED→READY) → packet re-enters queue → worker claims again. After max_attempts (3), escalate to FAILED.

Currently, REJECTED packets just sit there — worker doesn't retry them. This packet closes the loop.

## Slice

- slice_id: `SLICE-RETRY`
- slice_slug: `auto-retry`
- feature_id: `FEAT-GRACE-CP-RETRY`
- packet_id: `FEAT-GRACE-CP-RETRY-W05-AUTO-RETRY`
- wave_id: `W05`
- status: `ready`
- phase: `PHASE-POST-MVP`
- depends_on: `FEAT-GRACE-CP-WORKER-W03-WORKER-LOOP, FEAT-GRACE-CP-STATE-W01-STATE-MACHINE`
- feature_dir: `grace/packets/FEAT-GRACE-CP-RETRY`

## Source Of Truth

- `CANONICAL_DECISIONS.md` §1 (retry strategy)
- `FINAL_DECISIONS.md` §5 (rework loop, max 3 attempts)
- `tasks/PHASE_1_CORE_REVISED.md` — retry_packet function exists

## Impacted Modules

- `M-GRACE-CP-WORKER`
- `M-GRACE-CP-STATE`

## Allowed Write Scope

- `src/grace_control/worker/worker.py`
- `src/grace_control/core/packet_operations.py`
- `tests/test_worker_retry.py`
- `grace/packets/FEAT-GRACE-CP-RETRY/**`

## Frozen Scope

- `src/prefect_grace/**`
- `src/grace_control/api/**`
- `src/grace_control/db/**`
- `src/grace_control/adapters/**`
- `src/grace_control/cli/**`

## Must Preserve

- retry_packet() already exists in packet_operations.py
- Worker's _main_loop catches exceptions from release — use this catch block for retry
- Max 3 attempts (from packet.max_attempts)
- After max_attempts: transition to FAILED, stop retrying
- Escalation counter must be per-packet (not global)

### GRACE Canon Compliance

- AI_HEADER, MODULE_CONTRACT, FUNCTION_CONTRACT на всех новых функциях
- START_BLOCK/END_BLOCK для логических секций
- log_event() для логирования, trace_context() для сквозного trace_id

## Required Design Decisions

### 1. Worker retry logic

In `_main_loop`, after `release_packet` returns, check result:

```python
result = await self.executor.execute(claim.packet_id, self.worker_id)
status = "accepted" if result.accepted else "rejected"
release_resp = await self.api.release_packet(claim.packet_id, self.worker_id, status, result.model_dump())

# If rejected and attempts remain, mark for retry
if status == "rejected":
    from grace_control.core.packet_operations import retry_packet as _mark_retry
    try:
        _mark_retry(claim.packet_id)
        # Packet moves: REJECTED → READY, will be claimed in next loop iteration
    except StateTransitionError:
        # Max attempts reached — packet stays REJECTED or goes to FAILED
        from grace_control.core.packet_operations import mark_failed as _mark_failed
        _mark_failed(claim.packet_id, "Max retry attempts reached")
```

### 2. No new endpoint needed

Retry is internal to the worker — no API changes.

## Implementation Requirements

1. Update `src/grace_control/worker/worker.py` `_main_loop`:
   - After release with "rejected", call retry_packet()
   - On StateTransitionError (max attempts), call mark_failed()
   - Log retry attempt with attempt_count

2. Create `tests/test_worker_retry.py`:
   - test_auto_retry_rejected_packet
   - test_max_attempts_escalates_to_failed
   - test_retry_reclaims_same_packet

## Acceptance Criteria

- [ ] Worker auto-retries REJECTED packets
- [ ] After max_attempts, packet transitions to FAILED
- [ ] Retry log includes attempt_count
- [ ] All existing tests still pass
- [ ] New tests pass: `pytest tests/test_worker_retry.py -v`

## Verification

```bash
pytest tests/test_worker_retry.py -v
pytest tests/ --asyncio-mode=auto --ignore=tests/test_hello_grace.py -v
```

## Escalation Triggers

- Infinite retry loop (same packet keeps failing with same error)
- retry_packet() returns False when it should succeed
- Worker crashes during retry cycle

## Reviewer Gate

- auto-retry must not loop infinitely
- Must respect max_attempts
- Must log each retry with attempt number
