# TZ 017 — Feature Recovery / Escalation Policy for reliable feature delivery

Audience: Flash coder / literal executor.

Status: **DO NOT IMPLEMENT UNTIL CURRENT GOLDEN SERIES IS STABLE.**

Goal: add a deterministic recovery/escalation layer so a feature keeps moving toward DONE when packets fail, instead of getting stuck after one failed model/agent attempt. This must preserve all safety gates: no bypassing scope guard, deterministic acceptance, STRICT reviewer, dirty merge checks, or true blockers.

This is a full-scope specification for later implementation. For now, only keep it in `docs/codex/` and do not wire it into live runs until FAST/NORMAL/STRICT golden tests are green.

---

## 0. Product intent

We want the system to be persistent and resilient:

```text
feature should keep moving while failures are retryable
feature should stop only when there is a true blocker
```

Examples of retryable failures:

```text
coder missed part of TZ
unit tests failed
acceptance failed
verifier found missing evidence
reviewer rejected implementation
LLM returned invalid JSON
timeout/stall happened
selected model is weak for this packet
architect made packet too large
architect made scope/verification slightly wrong
```

Examples of true blockers:

```text
missing credentials / missing CLI / missing repo access
user decision required
TZ contradicts itself and cannot be safely inferred
requested change requires unsafe/destructive action
merge conflict cannot be resolved deterministically
scope is impossible without expanding allowed scope
security/payment/auth/data-loss risk requires explicit approval
```

Failure is not automatically a blocker. A blocker is a classified terminal condition.

---

## 1. High-level design

Add a recovery policy layer that sits above packet attempts and below feature orchestration.

Suggested module:

```text
src/grace_control/core/feature_recovery.py
```

It should not call LLMs directly in the first implementation. It should be deterministic and testable.

Input:

```text
feature_id
packet_id
packet state/result
attempt history
failure reason/category
acceptance profile
executor history
architect repair history
configured policy limits
```

Output:

```text
next action:
  retry same coder
  switch coder/model
  return to architect for repack
  escalate architect/reviewer critique
  retry verifier
  retry reviewer
  retry merge
  block feature
  mark done/no action
```

Normal worker/API should remain simple. Recovery policy should decide *what to schedule next*, not bypass gates.

---

## 2. Non-goals / safety rules

Do not bypass scope guard.
Do not bypass deterministic acceptance.
Do not bypass reviewer for STRICT packets.
Do not force-merge on dirty target repo.
Do not mutate packet state manually without audit.
Do not silently expand packet scope.
Do not silently rewrite user TZ.
Do not treat security/auth/billing/data-loss issues as retryable implementation failures.
Do not let recovery loops run forever.
Do not call expensive premium models before cheaper deterministic checks have failed.

The policy can retry/escalate work, but cannot lower safety.

---

## 3. Core data models

Create in:

```text
src/grace_control/core/feature_recovery.py
```

### 3.1 FailureClass

```python
class FailureClass(str, Enum):
    RETRYABLE_CODER = "retryable_coder"
    RETRYABLE_VERIFIER = "retryable_verifier"
    RETRYABLE_REVIEWER = "retryable_reviewer"
    ARCHITECT_REPACK_NEEDED = "architect_repack_needed"
    ARCHITECT_ESCALATION_NEEDED = "architect_escalation_needed"
    MERGE_RETRYABLE = "merge_retryable"
    TRUE_BLOCKER = "true_blocker"
    UNKNOWN_RETRYABLE = "unknown_retryable"
```

### 3.2 RecoveryAction

```python
class RecoveryAction(str, Enum):
    RETRY_SAME_CODER = "retry_same_coder"
    SWITCH_CODER = "switch_coder"
    RETURN_TO_ARCHITECT = "return_to_architect"
    ESCALATE_ARCHITECT = "escalate_architect"
    RETRY_VERIFIER = "retry_verifier"
    RETRY_REVIEWER = "retry_reviewer"
    RETRY_MERGE = "retry_merge"
    BLOCK_FEATURE = "block_feature"
    NO_ACTION = "no_action"
```

### 3.3 RecoveryDecision

