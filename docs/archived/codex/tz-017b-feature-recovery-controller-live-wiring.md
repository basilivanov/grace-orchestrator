# TZ 017b — Feature Recovery Controller: live retry/switch/repack/block wiring

Audience: Flash coder / literal executor.

Parent specs:

```text
docs/codex/tz-017-feature-recovery-escalation-policy.md
docs/codex/tz-020-golden-fixtures-staged-scenarios.md
docs/codex/tz-019c-admin-event-stream-and-recovery-observability.md
```

Goal: implement the live orchestration layer that consumes `RecoveryDecision` from `feature_recovery.py` and safely performs recovery actions: retry same coder, switch coder/model, return to architect, escalate architect, retry verifier/reviewer/merge, or block the feature.

`TZ-017` Phase 1 is only the deterministic policy core. This TZ is Phase 2: controller + API + worker integration + events + tests.

---

## 1. Current gap

`TZ-017` defines:

```text
FailureSignal → classify_failure(...) → decide_recovery(...) → RecoveryDecision
```

But it does not fully define the live part:

```text
who calls the policy
when FailureSignal is built
where RecoveryDecision is stored
who schedules retry/switch/repack/block
how requested executor/model reaches the next attempt
how recovery events are emitted
how admin UI reads recovery state
how loops are prevented
```

This TZ closes that gap.

---

## 2. High-level flow

```text
packet rejected / blocked / merge failed / verifier failed / reviewer failed
→ build FailureSignal from Packet + latest PacketRun + result_json/events
→ classify_failure(signal)
→ decide_recovery(signal, policy)
→ persist RecoveryDecision
→ emit recovery events
→ apply safe RecoveryAction
→ admin UI displays recovery summary/events
```

Recovery never replaces acceptance, scope guard, reviewer, or merge validation.

---

## 3. New files

Add:

```text
src/grace_control/core/recovery_controller.py
src/grace_control/api/routers/recovery.py
src/grace_control/worker/recovery_client.py  # optional
```

Existing/parent file:

```text
src/grace_control/core/feature_recovery.py
```

Tests:

```text
tests/grace_control/core/test_recovery_controller.py
tests/api/test_recovery_api.py
tests/worker/test_worker_recovery_integration.py
tests/golden_fixtures/test_fixture_recovery_scenarios.py
```

---

## 4. Persistence

Recovery decisions must be structured and queryable.

Preferred: add DB table `recovery_decisions`:

```text
id = rec_<nanoid>
feature_id
wave_id
packet_id
run_id
attempt_number
failure_class
action
reason
current_executor_id
next_executor_hint
acceptance_profile
next_acceptance_profile
status: proposed/applied/failed/skipped/superseded
payload_json
created_at
applied_at
```

If adding a table is too much for first patch, store the same shape in `PacketRun.result_json["recovery"]` plus events. But API must still return recovery history reliably.

---

## 5. Recovery actions

### RETRY_SAME_CODER

```text
packet → READY
next attempt uses same executor when possible
emit recovery_retry_same_coder
```

### SWITCH_CODER

```text
packet → READY
set requested_executor_id / next_executor_hint for next attempt
emit recovery_switch_coder
```

The next worker attempt must honor the requested executor. Do not silently use the same failing executor after a switch decision.

### RETURN_TO_ARCHITECT

```text
packet exits normal coder retry loop
store architect repair request payload
packet → BLOCKED or architect_repack_needed equivalent
emit recovery_return_to_architect
```

First patch does not need to run architect LLM automatically. It only creates the repair request and makes it visible.

### ESCALATE_ARCHITECT

```text
packet/feature marked escalated or blocked
requires stronger architect/reviewer/human decision later
emit recovery_escalate_architect
```

### RETRY_VERIFIER / RETRY_REVIEWER

```text
request verifier/reviewer retry if those stages can run independently
otherwise store retry requested metadata and show it in admin UI
emit recovery_retry_verifier / recovery_retry_reviewer
```

Do not rerun coder when only verifier/reviewer parser failed.

### RETRY_MERGE

```text
allowed only for merge-retryable failures and below retry limit
increment merge_attempt_count
emit recovery_retry_merge
```

