# TZ 017 — Feature Recovery / Escalation Policy

Audience: Flash coder / literal executor.

Status: **single source of truth for recovery**.

Goal: keep feature delivery moving when failures are retryable, while preserving all safety gates: scope guard, deterministic acceptance, STRICT reviewer, dirty merge checks, and merge conflict safety.

Important: Phase 1 recovery core already exists. Do **not** replace it with a new rules engine. This TZ updates and tightens the existing implementation contract.

---

## 0. Current implementation baseline

Current code already has:

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

Current tests are expected under:

```text
tests/grace_control/core/test_feature_recovery.py
```

Recovery fixture YAMLs are expected under:

```text
fixtures/golden/recovery_*.yaml
```

Do not create a competing `RecoveryRouteDecision`, YAML rules engine, or second policy layer in this phase.

---

## 1. Phase map

Use these phases:

```text
Phase 1 — deterministic policy core            current baseline + rework fixes in this TZ
Phase 2 — recovery fixture YAMLs               current baseline, must remain compatible
Phase 3 — live RecoveryController wiring       future
Phase 4 — session resume context stubs         future, scaffold only
Phase 5 — admin/event observability            future UI/API layer
Phase 6 — optional routing wrapper             future, only thin wrapper over RecoveryDecision
```

This task is mostly **Phase 1 rework + TZ/code sync**.

---

## 2. Canonical runtime formats

Recovery verdicts must be machine-readable.

```text
RecoveryPolicy / recovery fixture specs → YAML
RecoveryDecision inside code             → Pydantic model
RecoveryDecision at API/DB/events        → JSON-compatible dict
Human explanation                        → reason/audit_payload fields, not free text only
```

`RecoveryDecision` is the canonical recovery/routing verdict for now.

Do not return recovery decisions as free-form text.
Do not use YAML as runtime verdict format.
Do not introduce a second `RouteDecision` unless it wraps or extends `RecoveryDecision` in a later phase.

Example runtime JSON:

```json
{
  "action": "switch_coder",
  "failure_class": "retryable_coder",
  "reason": "coder failed 2x, switching model",
  "current_executor_id": "coder-flash",
  "next_executor_hint": "coder-agy-sonnet",
  "next_acceptance_profile": null,
  "max_attempts_reached": false,
  "audit_payload": {
    "policy": "default",
    "coder_attempt_count": 2,
    "matched_branch": "coder_ladder.switch_coder"
  }
}
```

---

## 3. Non-goals and safety rules

Do not bypass scope guard.
Do not bypass deterministic acceptance.
Do not bypass reviewer for STRICT packets.
Do not force-merge on dirty target repo.
Do not auto-resolve merge conflicts.
Do not lower STRICT to NORMAL/FAST.
Do not silently expand packet scope.
Do not let recovery loops run forever.
Do not add a new broad YAML routing engine now.

---

## 4. Core API remains authoritative

Keep these functions as the core API:

```python
def classify_failure(signal: FailureSignal) -> FailureClass: ...
def decide_recovery(signal: FailureSignal, policy: RecoveryPolicy | None = None) -> RecoveryDecision: ...
```

If `decide_recovery` currently requires a non-optional policy argument, either keep that behavior or add a safe default internally:

```python
def decide_recovery(signal: FailureSignal, policy: RecoveryPolicy | None = None) -> RecoveryDecision:
    policy = policy or RecoveryPolicy()
    ...
```

Do not change callers silently without tests.

---

## 5. RecoveryPolicy must match code and safety requirements

`RecoveryPolicy` must include all current fields plus the missing STRICT safety flag.

Required model:

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
    never_downgrade_strict: bool = True
```

`allow_profile_escalation` and `allow_model_switch` are already implemented fields and must remain documented.

`never_downgrade_strict` is currently missing and must be added.

Implementation example:

```python
def _safe_next_profile(current: str | None, proposed: str | None, policy: RecoveryPolicy) -> str | None:
    if proposed is None:
        return None
    if policy.never_downgrade_strict and current == "STRICT" and proposed != "STRICT":
        return "STRICT"
    return proposed
```

If current logic never sets `next_acceptance_profile`, still add the field and invariant tests so future code cannot downgrade STRICT by accident.

---

## 6. Failure classification rules

### 6.1 Deterministic acceptance failures

Explicitly classify these as coder retryable:

```text
T1 failed
T2 failed
test failed
command failed
pycompile failed
syntax failed
evidence missing
no changes
no_changes
no_changes_produced
no changes produced
```

Implementation example:

```python
NO_CHANGES_PATTERNS = ("no changes", "no_changes", "no_changes_produced", "no changes produced")