```python
class RecoveryDecision(BaseModel):
    action: RecoveryAction
    failure_class: FailureClass
    reason: str
    next_executor_hint: str | None = None
    next_acceptance_profile: str | None = None
    architect_instruction: str | None = None
    reviewer_instruction: str | None = None
    max_attempts_reached: bool = False
    audit_payload: dict[str, Any] = Field(default_factory=dict)
```

### 3.4 FailureSignal

```python
class FailureSignal(BaseModel):
    feature_id: str
    packet_id: str
    packet_state: str
    domain_status: str | None = None
    reason: str | None = None
    acceptance_verdict: str | None = None
    evidence_verifier_verdict: str | None = None
    reviewer_verdict: str | None = None
    merge_error: str | None = None
    blocked_reason: str | None = None
    acceptance_profile: str | None = None
    attempt_count: int = 0
    coder_attempt_count: int = 0
    architect_repair_count: int = 0
    reviewer_reject_count: int = 0
    verifier_reject_count: int = 0
    merge_attempt_count: int = 0
    current_executor_id: str | None = None
    previous_executor_ids: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
```

### 3.5 RecoveryPolicy

```python
class RecoveryPolicy(BaseModel):
    max_same_coder_attempts: int = 2
    max_total_coder_attempts: int = 4
    max_architect_repairs: int = 2
    max_reviewer_retries: int = 2
    max_verifier_retries: int = 2
    max_merge_retries: int = 2
    allow_profile_escalation: bool = True
    allow_model_switch: bool = True
```

---

## 4. Failure classification rules

Add function:

```python
def classify_failure(signal: FailureSignal) -> FailureClass:
    ...
```

### 4.1 Deterministic acceptance failures

If acceptance failed because tests failed, command failed, pycompile failed, evidence missing, no changes produced, or T1/T2 failed:

```text
FailureClass.RETRYABLE_CODER
```

Unless reason contains impossible scope / forbidden scope / contradictory packet.

### 4.2 Scope violations

Scope violations are usually coder retryable if the packet scope is correct and coder wrote outside it:

```text
scope violation: wrote docs/extra.md outside allowed scope
→ RETRYABLE_CODER
```

But if verifier/reviewer says the requested implementation cannot be done within scope:

```text
RETURN_TO_ARCHITECT
scope impossible without editing API file
→ ARCHITECT_REPACK_NEEDED
```

### 4.3 Evidence Verifier decisions

```text
PASS → NO_ACTION
REWORK_TO_CODER → RETRYABLE_CODER
RETURN_TO_ARCHITECT → ARCHITECT_REPACK_NEEDED
invalid JSON / parser fail → RETRYABLE_VERIFIER, then switch verifier if repeated
```

### 4.4 Reviewer decisions

```text
PASS → NO_ACTION
REWORK_TO_CODER → RETRYABLE_CODER
RETURN_TO_ARCHITECT → ARCHITECT_REPACK_NEEDED
invalid JSON / parser fail → RETRYABLE_REVIEWER, then switch reviewer if repeated
```

### 4.5 Merge failures

```text
DIRTY_TARGET_REPO → TRUE_BLOCKER or MERGE_RETRYABLE depending source
merge conflict → TRUE_BLOCKER unless explicit auto-resolve strategy exists
branch missing → MERGE_RETRYABLE first, then TRUE_BLOCKER
worktree missing → MERGE_RETRYABLE in golden-debug only, TRUE_BLOCKER in normal mode
```

Default:

```text
merge endpoint 409 due dirty target repo → TRUE_BLOCKER
merge endpoint transient network/API error → MERGE_RETRYABLE
```

### 4.6 Infrastructure/auth/access failures

```text
missing CLI binary
missing API key
auth failed
quota exceeded
rate limit exceeded
repository inaccessible
permission denied
```

Classification:

```text
TRUE_BLOCKER
```

Exception:

```text
single transient timeout/stall → retry same/switch executor based on counts
```

### 4.7 Unknown failures

Unknown failures should be retryable once, then escalated.

```text
first unknown → UNKNOWN_RETRYABLE
repeated unknown → ARCHITECT_ESCALATION_NEEDED or TRUE_BLOCKER based on safety
```

---

## 5. Recovery decision rules

Add function:

```python
def decide_recovery(signal: FailureSignal, policy: RecoveryPolicy) -> RecoveryDecision:
    ...
```

### 5.1 Coder retry ladder

