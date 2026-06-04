# TZ 017 — Feature Recovery / Escalation Policy

Audience: Flash coder / literal executor.

Status: **single source of truth for recovery**.

Goal: make feature delivery resilient: retry or reroute retryable failures, switch weak executors when needed, return impossible packets to architect, and stop only on true blockers. This must preserve all safety gates: scope guard, deterministic acceptance, STRICT reviewer, dirty merge checks, and merge conflict safety.

Important: this spec must follow the current implementation. Do not replace working recovery policy code with a new broad rules engine.

---

## 0. Current implementation baseline

Assume Phase 1 is already implemented or being reviewed:

```text
src/grace_control/core/feature_recovery.py
FailureClass
RecoveryAction
FailureSignal
RecoveryDecision
RecoveryPolicy
classify_failure(...)
decide_recovery(...)
_next_executor_hint(...)
build_failure_signal_from_fixture(...)
```

Reported baseline:

```text
25 recovery policy tests pass
14 recovery fixture YAMLs exist/work
```

Therefore future work must extend this implementation, not recreate conflicting abstractions.

---

## 1. Phase map

Use these phases:

```text
Phase 1 — deterministic policy core            DONE / current baseline
Phase 2 — recovery fixture YAMLs               DONE or required baseline
Phase 3 — live RecoveryController wiring       next implementation phase
Phase 4 — session resume context stubs         scaffold only, no live LLM wiring
Phase 5 — admin/event observability            reads recovery data/events
Phase 6 — optional routing policy wrapper      future, thin wrapper only
```

Do not implement Phase 6 before Phase 3/4 are stable.

---

## 2. Non-goals and safety rules

Do not bypass scope guard.
Do not bypass deterministic acceptance.
Do not bypass reviewer for STRICT packets.
Do not force-merge on dirty target repo.
Do not auto-resolve merge conflicts.
Do not lower STRICT to NORMAL/FAST.
Do not let recovery loops run forever.
Do not add a second competing recovery/routing engine.
Do not replace `classify_failure` / `decide_recovery` with YAML logic.

---

## 3. Existing policy core remains authoritative

The following functions remain the core API:

```python
def classify_failure(signal: FailureSignal) -> FailureClass: ...
def decide_recovery(signal: FailureSignal, policy: RecoveryPolicy | None = None) -> RecoveryDecision: ...
```

Any future routing/config layer must call these or wrap them. It must not fork separate semantics.

Valid extension pattern:

```text
FailureSignal
→ classify_failure(...)
→ decide_recovery(...)
→ optional route metadata decoration
→ RecoveryDecision / RouteDecision for controller/UI
```

Invalid extension pattern:

```text
FailureSignal
→ unrelated YAML rules engine
→ different action semantics
```

---

## 4. RecoveryPolicy is the only threshold source

Retry/escalation limits must live in `RecoveryPolicy`.

Default fields:

```text
max_same_coder_attempts = 2
max_total_coder_attempts = 4
max_architect_repairs = 2
max_verifier_retries = 2
max_reviewer_retries = 2
max_merge_retries = 2
allow_profile_escalation = true
allow_model_switch = true
never_downgrade_strict = true
```

Do not introduce duplicate stop guards such as separate `max_same_failure_class_repeats` or `max_total_recovery_steps` unless they are explicitly added to `RecoveryPolicy` and tested there.

If a future config file exists, it must hydrate `RecoveryPolicy`, not bypass it.

Optional future config shape:

```yaml
recovery:
  enabled: false
  policy:
    max_same_coder_attempts: 2
    max_total_coder_attempts: 4
    max_architect_repairs: 2
    max_verifier_retries: 2
    max_reviewer_retries: 2
    max_merge_retries: 2
    never_downgrade_strict: true
```

---

## 5. Classification semantics

Keep existing semantics from Phase 1.

Required examples:

```text
T1/T2 failed                         → RETRYABLE_CODER
no_changes_produced                  → RETRYABLE_CODER
coder wrote outside allowed scope     → RETRYABLE_CODER
packet impossible within scope        → ARCHITECT_REPACK_NEEDED
verifier REWORK_TO_CODER              → RETRYABLE_CODER
verifier RETURN_TO_ARCHITECT          → ARCHITECT_REPACK_NEEDED
reviewer REWORK_TO_CODER              → RETRYABLE_CODER
reviewer RETURN_TO_ARCHITECT          → ARCHITECT_REPACK_NEEDED
verifier/reviewer invalid JSON        → RETRYABLE_VERIFIER / RETRYABLE_REVIEWER
dirty target repo                     → TRUE_BLOCKER
merge conflict                        → TRUE_BLOCKER
transient merge/API error             → MERGE_RETRYABLE
missing CLI/API key/auth              → TRUE_BLOCKER
unknown first failure                 → UNKNOWN_RETRYABLE
repeated unknown failure              → ESCALATE_OR_BLOCK via policy
```