if any(p in reason for p in NO_CHANGES_PATTERNS):
    return FailureClass.RETRYABLE_CODER
```

### 6.2 Scope failures

```text
coder wrote outside allowed scope        → RETRYABLE_CODER
packet impossible within allowed scope   → ARCHITECT_REPACK_NEEDED
frozen/safety scope violation            → depends on reason; default safe route is architect/blocker
```

Implementation example:

```python
if "scope" in reason:
    if "impossible" in reason or "cannot be done" in reason or "cannot" in reason:
        return FailureClass.ARCHITECT_REPACK_NEEDED
    return FailureClass.RETRYABLE_CODER
```

### 6.3 Evidence Verifier verdicts

Required mapping:

```text
PASS                 → UNKNOWN_RETRYABLE or NO_ACTION depending call context
REWORK_TO_CODER      → RETRYABLE_CODER
RETURN_TO_ARCHITECT  → ARCHITECT_REPACK_NEEDED
INVALID / PARSE_ERROR / TIMEOUT / invalid JSON / unknown non-empty verdict
                     → RETRYABLE_VERIFIER
```

Implementation example:

```python
if ev_verdict:
    if ev_verdict == "RETURN_TO_ARCHITECT":
        return FailureClass.ARCHITECT_REPACK_NEEDED
    if ev_verdict == "REWORK_TO_CODER":
        return FailureClass.RETRYABLE_CODER
    if ev_verdict == "PASS":
        return FailureClass.UNKNOWN_RETRYABLE
    return FailureClass.RETRYABLE_VERIFIER
```

### 6.4 Reviewer verdicts

Required mapping:

```text
PASS                 → UNKNOWN_RETRYABLE or NO_ACTION depending call context
REWORK_TO_CODER      → RETRYABLE_CODER
RETURN_TO_ARCHITECT  → ARCHITECT_REPACK_NEEDED
INVALID / PARSE_ERROR / TIMEOUT / invalid JSON / unknown non-empty verdict
                     → RETRYABLE_REVIEWER
```

Implementation example:

```python
if rv_verdict:
    if rv_verdict == "RETURN_TO_ARCHITECT":
        return FailureClass.ARCHITECT_REPACK_NEEDED
    if rv_verdict == "REWORK_TO_CODER":
        return FailureClass.RETRYABLE_CODER
    if rv_verdict == "PASS":
        return FailureClass.UNKNOWN_RETRYABLE
    return FailureClass.RETRYABLE_REVIEWER
```

### 6.5 Merge failures

Required mapping:

```text
DIRTY_TARGET_REPO       → TRUE_BLOCKER
merge conflict          → TRUE_BLOCKER
missing worktree/branch → MERGE_RETRYABLE first, then controller/policy may block after retries
timeout/transient       → MERGE_RETRYABLE
unknown merge error     → TRUE_BLOCKER by default
```

### 6.6 True blockers

Required true blocker examples:

```text
missing CLI
missing API key
auth failed
permission denied
repository inaccessible
quota exceeded if no automatic fallback exists
user decision required
security/auth/billing/data-loss approval required
dirty target repo
merge conflict
```

---

## 7. Decision policy

Required actions:

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
RETRYABLE_CODER:
  coder_attempt_count < max_same_coder_attempts
    → RETRY_SAME_CODER

  coder_attempt_count >= max_same_coder_attempts
  and coder_attempt_count < max_total_coder_attempts
  and allow_model_switch=true
    → SWITCH_CODER

  coder_attempt_count >= max_total_coder_attempts
    → RETURN_TO_ARCHITECT

ARCHITECT_REPACK_NEEDED:
  architect_repair_count < max_architect_repairs
    → RETURN_TO_ARCHITECT

  architect_repair_count >= max_architect_repairs
    → ESCALATE_ARCHITECT

RETRYABLE_VERIFIER:
  verifier_reject_count < max_verifier_retries
    → RETRY_VERIFIER
  else
    → ESCALATE_ARCHITECT

RETRYABLE_REVIEWER:
  reviewer_reject_count < max_reviewer_retries
    → RETRY_REVIEWER
  else
    → ESCALATE_ARCHITECT

MERGE_RETRYABLE:
  merge_attempt_count < max_merge_retries
    → RETRY_MERGE
  else
    → BLOCK_FEATURE

TRUE_BLOCKER:
  → BLOCK_FEATURE
```

Implementation example for model switch:

```python
if fc == FailureClass.RETRYABLE_CODER:
    if signal.coder_attempt_count >= policy.max_total_coder_attempts:
        return RecoveryDecision(... RETURN_TO_ARCHITECT ...)
    if signal.coder_attempt_count >= policy.max_same_coder_attempts:
        if policy.allow_model_switch:
            return RecoveryDecision(... SWITCH_CODER, next_executor_hint=_next_executor_hint(signal) ...)
        return RecoveryDecision(... RETRY_SAME_CODER, next_executor_hint=signal.current_executor_id ...)
    return RecoveryDecision(... RETRY_SAME_CODER ...)
```

---

## 8. RecoveryDecision contract

Current `RecoveryDecision` must remain the canonical runtime verdict.

Required model:

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

Must be JSON serializable:

```python
decision_json = decision.model_dump(mode="json")
```

Use this JSON shape in:

```text
PacketRun.result_json["recovery_decision"]
recovery events payload
future /api/recovery responses
fixture expected.recovery comparisons
```

Do not store only human text.

---

## 9. Fixture helper contract

`build_failure_signal_from_fixture(...)` is part of Phase 2 contract and must be documented and tested.

Required behavior:

```text
input: parsed recovery fixture YAML/dict
output: FailureSignal
must map fixture.failure_signal fields
must preserve current_executor_id / previous_executor_ids
must preserve counters
must not require generated UIDs in YAML
must not call real agents or Git
```

Implementation example:

```python
def build_failure_signal_from_fixture(fixture: dict[str, Any]) -> FailureSignal:
    fs = fixture.get("failure_signal", {})
    packet = fixture.get("packet", {})
    return FailureSignal(
        feature_id="",
        packet_id="",
        packet_state=packet.get("state", ""),
        reason=fs.get("reason"),
        acceptance_verdict=fs.get("acceptance_verdict"),
        evidence_verifier_verdict=fs.get("evidence_verifier_verdict"),
        reviewer_verdict=fs.get("reviewer_verdict"),
        merge_error=fs.get("merge_error"),
        acceptance_profile=packet.get("acceptance_profile"),
        attempt_count=fs.get("attempt_count", 0),
        coder_attempt_count=fs.get("coder_attempt_count", 0),
        current_executor_id=fs.get("current_executor_id"),
        previous_executor_ids=fs.get("previous_executor_ids", []),
    )
```

If the current helper name/signature differs, keep current signature but document it in tests.

---

## 10. Recovery fixture YAML requirements

Fixtures live under:

```text
fixtures/golden/
```

Required scenario families:

```text
coder fail once → RETRY_SAME_CODER
coder fail twice → SWITCH_CODER
coder fail four times → RETURN_TO_ARCHITECT
merge dirty target → BLOCK_FEATURE
transient merge → RETRY_MERGE then BLOCK_FEATURE after limit
blocked packet retry denied
verifier RETURN_TO_ARCHITECT
verifier invalid JSON → RETRY_VERIFIER
reviewer REWORK_TO_CODER
reviewer invalid JSON → RETRY_REVIEWER
STRICT profile never downgraded
no_changes_produced → RETRYABLE_CODER
```

Fixture YAML must use readable IDs only for humans:

```yaml
id: recovery_coder_fail_twice_switch_model
kind: golden_fixture
start_stage: recovery
profile: NORMAL
packet:
  title: Fix small API bug
  slug: fix-small-api-bug
  state: rejected
  acceptance_profile: NORMAL
failure_signal:
  reason: T1 failed twice
  acceptance_verdict: rework_required
  coder_attempt_count: 2
  attempt_count: 2
  current_executor_id: coder-flash
  previous_executor_ids:
    - coder-flash
    - coder-flash
expected:
  recovery:
    failure_class: retryable_coder
    action: switch_coder
    next_executor_hint_any_of:
      - coder-agy-sonnet
      - coder-agy-flash
    must_not_lower_acceptance_profile: true
```

Do not hardcode generated `feat_...`, `wave_...`, `pkt_...` IDs in fixtures.

---

## 11. Required tests and rework from review

Tests must live at:

```text
tests/grace_control/core/test_feature_recovery.py
```

Add or fix these tests:

```text
test_policy_has_never_downgrade_strict_default_true
test_strict_profile_never_downgraded_even_if_future_decision_sets_profile
test_verifier_invalid_json_is_retryable_verifier
test_verifier_unknown_non_pass_verdict_is_retryable_verifier
test_reviewer_invalid_json_is_retryable_reviewer
test_reviewer_unknown_non_pass_verdict_is_retryable_reviewer
test_no_changes_produced_is_retryable_coder
test_no_changes_snake_case_is_retryable_coder
test_build_failure_signal_from_fixture_maps_required_fields
```

Fix existing weak tests:

```text
verifier invalid JSON must expect RETRY_VERIFIER, not RETRY_SAME_CODER
reviewer invalid JSON must expect RETRY_REVIEWER, not RETRY_SAME_CODER
remove placeholder/pass tests
```

Example expected verifier test:

```python
def test_verifier_invalid_json_retries_verifier():
    signal = FailureSignal(
        packet_state="rejected",
        evidence_verifier_verdict="INVALID_JSON",
        verifier_reject_count=0,
    )
    assert classify_failure(signal) == FailureClass.RETRYABLE_VERIFIER
    decision = decide_recovery(signal, RecoveryPolicy())
    assert decision.action == RecoveryAction.RETRY_VERIFIER
```

Example expected reviewer test:

```python
def test_reviewer_invalid_json_retries_reviewer():
    signal = FailureSignal(
        packet_state="rejected",
        reviewer_verdict="PARSE_ERROR",
        reviewer_reject_count=0,
    )
    assert classify_failure(signal) == FailureClass.RETRYABLE_REVIEWER
    decision = decide_recovery(signal, RecoveryPolicy())
    assert decision.action == RecoveryAction.RETRY_REVIEWER
```

---

## 12. Phase 3 — future RecoveryController

Not part of this rework unless explicitly requested.

Future controller flow:

```text
packet rejected/blocked/failed or merge failed
→ build FailureSignal from packet/run/result_json/events
→ classify_failure(...)
→ decide_recovery(...)
→ persist RecoveryDecision JSON
→ emit recovery events
→ apply safe action if feature flag enabled
```

Feature flag:

```text
GRACE_RECOVERY_CONTROLLER_ENABLED=true|false
```

Future API:

```text
POST /api/recovery/evaluate/{packet_id}
GET /api/recovery/packets/{packet_id}
GET /api/recovery/features/{feature_id}
```

Do not wire live controller until Phase 1/2 tests and staged fixtures are green.

---

## 13. Phase 4 — future session resume stubs

Not part of this rework unless explicitly requested.

Goal: when a packet is retried/switched/returned, future system can pass a structured summary of previous attempt.

Models to add later:

```text
RecoverySessionSnapshot
TaskResumeContext
SessionResumeSummary
```

No live prompt injection yet.
No LLM calls.
No `build_resume_context=true` runtime behavior yet.

---

## 14. Phase 5 — future admin/event integration

Admin UI should later show:

```text
latest RecoveryDecision JSON
failure_class/action/reason
old executor → new executor
blocker reason
return_to_architect / escalation reason
session resume availability when Phase 4 exists
```

Details remain in:

```text
docs/codex/tz-019c-admin-event-stream-and-recovery-observability.md
```

---

## 15. Future optional routing wrapper

A future routing wrapper is allowed only if it extends current core.

Allowed:

```text
RecoveryDecision + optional audit_payload.matched_rule_id
RecoveryDecision + optional audit_payload.session_context_mode
config hydration into RecoveryPolicy
```

Not allowed now:

```text
separate YAML rules engine replacing classify_failure/decide_recovery
new duplicate RouteContext counters
new stop guards outside RecoveryPolicy
new runtime RouteDecision that conflicts with RecoveryDecision
```

---

## 16. Acceptance criteria for this rework

Done only if:

```text
1. TZ-017 is the only recovery spec source of truth.
2. RecoveryPolicy in docs matches code and includes never_downgrade_strict.
3. allow_profile_escalation and allow_model_switch are documented.
4. RecoveryDecision is explicitly Pydantic internally and JSON externally.
5. Verifier invalid/unknown verdicts classify as RETRYABLE_VERIFIER.
6. Reviewer invalid/unknown verdicts classify as RETRYABLE_REVIEWER.
7. no_changes_produced/no_changes are explicit RETRYABLE_CODER patterns.
8. tests/grace_control/core/test_feature_recovery.py contains the required rework tests.
9. Placeholder/pass tests are removed or made meaningful.
10. build_failure_signal_from_fixture is documented and tested.
11. No new broad routing engine is introduced.
```

---

## 17. Final coder report format

Coder must report:

```text
Files changed
RecoveryPolicy.never_downgrade_strict added: yes/no
allow_profile_escalation/model_switch preserved: yes/no
Verifier invalid verdict classification fixed: yes/no
Reviewer invalid verdict classification fixed: yes/no
no_changes_produced explicit classification added: yes/no
RecoveryDecision JSON/Pydantic contract preserved: yes/no
build_failure_signal_from_fixture tests added: yes/no
Placeholder tests removed/fixed: yes/no
Tests run
Remaining blockers
```