```text
coder failure #1:
  RETRY_SAME_CODER
  include failure summary and acceptance report in next prompt

coder failure #2:
  RETRY_SAME_CODER or SWITCH_CODER depending same executor failure count

coder failure #3:
  SWITCH_CODER to stronger/different provider

coder failure #4:
  RETURN_TO_ARCHITECT for repack/split
```

Default exact policy:

```text
coder_attempt_count < 2 → RETRY_SAME_CODER
coder_attempt_count >= 2 and total < 4 → SWITCH_CODER
coder_attempt_count >= 4 → RETURN_TO_ARCHITECT
```

### 5.2 Model switch ladder

Initial coder preference can remain existing selector/priority.

Recovery hints:

```text
coder-flash failed twice → coder-agy-flash or coder-agy-sonnet
coder-agy-flash failed → coder-agy-sonnet
coder-agy-sonnet failed → architect repack
```

Do not hardcode only these names in core logic. Use executor registry if available. But tests can use these fixture ids.

### 5.3 Architect repack ladder

If packet repeatedly fails or scope is impossible:

```text
RETURN_TO_ARCHITECT
```

Architect instruction should include:

```text
- original packet
- failure history
- acceptance reports
- changed files attempted
- exact reason
- ask for smaller packet or corrected scope/verification
```

If architect repair already happened twice:

```text
ESCALATE_ARCHITECT
```

Escalation means premium architect/reviewer critique, not user blocker yet.

### 5.4 Verifier retry ladder

If verifier fails due parser/invalid JSON/timeout:

```text
verifier_reject_count < 2 → RETRY_VERIFIER
else → switch verifier if available or ESCALATE_ARCHITECT
```

If verifier returns REWORK_TO_CODER:

```text
route to coder ladder
```

If verifier returns RETURN_TO_ARCHITECT:

```text
route to architect ladder
```

### 5.5 Reviewer retry ladder

If reviewer fails due parser/invalid JSON/timeout:

```text
reviewer_reject_count < 2 → RETRY_REVIEWER
else → ESCALATE_ARCHITECT
```

If reviewer returns REWORK_TO_CODER:

```text
route to coder ladder
```

If reviewer returns RETURN_TO_ARCHITECT:

```text
route to architect ladder
```

### 5.6 Merge retry ladder

```text
transient merge/API error and merge_attempt_count < 2 → RETRY_MERGE
DIRTY_TARGET_REPO → BLOCK_FEATURE
merge conflict → BLOCK_FEATURE
missing branch/worktree in normal mode → BLOCK_FEATURE
```

Do not auto-resolve conflicts in this task.

---

## 6. Integration points

Do not wire a complex new controller deeply into production flow in the first patch.

### Phase 1 implementation: deterministic library + tests only

Implement:

```text
src/grace_control/core/feature_recovery.py
tests/grace_control/core/test_feature_recovery.py
```

No live orchestration changes yet, except optional report/log helper.

This is the minimum safe implementation.

### Phase 2 later: API/worker integration

Later, worker/API can call recovery policy when packet reaches:

```text
rejected
blocked
accepted but merge failed
reviewer rejected
verifier rejected
```

But do not add autonomous scheduling in this first task unless explicitly requested.

---

## 7. Optional helper: build signal from result_json

Add helper:

```python
def build_failure_signal_from_packet_run(packet_run: Any, packet: Any | None = None) -> FailureSignal:
    ...
```

It should read:

```text
packet_run.status
packet_run.result_json.acceptance_report
packet_run.result_json.evidence_verifier_report
packet_run.result_json.reviewer_report
packet_run.result_json.agent_commit_sha
packet.attempt_count
packet.acceptance_profile
```

If this is too much for first implementation, skip it and only implement pure model/rules.

---

## 8. Audit events

When integrated later, every recovery decision must emit an audit event:

```text
recovery_decision_made
recovery_retry_same_coder
recovery_switch_coder
recovery_return_to_architect
recovery_escalate_architect
recovery_block_feature
recovery_retry_merge
```

Payload:

```json
{
  "feature_id": "...",
  "packet_id": "...",
  "failure_class": "retryable_coder",
  "action": "switch_coder",
  "reason": "coder failed deterministic acceptance twice",
  "current_executor_id": "coder-flash",
  "next_executor_hint": "coder-agy-sonnet",
  "attempt_count": 3
}
```

