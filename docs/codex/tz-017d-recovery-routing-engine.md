# TZ 017d — Universal Recovery Routing Engine

Audience: Flash coder / literal executor.

Parent spec:

```text
docs/codex/tz-017-feature-recovery-escalation-policy.md
```

Goal: make recovery decisions configurable and universal. The system must not hardcode who returns a packet, how many times to retry, when to switch coder/model, when to return to architect, when to stop, or whether to attach session context. This should be expressed as a routing policy.

---

## 1. Product idea

Recovery is routing.

Instead of hardcoding:

```text
if coder failed twice → switch coder
if failed four times → architect
```

implement a rules engine:

```text
failure signal + packet context + counters + role + profile + policy rules
→ route decision
```

The route decision says:

```text
who receives the task next
why
how many times allowed
which executor/model to use
whether to include session resume context
whether to stop/block/escalate
```

---

## 2. Required concepts

Add or model these concepts:

```text
RecoveryRoutingPolicy
RecoveryRouteRule
RecoveryRouteDecision
RouteTarget
RouteReason
RetryBudget
SessionContextMode
```

Route targets:

```text
same_coder
switch_coder
same_verifier
switch_verifier
same_reviewer
switch_reviewer
architect_repack
architect_escalation
merge_retry
block_feature
manual_user_decision
no_action
```

Session context modes:

```text
none
summary_only
summary_plus_artifacts
full_structured_context
```

---

## 3. Config shape

Eventually load from `.grace/project.yaml`. For Phase 1, Pydantic defaults are enough.

Example:

```yaml
recovery_routing:
  enabled: false
  defaults:
    session_context_mode: summary_plus_artifacts
    never_downgrade_strict: true
    max_total_recovery_steps_per_packet: 8

  rules:
    - id: coder-first-failure
      when:
        failure_class: retryable_coder
        coder_attempt_count_lt: 2
      route:
        target: same_coder
        session_context_mode: summary_plus_artifacts
        reason: retryable coder failure under retry budget

    - id: coder-repeat-failure-switch
      when:
        failure_class: retryable_coder
        coder_attempt_count_gte: 2
        total_attempt_count_lt: 4
      route:
        target: switch_coder
        executor_strategy: next_stronger_or_different_provider
        session_context_mode: full_structured_context
        reason: repeated coder failure, switch model

    - id: coder-exhausted-return-architect
      when:
        failure_class: retryable_coder
        total_attempt_count_gte: 4
      route:
        target: architect_repack
        session_context_mode: full_structured_context
        reason: coder attempts exhausted, architect must repack

    - id: scope-impossible-architect
      when:
        failure_class: architect_repack_needed
        architect_repair_count_lt: 2
      route:
        target: architect_repack
        session_context_mode: full_structured_context
        reason: packet scope/verification impossible

    - id: architect-exhausted-escalate
      when:
        failure_class: architect_repack_needed
        architect_repair_count_gte: 2
      route:
        target: architect_escalation
        session_context_mode: full_structured_context
        reason: architect repair attempts exhausted

    - id: merge-dirty-target-block
      when:
        failure_class: true_blocker
        merge_error: DIRTY_TARGET_REPO
      route:
        target: block_feature
        reason: dirty target repo is not retryable

    - id: transient-merge-retry
      when:
        failure_class: merge_retryable
        merge_attempt_count_lt: 2
      route:
        target: merge_retry
        reason: transient merge failure under retry budget
```

Do not require YAML config in the first patch if it is too much. But the code model must be ready for it.

---

## 4. Rule evaluation

Rules are evaluated in order.

Behavior:

```text
1. Build FailureSignal.
2. Build RouteContext from packet/run/history/profile/session data.
3. Iterate rules in configured order.
4. First matching rule returns RecoveryRouteDecision.
5. If no rule matches, use safe fallback: block or escalate, never unsafe retry forever.
```

No side effects in rule evaluation.

Pure function:

```python
def decide_route(signal: FailureSignal, context: RouteContext, policy: RecoveryRoutingPolicy) -> RecoveryRouteDecision:
    ...
```

---

## 5. RouteContext

`RouteContext` must include:

```text
feature_id
wave_id
packet_id
run_id
attempt_number
acceptance_profile
self_improvement
affected_subsystem
risk_level
coder_attempt_count
same_executor_failure_count
verifier_retry_count
reviewer_retry_count
merge_attempt_count
architect_repair_count
unknown_failure_count
total_recovery_steps_for_packet
current_executor_id
previous_executor_ids
available_executors
session_resume_available
```

---

## 6. Session context routing

Every route may specify whether to attach session context.

Examples:

```text
same_coder after small failure → summary_plus_artifacts
switch_coder after repeated failure → full_structured_context
architect_repack → full_structured_context
merge_retry → summary_only
block_feature → summary_only for admin/human
```

The route decision must include:

```json
{
  "session_context_mode": "full_structured_context",
  "build_resume_context": true
}
```

If Phase 4 session memory is not implemented yet, decision still carries the desired mode and admin/UI can show `resume_context_pending`.

---

## 7. Stop conditions

Routing policy must have global stop guards:

```text
max_total_recovery_steps_per_packet
max_total_recovery_steps_per_feature
max_same_failure_class_repeats
max_wall_clock_duration_per_packet optional later
max_architect_repairs
true_blockers_block_immediately
```

If a stop guard hits:

```text
route target = block_feature or architect_escalation
reason = explicit stop condition
```

Never continue retrying silently.

---

## 8. Integration with RecoveryDecision

Existing `RecoveryDecision` can either become `RecoveryRouteDecision` or wrap it.

Required fields:

```text
action / route_target
reason
matched_rule_id
failure_class
current_executor_id
next_executor_hint
session_context_mode
build_resume_context
stop_condition_hit
safety_notes
```

Admin UI should show:

```text
Recovery route: switch coder
Rule: coder-repeat-failure-switch
Context: full structured resume
Reason: repeated coder failure, switch model
```

---

## 9. Tests required

Add tests:

```text
test_route_retry_same_coder_first_failure
test_route_switch_coder_after_repeated_failure
test_route_return_architect_after_attempt_budget
test_route_escalate_architect_after_repair_budget
test_route_block_dirty_target_repo
test_route_retry_transient_merge_under_budget
test_route_block_transient_merge_after_budget
test_route_unknown_falls_back_safe
test_rule_order_first_match_wins
test_custom_policy_overrides_default_route
test_strict_profile_never_downgraded_by_route
test_route_decision_includes_session_context_mode
test_route_stop_condition_blocks_infinite_loop
```

No real agents, git, API server, or LLM calls.

---

## 10. Fixture YAML requirements

Add staged fixture YAMLs that exercise routing, not only classification:

```text
fixtures/golden/recovery_route_same_coder.yaml
fixtures/golden/recovery_route_switch_coder.yaml
fixtures/golden/recovery_route_architect_repack.yaml
fixtures/golden/recovery_route_architect_escalation.yaml
fixtures/golden/recovery_route_merge_retry.yaml
fixtures/golden/recovery_route_block_true_blocker.yaml
fixtures/golden/recovery_route_with_full_session_context.yaml
```

Each fixture expected block must include:

```yaml
expected:
  recovery_route:
    matched_rule_id: coder-repeat-failure-switch
    target: switch_coder
    session_context_mode: full_structured_context
    must_not_lower_acceptance_profile: true
```

---

## 11. Acceptance criteria

Done only if:

```text
1. Recovery routing is policy-driven, not hardcoded in if/else branches.
2. Default policy exists and is tested.
3. Custom policy can change route decisions.
4. Route decision says who gets task next and why.
5. Route decision says whether session resume context is required.
6. Stop conditions prevent infinite loops.
7. True blockers cannot be made retryable by accident.
8. STRICT cannot be downgraded.
9. Staged routing fixtures exist.
10. Admin/event layer can display matched rule, target, reason, and session context mode.
```

---

## 12. Do not do

```text
Do not implement a complex general-purpose programming language in YAML.
Do not allow arbitrary Python expressions in config.
Do not make rules mutate DB directly.
Do not bypass RecoveryPolicy safety invariants.
Do not retry true blockers.
Do not require session memory implementation before routing can declare desired context mode.
```

---

## 13. Final coder report additions

Coder must report:

```text
RecoveryRoutingPolicy added: yes/no
Route rules configurable: yes/no
Custom policy tests added: yes/no
Session context mode in route decision: yes/no
Stop guards implemented: yes/no
Routing fixtures added: yes/no
Admin fields available: yes/no
Tests run
Remaining blockers
```
