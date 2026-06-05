# TZ 017c — Recovery config + required recovery fixture YAMLs

Audience: Flash coder / literal executor.

Parent specs:

```text
docs/codex/tz-017-feature-recovery-escalation-policy.md
docs/codex/tz-017b-feature-recovery-controller-live-wiring.md
docs/codex/tz-020-golden-fixtures-staged-scenarios.md
```

Goal: make explicit that recovery policy thresholds are configurable, not hardcoded, and that implementation is incomplete until recovery fixture YAMLs exist under `fixtures/golden/`.

---

## 0. Current repository state reminder

At the time this TZ is written, recovery is specified but not implemented.

Expected missing files before implementation:

```text
src/grace_control/core/feature_recovery.py
src/grace_control/core/recovery_controller.py
src/grace_control/api/routers/recovery.py
fixtures/golden/recovery_*.yaml
tests/grace_control/core/test_feature_recovery.py
tests/golden_fixtures/test_fixture_recovery_scenarios.py
```

This is intentional until TZ-017/TZ-017b/TZ-020 are implemented.

---

## 1. Policy must be configurable, not hardcoded

Do not hardcode retry/escalation thresholds directly in action logic.

All thresholds must live in `RecoveryPolicy` and later be loadable from project config.

Default policy values are allowed, but they must be defaults only.

Suggested default config:

```yaml
recovery:
  enabled: false
  coder:
    retry_same_until: 2
    switch_until_total: 4
    return_to_architect_after: 4
  architect:
    escalate_after_repairs: 2
  verifier:
    max_parser_retries: 2
  reviewer:
    max_parser_retries: 2
  merge:
    max_retries: 2
  unknown:
    retry_once: true
  safety:
    never_downgrade_strict: true
    true_blockers_block_feature: true
```

The exact storage can be:

```text
RecoveryPolicy Pydantic defaults first
then .grace/project.yaml support later
then env override only where useful for tests
```

---

## 2. Required RecoveryPolicy fields

`RecoveryPolicy` must include at least:

```python
class RecoveryPolicy(BaseModel):
    max_same_coder_attempts: int = 2
    max_total_coder_attempts: int = 4
    max_architect_repairs: int = 2
    max_verifier_retries: int = 2
    max_reviewer_retries: int = 2
    max_merge_retries: int = 2
    retry_unknown_once: bool = True
    allow_profile_escalation: bool = True
    allow_model_switch: bool = True
    never_downgrade_strict: bool = True
```

Tests must prove custom values change decisions.

Required tests:

```text
test_custom_same_coder_threshold_changes_retry_vs_switch
test_custom_total_coder_attempts_changes_return_to_architect
test_custom_merge_retry_limit_changes_retry_vs_block
test_custom_architect_repair_limit_changes_escalation
test_strict_never_downgraded_even_with_custom_policy
```

---

## 3. Recovery fixture YAMLs are mandatory

Implementation is not complete until recovery YAML fixtures exist.

Create under:

```text
fixtures/golden/
```

Minimum required YAML files for first implementation:

```text
fixtures/golden/recovery_coder_fail_once_retry_same.yaml
fixtures/golden/recovery_coder_fail_twice_switch_model.yaml
fixtures/golden/recovery_coder_fail_four_times_return_architect.yaml
fixtures/golden/recovery_merge_dirty_target_true_blocker.yaml
fixtures/golden/recovery_merge_transient_retry.yaml
fixtures/golden/recovery_blocked_retry_denied.yaml
fixtures/golden/recovery_verifier_return_to_architect.yaml
fixtures/golden/recovery_reviewer_rework_to_coder.yaml
fixtures/golden/recovery_strict_profile_never_downgraded.yaml
```

These fixtures are required even if first version is seed-only.

---

## 4. Recovery fixture YAML shape

Each recovery fixture must include:

```yaml
id: recovery_coder_fail_twice_switch_model
kind: golden_fixture
start_stage: recovery
profile: NORMAL

feature:
  title: Recovery coder switch
  slug: recovery-coder-switch

wave:
  title: Recovery wave
  order: 1

packet:
  title: Fix small API bug
  slug: fix-small-api-bug
  state: rejected
  acceptance_profile: NORMAL
  scope:
    - sandbox/golden/recovery_coder_switch/
  verification:
    t0: []
    t1:
      - python3 -m pytest sandbox/golden/recovery_coder_switch/test_api.py -q
    t2: []

failure_signal:
  failure_class_hint: retryable_coder
  reason: T1 failed twice
  acceptance_verdict: rework_required
  coder_attempt_count: 2
  attempt_count: 2
  current_executor_id: coder-flash
  previous_executor_ids:
    - coder-flash
    - coder-flash

runs:
  - attempt: 1
    status: rejected
    executor_id: coder-flash
    result_json:
      acceptance_report:
        final_verdict: rework_required
        summary: T1 failed
  - attempt: 2
    status: rejected
    executor_id: coder-flash
    result_json:
      acceptance_report:
        final_verdict: rework_required
        summary: T1 failed again

expected:
  recovery:
    failure_class: retryable_coder
    action: switch_coder
    next_executor_hint_any_of:
      - coder-agy-flash
      - coder-agy-sonnet
    must_not_block_feature: true
    must_not_lower_acceptance_profile: true
```

Do not require generated UIDs in YAML.
Fixture seeder must generate `feat_...`, `wave_...`, `pkt_...`.

---

## 5. Seed-only mode is acceptable before controller lands

If `RecoveryController` is not implemented yet, fixture runner must still be able to:

```text
parse recovery YAML
create Feature/Wave/Packet/PacketRun test state
write fixture report
validate FailureSignal-compatible payload
mark execution as pending_recovery_controller
```

Once `feature_recovery.py` and `RecoveryController` exist, the same fixtures must become executable checks:

```text
build FailureSignal
call classify_failure(...)
call decide_recovery(...)
optionally apply decision if running TZ-017b integration tests
validate expected.recovery
```

---

## 6. Acceptance criteria addendum

Recovery implementation is incomplete unless:

```text
1. RecoveryPolicy thresholds are configurable.
2. Default thresholds are not magic hardcoded numbers inside action branches.
3. Tests prove custom policy values change behavior.
4. Required recovery_*.yaml files exist under fixtures/golden/.
5. Fixture YAMLs do not contain generated UIDs.
6. Fixture runner supports start_stage=recovery at least in seed-only mode.
7. Recovery fixture tests exist and do not run real LLMs/agents.
8. TZ-017b controller tests can later reuse the same YAML fixtures.
```

---

## 7. Final coder report additions

Coder must report:

```text
RecoveryPolicy configurable: yes/no
Custom policy tests added: yes/no
Recovery YAML fixtures added: yes/no
start_stage=recovery supported: seed-only/executable/no
Recovery fixtures use generated UIDs only at seed time: yes/no
Recovery fixture tests added: yes/no
Remaining blockers
```