No audit integration required in Phase 1 unless easy.

---

## 9. Report shape for future integration

When integrated, feature report should include:

```json
"recovery": {
  "enabled": true,
  "decisions": [
    {
      "packet_id": "...",
      "failure_class": "retryable_coder",
      "action": "switch_coder",
      "reason": "..."
    }
  ]
}
```

Do not implement report integration in Phase 1 unless very small.

---

## 10. Tests required

Create:

```text
tests/grace_control/core/test_feature_recovery.py
```

Add tests for classification:

```text
test_acceptance_test_failure_is_retryable_coder
test_no_changes_produced_is_retryable_coder
test_scope_violation_by_coder_is_retryable_coder
test_scope_impossible_is_architect_repack_needed
test_verifier_rework_to_coder_is_retryable_coder
test_verifier_return_to_architect_is_architect_repack_needed
test_reviewer_rework_to_coder_is_retryable_coder
test_reviewer_return_to_architect_is_architect_repack_needed
test_dirty_target_repo_is_true_blocker
test_merge_conflict_is_true_blocker
test_transient_merge_error_is_merge_retryable
test_missing_cli_is_true_blocker
test_unknown_first_failure_is_unknown_retryable
```

Add tests for decisions:

```text
test_first_coder_failure_retries_same_coder
test_second_coder_failure_switches_coder
test_fourth_coder_failure_returns_to_architect
test_repeated_architect_repair_escalates_architect
test_verifier_parser_fail_retries_verifier
test_reviewer_parser_fail_retries_reviewer
test_repeated_reviewer_parser_fail_escalates_architect
test_merge_retryable_retries_until_limit
test_merge_retry_limit_blocks_feature
test_true_blocker_blocks_feature
test_strict_profile_does_not_downgrade_to_normal_or_fast
```

Add tests for safety invariants:

```text
test_recovery_never_returns_action_to_skip_acceptance
test_recovery_never_returns_action_to_skip_scope_guard
test_recovery_never_lowers_acceptance_profile
test_recovery_can_escalate_acceptance_profile_to_strict
test_recovery_decision_contains_reason
```

---

## 11. Acceptance criteria for Phase 1

Done only if:

1. `feature_recovery.py` exists with FailureClass, RecoveryAction, FailureSignal, RecoveryPolicy, RecoveryDecision.
2. `classify_failure(...)` is deterministic and unit-tested.
3. `decide_recovery(...)` is deterministic and unit-tested.
4. Coder retry ladder works.
5. Verifier/reviewer retry and architect-return routing work.
6. Merge retry/blocker classification works.
7. True blockers always produce `BLOCK_FEATURE`.
8. Policy never emits unsafe bypass actions.
9. Tests do not call real LLMs, git, opencode, agy, or API server.
10. Existing tests still pass.

---

## 12. Do not do in this task

Do not wire automatic recovery into worker live loop yet.
Do not mutate DB state automatically.
Do not create new packet attempts automatically.
Do not call architect/reviewer/coder from recovery module.
Do not bypass acceptance/reviewer/scope/merge gates.
Do not implement conflict auto-resolution.
Do not add manual override commands.
Do not run real agents in tests.
Do not change golden behavior.

---

## 13. Suggested implementation order

1. Create `feature_recovery.py` with enums/models only.
2. Add `classify_failure(...)` with simple rule checks.
3. Add `decide_recovery(...)` using policy counters.
4. Add tests for classification.
5. Add tests for decisions.
6. Add safety invariant tests.
7. Run full test suite.

---

## 14. Future Phase 2 outline, not for this task

Later TZ should integrate this with orchestration:

```text
packet rejected → build FailureSignal → decide_recovery → schedule action
blocked → decide if architect repack or true blocker
merge failed → retry merge or block
architect repair → create revised packets
model switch → pass requested_executor to next attempt
```

Potential future files:

```text
src/grace_control/core/feature_recovery.py
src/grace_control/api/routers/recovery.py
src/grace_control/worker/recovery_controller.py
```

But Phase 1 is only core policy and tests.

---

## 15. Final coder report format

Coder must report:

```text
Files changed
Phase implemented: 1 only / more
Failure classes implemented: yes/no
Recovery decision policy implemented: yes/no
Safety invariant tests added: yes/no
Tests added
Tests run
Any remaining blockers
```