---

## 6. Decision semantics

Keep existing `RecoveryAction` semantics:

```text
RETRY_SAME_CODER
SWITCH_CODER
RETURN_TO_ARCHITECT
ESCALATE_ARCHITECT
RETRY_VERIFIER
RETRY_REVIEWER
RETRY_MERGE
BLOCK_FEATURE
NO_ACTION
```

Default ladder:

```text
coder_attempt_count < max_same_coder_attempts
  → RETRY_SAME_CODER

coder_attempt_count >= max_same_coder_attempts and attempt_count < max_total_coder_attempts
  → SWITCH_CODER

attempt_count >= max_total_coder_attempts
  → RETURN_TO_ARCHITECT

architect_repair_count >= max_architect_repairs
  → ESCALATE_ARCHITECT

merge_attempt_count < max_merge_retries and failure is merge_retryable
  → RETRY_MERGE

true blocker
  → BLOCK_FEATURE
```

Tests must verify custom `RecoveryPolicy` values change decisions.

---

## 7. Phase 2 — recovery fixture YAMLs

Recovery fixture YAMLs are required and must remain compatible with the implemented `build_failure_signal_from_fixture(...)` helper.

Required fixture rules:

```text
live under fixtures/golden/
use start_stage: recovery
use readable title/slug only
must not hardcode generated feat_/wave_/pkt_ IDs
must include failure_signal
must include runs/history when needed
must include expected.recovery
must not run real LLMs or agents
```

Minimum scenario families:

```text
coder fail once → retry same coder
coder fail twice → switch coder
coder fail four times → return to architect
merge dirty target → true blocker / block feature
transient merge → retry merge under limit
blocked packet retry denied
verifier return_to_architect
reviewer rework_to_coder
STRICT profile never downgraded
```

If fixture count changes, update this section rather than creating another TZ file.

---

## 8. Phase 3 — live RecoveryController

Next implementation phase.

Add:

```text
src/grace_control/core/recovery_controller.py
src/grace_control/api/routers/recovery.py
src/grace_control/worker/recovery_client.py  # optional
```

High-level flow:

```text
packet rejected / blocked / failed / merge failed
→ build FailureSignal from packet/run/result_json/events
→ classify_failure(...)
→ decide_recovery(...)
→ persist RecoveryDecision
→ emit recovery events
→ apply safe action
```

Feature flag:

```text
GRACE_RECOVERY_CONTROLLER_ENABLED=true|false
```

Rollout:

```text
A. disabled by default
B. enabled for staged recovery fixtures
C. enabled for STRICT self-improvement
D. enabled for normal feature execution
```

Controller must not call an unrelated routing engine.

---

## 9. Recovery persistence

Preferred table:

```text
recovery_decisions
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

Temporary fallback is allowed only for a small patch:

```text
PacketRun.result_json["recovery"] + DB events
```

But admin/API must be able to return recovery history reliably.

---

## 10. Phase 3 live actions

### RETRY_SAME_CODER

```text
packet → READY
next attempt uses same executor when possible
```

### SWITCH_CODER

```text
packet → READY
set requested executor for next attempt
```

Canonical field:

```text
Packet.spec_json["recovery"]["requested_executor_id"]
```

Worker/executor selection must honor it. Do not silently reuse the same failing executor after `SWITCH_CODER`.

### RETURN_TO_ARCHITECT

```text
stop normal coder retry loop
store architect repair request payload
packet → BLOCKED or architect_repack_needed equivalent
```

Do not run architect LLM automatically in first controller patch.

### ESCALATE_ARCHITECT

```text
packet/feature marked escalated or blocked
```

### RETRY_VERIFIER / RETRY_REVIEWER

```text
rerun verifier/reviewer only if independent stage runner exists
otherwise store retry-requested metadata for later/admin
```

### RETRY_MERGE

```text
only for MERGE_RETRYABLE and below max_merge_retries
```

### BLOCK_FEATURE

```text
packet → BLOCKED
feature recovery summary blocked=true
```

---

## 11. Recovery API

Add:

```text
POST /api/recovery/evaluate/{packet_id}
GET /api/recovery/packets/{packet_id}
GET /api/recovery/features/{feature_id}
```

POST behavior:

```text
load packet/history
build FailureSignal
classify/decide
persist decision
apply only if apply=true and feature flag allows
emit event
return decision
```

Response includes:

```text
packet_id
decision_id
failure_class
action
reason
next_executor_hint
status
```

---

## 12. Recovery events

Emit structured events for admin UI:

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

## 13. Phase 4 — session resume stubs only

Do not implement live session memory yet.

Add only contracts/stubs so future retries can pass session context cleanly.

Required models:

```text
RecoverySessionSnapshot
TaskResumeContext
SessionResumeSummary
```

Required fields:

```text
session_id, feature_id, wave_id, packet_id, run_id, attempt_number
role, executor_id, model, started_at, finished_at, status
summary_human, failure_reason, changed_files, artifacts
acceptance_report_path, evidence_report_path, reviewer_report_path
recovery_decision_id, previous_attempts_summary, full_context_json
```

Stub functions:

```python
def build_session_snapshot(packet_run, packet=None) -> RecoverySessionSnapshot: ...
def build_task_resume_context(packet, decision, history) -> TaskResumeContext: ...
def render_resume_summary(context: TaskResumeContext) -> str: ...
```

No LLM calls. No automatic prompt injection. No `build_resume_context: true` live behavior yet.

Future controller may ask for resume context, but Phase 4 only prepares the structure.

---

## 14. Phase 5 — admin/event integration

Admin UI must eventually show:

```text
latest RecoveryDecision
failure_class/action/reason
old executor → new executor for switch coder
blocker reason
return_to_architect / escalation reason
session resume availability after Phase 4
```

Detailed UI requirements remain in:

```text
docs/codex/tz-019c-admin-event-stream-and-recovery-observability.md
```

---

## 15. Future optional routing policy wrapper

A universal routing layer may be useful later, but it must be a thin wrapper around the current implementation.

Allowed future design:

```text
RecoveryPolicy config
+ classify_failure(...)
+ decide_recovery(...)
+ optional metadata: matched_rule_id, display_reason, session_context_mode
```

Not allowed now:

```text
new YAML rules engine replacing classify_failure/decide_recovery
new RouteContext with duplicate counters
new stop guards not backed by RecoveryPolicy
admin/routing/session abstractions before controller works
```

If future routing is added, it must:

```text
reuse FailureSignal
reuse RecoveryPolicy
reuse RecoveryDecision or extend it compatibly
prove custom config changes decisions
not add another source of truth
```

Session context mode is future metadata only until Phase 4 stubs and Phase 3 controller are stable.

---

## 16. Required tests

Keep existing tests and add only phase-appropriate tests.

Phase 1/2 tests:

```text
classification tests
decision tests
custom RecoveryPolicy tests
fixture YAML parsing tests
build_failure_signal_from_fixture tests
STRICT never downgraded tests
```

Phase 3 tests:

```text
RecoveryController builds signal from latest run
persists decision
emits recovery events
RETRY_SAME_CODER sets READY
SWITCH_CODER sets requested executor
RETURN_TO_ARCHITECT exits coder loop
RETRY_MERGE respects max_merge_retries
TRUE_BLOCKER blocks packet/feature
worker calls controller behind flag
```

Phase 4 tests:

```text
session snapshot contains run identity
snapshot contains executor/model/status
resume context contains previous attempts summary
resume context contains recovery decision
resume summary is human-readable
artifact paths are preserved
no LLM calls
```

No recovery tests may run real LLMs/agents.

---

## 17. Acceptance criteria by phase

Phase 1 done:

```text
feature_recovery.py exists
classify_failure/decide_recovery tested
RecoveryPolicy configurable
custom policy tests pass
```

Phase 2 done:

```text
recovery fixture YAMLs exist and parse
fixtures create/represent UID-based Feature/Wave/Packet/PacketRun state
fixtures validate expected.recovery
```

Phase 3 done:

```text
RecoveryController exists
RecoveryDecision persisted
API exists
worker integration behind flag exists
SWITCH_CODER requested executor wired
recovery events emitted
```

Phase 4 done:

```text
session resume models/stubs exist
tests pass
no live wiring
```

Phase 5 done:

```text
admin/API shows recovery summary/events
session resume availability visible when implemented
```

---

## 18. Do not do

```text
Do not create separate 017b/017c/017d recovery specs.
Do not replace implemented policy core.
Do not implement a complex YAML rules engine now.
Do not add live session resume before controller is stable.
Do not introduce duplicate stop counters outside RecoveryPolicy.
Do not enable live recovery globally before staged fixtures pass.
```

---

## 19. Final coder report format

```text
Phase implemented: 1/2/3/4/5
Files changed
Existing feature_recovery.py preserved: yes/no
RecoveryPolicy custom tests added: yes/no
Recovery fixture YAMLs updated: yes/no
RecoveryController added: yes/no
Recovery API added: yes/no
Worker integration behind flag: yes/no
SWITCH_CODER requested executor wired: yes/no
Recovery events emitted: yes/no
Session resume stubs added: yes/no
Tests run
Remaining blockers
```