Dirty target repo, merge conflict, missing worktree/branch after preflight are blockers unless policy says otherwise.

### BLOCK_FEATURE

```text
packet → BLOCKED
feature recovery summary blocked=true
emit recovery_block_feature
```

Blocked packets are not automatically retried.

### NO_ACTION

```text
record skipped/no_action decision
emit recovery_no_action
no state mutation
```

---

## 6. Executor/model switch contract

Use one canonical field for requested executor.

Suggested:

```text
Packet.spec_json["recovery"]["requested_executor_id"] = "coder-agy-sonnet"
```

Worker/executor selection rules:

```text
if requested_executor_id exists and available → use it
if unavailable → recovery apply failed or fallback according to policy
clear it after accepted result or after it is consumed safely
record previous_executor_ids from run history
```

Do not hardcode model names in controller. Use executor registry if available.

---

## 7. Loop guards

Controller must compute or store counters:

```text
coder_attempt_count
same_executor_failure_count
architect_repair_count
verifier_retry_count
reviewer_retry_count
merge_attempt_count
unknown_failure_count
```

Policy limits from TZ-017:

```text
coder_attempt_count < 2 → retry same coder
coder_attempt_count >= 2 and total < 4 → switch coder
coder_attempt_count >= 4 → return to architect
architect_repair_count >= 2 → escalate architect
merge retryable attempts >= 2 → block feature
```

No infinite loops.

---

## 8. API endpoints

Add:

```text
POST /api/recovery/evaluate/{packet_id}
GET /api/recovery/packets/{packet_id}
GET /api/recovery/features/{feature_id}
```

### POST /api/recovery/evaluate/{packet_id}

Input:

```json
{"trigger": "packet_rejected", "apply": true}
```

Behavior:

```text
load packet/history
build FailureSignal
classify/decide
persist decision
apply if requested
emit events
return decision
```

Response:

```json
{
  "packet_id": "pkt_...",
  "decision_id": "rec_...",
  "failure_class": "retryable_coder",
  "action": "switch_coder",
  "reason": "T1 failed twice",
  "next_executor_hint": "coder-agy-sonnet",
  "status": "applied"
}
```

---

## 9. Worker integration

When enabled:

```text
worker releases packet as rejected/blocked/failed
→ worker/API calls recovery evaluate/apply
→ recovery controller decides next action
```

Replace old direct rejection retry path when controller is enabled:

```text
old: _handle_rejection(packet_id) → retry_packet(packet_id)
new: recovery evaluate/apply
```

Add feature flag:

```text
GRACE_RECOVERY_CONTROLLER_ENABLED=true|false
```

Rollout:

```text
A. implemented but disabled by default
B. enabled for staged golden fixtures
C. enabled for STRICT self-improvement
D. enabled for normal features
```

When disabled, old behavior may remain temporarily, but emit event/summary that recovery controller is disabled.

---

## 10. Merge failure integration

Merge failures must become recovery triggers.

Required machine-readable error codes:

```text
DIRTY_TARGET_REPO
MERGE_CONFLICT
MISSING_WORKTREE
MISSING_BRANCH
TRANSIENT_MERGE_ERROR
NO_CHANGES
```

After merge failure:

```text
record merge event
build FailureSignal
RecoveryController decides RETRY_MERGE or BLOCK_FEATURE
```

---

## 11. Events for admin UI

Emit events required by TZ-019c:

```text
recovery_signal_built
recovery_classified
recovery_decision_made
recovery_retry_same_coder
recovery_switch_coder
recovery_return_to_architect
recovery_escalate_architect
recovery_retry_verifier
recovery_retry_reviewer
recovery_retry_merge
recovery_block_feature
recovery_no_action
recovery_apply_failed
```

Payload includes:

```text
feature_id, wave_id, packet_id, run_id, attempt_number
failure_class, action, reason
current_executor_id, next_executor_hint
acceptance_profile, next_acceptance_profile
trigger
```

---

## 12. Admin UI data contract

Controller/API must provide enough data for Mission Control:

```text
feature recovery summary
packet Recovery/Stability block
events panel recovery events
old executor → new executor for switch coder
blocker reason
architect return/escalation reason
```

Do not implement full UI here unless bundled with admin task. But data/events must be available.

---

## 13. Tests required

### Unit tests

```text
test_controller_builds_signal_from_latest_packet_run
test_controller_persists_decision
test_controller_emits_decision_event
test_retry_same_coder_sets_packet_ready
test_switch_coder_sets_requested_executor
test_return_to_architect_exits_normal_retry_loop
test_escalate_architect_blocks_packet
test_retry_merge_increments_merge_attempt_count
test_dirty_target_blocks_feature
test_no_action_does_not_mutate_packet_state
test_strict_profile_never_downgraded
```

### API tests

```text
test_recovery_evaluate_rejected_packet_returns_decision
test_recovery_evaluate_apply_false_only_records_proposed
test_recovery_evaluate_apply_true_applies_action
test_recovery_packet_history_endpoint
test_recovery_feature_summary_endpoint
test_recovery_events_written
test_recovery_switch_coder_response_contains_next_executor
test_recovery_true_blocker_response_contains_block_reason
```

### Worker tests

```text
test_worker_calls_recovery_after_rejected_release
test_worker_does_not_call_old_retry_when_recovery_enabled
test_worker_applies_switch_coder_on_next_attempt
test_worker_blocks_true_blocker
test_worker_calls_recovery_after_merge_failure
```

### Staged fixture tests

Use TZ-020 fixtures:

```text
recovery_coder_fail_once_retry_same
recovery_coder_fail_twice_switch_model
recovery_coder_fail_four_times_return_architect
recovery_merge_dirty_target_true_blocker
recovery_merge_transient_retry
recovery_blocked_retry_denied
recovery_verifier_return_to_architect
recovery_reviewer_rework_to_coder
recovery_strict_profile_never_downgraded
```

No real LLMs/agents in these tests.

---

## 14. Safety invariants

Controller must never:

```text
skip acceptance
skip scope guard
skip reviewer for STRICT
downgrade STRICT to NORMAL/FAST
auto-resolve git conflicts
auto-merge after failed reviewer
auto-retry blocked true blockers
silently ignore requested executor failure
loop forever
```

Add tests for these invariants.

---

## 15. Acceptance criteria

Done only if:

```text
1. RecoveryController exists.
2. It builds FailureSignal from real packet/run data.
3. It calls classify_failure and decide_recovery.
4. It persists structured RecoveryDecision history.
5. It emits recovery events.
6. RETRY_SAME_CODER makes packet READY safely.
7. SWITCH_CODER requests a different executor for next attempt.
8. RETURN_TO_ARCHITECT exits normal coder retry loop.
9. ESCALATE_ARCHITECT blocks/escalates instead of infinite retry.
10. RETRY_MERGE only applies to merge-retryable failures.
11. TRUE_BLOCKER blocks feature/packet.
12. Worker can call recovery after rejected/blocked/merge failed.
13. Old automatic retry is not used when controller is enabled.
14. Admin/API can read recovery summary/events.
15. Staged recovery fixture tests exist for key decisions.
16. Existing live golden behavior is unchanged when feature flag is disabled.
```

---

## 16. Do not do

```text
Do not implement full architect LLM repack in this task.
Do not run real architect/coder/reviewer in controller tests.
Do not auto-resolve merge conflicts.
Do not add manual override commands.
Do not remove acceptance/reviewer/scope gates.
Do not enable recovery controller globally before staged fixtures pass.
Do not create two competing executor-selection mechanisms.
```

---

## 17. Final coder report format

Coder must report:

```text
Files changed
RecoveryController added: yes/no
Recovery persistence added: table/result_json
Recovery API added: yes/no
Worker integration added: yes/no
Feature flag added: yes/no
SWITCH_CODER requested executor wired: yes/no
RETURN_TO_ARCHITECT behavior added: yes/no
MERGE retry/block behavior added: yes/no
Recovery events emitted: yes/no
Admin summary data available: yes/no
Tests added
Tests run
Remaining blockers
```
