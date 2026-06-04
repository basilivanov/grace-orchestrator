# TZ 019c — Mission Control Center: always-visible event stream + recovery/stability observability

Audience: Flash coder / literal executor.

Parent specs:

```text
docs/codex/tz-019-admin-ui-duration-timers-observability.md
docs/codex/tz-019b-admin-ui-stage-actor-status-observability.md
docs/codex/tz-017-feature-recovery-escalation-policy.md
```

Goal: extend Mission Control Center so the user always sees the live event stream for features/waves/packets/runs, including which role/agent/model started, what stage is active, and how feature-recovery/stability decisions are progressing.

This is a UI/API observability addendum. It must prepare the frontend for the future feature stability layer from TZ-017: retry same coder, switch model, return to architect, escalate architect, retry verifier/reviewer/merge, or block feature.

---

## 0. Product requirement

The admin UI must always answer:

```text
What just happened?
Who started working?
Which agent/model is currently working?
Which stage started/finished/failed?
Why was the packet retried/switched/returned/blocked?
What recovery decision was made?
```

The user must not need to open raw logs to understand the pipeline.

Events must be visible at all levels:

```text
Feature events
Wave events
Packet events
Run/attempt events
Agent/model events
Recovery/stability events
Merge events
```

---

## 1. Always-visible events principle

Mission Control must include an always-visible compact event stream.

Desktop layout:

```text
Main board: features/waves/packets
Right or bottom panel: Live Events
Packet detail: Events tab + compact recent events in Overview
```

Mobile layout:

```text
Feature screen: last 3 feature events
Packet detail: Events tab
```

The events panel must not overwhelm the main dashboard, but it must always be discoverable and visible enough that the user sees live activity.

Minimum desktop behavior:

```text
A compact Live Events panel shows latest 20 events for selected feature.
Packet detail Overview shows latest 5 packet events.
Events tab shows full filtered event list.
```

---

## 2. Required event types

Add/normalize event types for all major stages.

### 2.1 Architect/context events

```text
context_builder_started
context_builder_completed
context_builder_failed
architect_started
architect_generated_plan
architect_failed
architect_repair_started
architect_repair_completed
architect_repair_failed
```

Required payload fields:

```json
{
  "feature_id": "feat_...",
  "feature_slug": "...",
  "role": "architect",
  "executor_id": "architect-pro",
  "model": "deepseek/deepseek-v4-pro",
  "provider": "openrouter",
  "stage": "architect_plan",
  "summary": "Architect started planning feature"
}
```

### 2.2 Worker/coder events

```text
packet_ready
packet_claimed
coder_agent_started
coder_agent_completed
coder_agent_failed
worktree_created
worktree_reused
branch_created
change_detection_started
change_detection_completed
scope_guard_started
scope_guard_passed
scope_guard_failed
```

Required payload fields for agent start:

```json
{
  "feature_id": "feat_...",
  "wave_id": "wave_...",
  "packet_id": "pkt_...",
  "run_id": "run_...",
  "attempt_number": 2,
  "role": "coder",
  "executor_id": "coder-flash",
  "model": "deepseek/deepseek-v4-flash",
  "provider": "openrouter",
  "stage": "coder_agent",
  "worktree_path": "...",
  "branch_name": "agent/default/pkt_.../attempt-0002",
  "summary": "Coder agent started"
}
```

### 2.3 Deterministic acceptance events

```text
acceptance_started
acceptance_t0_started
acceptance_t0_passed
acceptance_t0_failed
acceptance_t1_started
acceptance_t1_passed
acceptance_t1_failed
acceptance_t2_started
acceptance_t2_passed
acceptance_t2_failed
acceptance_completed
acceptance_rejected
```

Required payload:

```json
{
  "role": "deterministic_acceptance",
  "stage": "deterministic_t1",
  "command": "python3 -m pytest ...",
  "exit_code": 0,
  "duration_ms": 12000,
  "summary": "T1 passed"
}
```

### 2.4 Evidence verifier events

```text
evidence_verifier_started
evidence_verifier_completed
evidence_verifier_failed
evidence_verifier_rework_to_coder
evidence_verifier_return_to_architect
```

Required payload:

```json
{
  "role": "evidence_verifier",
  "executor_id": "verifier-flash",
  "model": "deepseek/deepseek-v4-flash",
  "provider": "openrouter",
  "stage": "evidence_verifier",
  "verdict": "REWORK_TO_CODER",
  "summary": "Expected evidence missing"
}
```

### 2.5 Reviewer events

```text
reviewer_started
reviewer_completed
reviewer_failed
reviewer_accepted
reviewer_rework_to_coder
reviewer_return_to_architect
reviewer_blocked
```

Required payload:

```json
{
  "role": "reviewer",
  "executor_id": "reviewer-strict",
  "model": "codex-5.2-xhigh",
  "provider": "openai",
  "stage": "reviewer",
  "verdict": "RETURN_TO_ARCHITECT",
  "summary": "Packet scope is impossible"
}
```

### 2.6 Merge events

```text
merge_requested
merge_preflight_started
merge_preflight_passed
merge_preflight_failed
merge_started
merge_completed
merge_failed
merge_conflict
merge_dirty_target_repo
merge_missing_worktree
merge_missing_branch
packet_merged
```

Required payload:

```json
{
  "role": "merge_worker",
  "stage": "merge_apply",
  "packet_id": "pkt_...",
  "branch_name": "agent/default/pkt_.../attempt-0001",
  "worktree_path": "...",
  "commit_sha": "...",
  "target_repo_root": "...",
  "summary": "Merge started"
}
```

---

## 3. Recovery/stability events from TZ-017

Mission Control must be ready to display feature-recovery decisions from:

```text
docs/codex/tz-017-feature-recovery-escalation-policy.md
```

Required event types:

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
```

Required payload:

```json
{
  "feature_id": "feat_...",
  "packet_id": "pkt_...",
  "failure_class": "retryable_coder",
  "action": "switch_coder",
  "reason": "coder failed deterministic acceptance twice",
  "current_executor_id": "coder-flash",
  "next_executor_hint": "coder-agy-sonnet",
  "attempt_count": 3,
  "acceptance_profile": "NORMAL",
  "next_acceptance_profile": "NORMAL",
  "summary": "Switching coder model after repeated T1 failures"
}
```

UI must render this as human text:

```text
Recovery · switch coder · coder-flash → coder-agy-sonnet · repeated T1 failures
```

---

## 4. Recovery/stability UI requirements

The UI must show feature-stability state, not only packet state.

### 4.1 Feature summary

Feature card/header should show:

```text
Recovery: active / inactive
Retries: 2 coder, 0 verifier, 0 reviewer, 1 merge
Last recovery: switched coder 3 минуты назад
Blocked: no / yes
```

Example:

```text
SolarSage Admin UI
2 running · 1 rejected · recovery active
Last recovery: switched coder coder-flash → coder-agy-sonnet
```

### 4.2 Packet row

Packet row should show recovery hint if active:

```text
! Tests failed · recovery: retry same coder
! Tests failed twice · recovery: switch coder
⤴ Scope impossible · returning to architect
⛔ Dirty target repo · true blocker
```

### 4.3 Packet detail Overview

Add block:

```text
Recovery / Stability
Failure class: retryable_coder
Decision: switch coder
Reason: T1 failed twice
Previous executor: coder-flash
Next executor: coder-agy-sonnet
Attempt: 3/4
```

If no recovery decision:

```text
Recovery: inactive
```

### 4.4 Events tab

Events tab must include recovery events and allow filter:

```text
All | Lifecycle | Agents | Acceptance | Verifier | Reviewer | Merge | Recovery | Errors
```

---

## 5. Event display requirements

Every event row must include:

```text
time
scope/entity: feature/wave/packet/run
stage
role/actor
executor/model if available
status/result
human summary
expandable payload
trace_id copy button if available
```

Example event rows:

```text
12:01:02  Architect   deepseek-v4-pro      started planning feature
12:01:18  Architect   deepseek-v4-pro      generated 3 waves / 12 packets
12:02:01  Worker      worker-a13f          claimed pkt_AbC123
12:02:02  Coder       coder-flash          started coder-agent, attempt #1
12:08:14  Coder       coder-flash          completed after 6 минут 12 секунд
12:08:15  Acceptance  T1                   started pytest
12:08:42  Acceptance  T1                   failed after 27 секунд
12:08:43  Recovery    switch_coder          coder-flash → coder-agy-sonnet
```

Do not display only raw event names.

---

## 6. Event severity / badges

Normalize severity:

```text
info
success
warning
error
blocked
recovery
```

Examples:

```text
agent started → info
acceptance passed → success
retry scheduled → warning
merge failed → error
true blocker → blocked
switch coder → recovery
```

Color may help but must not be the only signal. Include text labels.

---

## 7. API additions

Extend `/api/dashboard/v2` with feature-level recent events:

```json
{
  "features": [
    {
      "id": "feat_...",
      "recent_events": [],
      "recovery_summary": {
        "active": true,
        "last_action": "switch_coder",
        "last_reason": "T1 failed twice",
        "last_event_at": "...",
        "retry_counts": {
          "coder": 2,
          "verifier": 0,
          "reviewer": 0,
          "merge": 0
        }
      }
    }
  ]
}
```

Extend `/api/packets/{packet_id}` with:

```json
{
  "events": [
    {
      "id": "evt_...",
      "timestamp": "...",
      "event_type": "coder_agent_started",
      "severity": "info",
      "entity_type": "packet",
      "entity_id": "pkt_...",
      "feature_id": "feat_...",
      "wave_id": "wave_...",
      "packet_id": "pkt_...",
      "run_id": "run_...",
      "attempt_number": 1,
      "stage": "coder_agent",
      "role": "coder",
      "executor_id": "coder-flash",
      "model": "deepseek/deepseek-v4-flash",
      "provider": "openrouter",
      "summary": "Coder agent started",
      "payload": {}
    }
  ],
  "recovery": {
    "active": true,
    "failure_class": "retryable_coder",
    "action": "switch_coder",
    "reason": "T1 failed twice",
    "current_executor_id": "coder-flash",
    "next_executor_hint": "coder-agy-sonnet"
  }
}
```

Add optional endpoint if easier:

```text
GET /api/events?feature_id=feat_...&packet_id=pkt_...&limit=100&type=recovery
```

But do not block MVP if existing packet detail can include events.

---

## 8. Event persistence rules

Events must be DB-backed, not only logs.

When a major stage starts/completes/fails:

```text
record_event(...)
```

Payload must include enough context for UI:

```text
feature_id
wave_id
packet_id
run_id
attempt_number
stage
role
executor_id
model
provider
summary
trace_id
```

If model/provider are unknown, use null. Do not fake them.

For deterministic internal stages:

```text
executor_id = internal
model = null
provider = null
```

---

## 9. Stage + event consistency

The following active_stage values from TZ-019b must map to events:

```text
architect_context → context_builder_started/completed
architect_plan → architect_started/generated/failed
coder_agent → coder_agent_started/completed/failed
deterministic_t0 → acceptance_t0_started/passed/failed
deterministic_t1 → acceptance_t1_started/passed/failed
deterministic_t2 → acceptance_t2_started/passed/failed
evidence_verifier → evidence_verifier_started/completed/failed
reviewer → reviewer_started/completed/failed
merge_apply → merge_started/completed/failed
retry_scheduled → recovery_retry_same_coder or packet_retry_scheduled
return_to_architect → recovery_return_to_architect
blocked_safety → recovery_block_feature / reviewer_blocked / merge_dirty_target_repo
```

A packet should never show `active_stage=reviewer` if no reviewer event exists for the current run, unless this is legacy data and UI marks it as derived.

---

## 10. Stability-first implementation order

The user plans to implement feature execution stability before the full admin UI.

Therefore Mission Control UI/API must be designed to display the future stability layer even if it is not active yet.

Implementation order:

```text
1. TZ-017 feature recovery core/policy.
2. TZ-020 staged fixtures for recovery/merge/verifier/reviewer scenarios.
3. Event recording additions for recovery decisions and agent/stage starts.
4. Mission Control UI reads and renders those events/recovery summaries.
```

Admin UI must not hardcode a world where only coder/acceptance/merge exist. It must already support:

```text
retry same coder
switch coder/model
return to architect
architect repair
escalate architect
retry verifier
retry reviewer
retry merge
block feature
no action
```

---

## 11. Tests required

API tests:

```text
test_dashboard_feature_includes_recent_events
test_dashboard_feature_includes_recovery_summary
test_packet_detail_includes_agent_model_events
test_packet_detail_includes_recovery_events
test_packet_detail_includes_merge_events
test_event_payload_has_stage_role_executor_model_fields
test_internal_stage_event_uses_internal_executor_and_null_model
test_recovery_decision_event_renders_action_and_reason
test_no_running_packet_without_stage_start_event_for_current_run
```

UI/template tests:

```text
test_live_events_panel_visible_on_dashboard
test_packet_overview_shows_recent_events
test_events_tab_filters_recovery_events
test_event_row_shows_role_and_model
test_recovery_block_visible_when_active
test_switch_coder_event_shows_old_and_new_executor
```

Playwright tests:

```text
test_live_events_panel_shows_architect_coder_verifier_reviewer_events
test_agent_event_shows_model_name
test_recovery_switch_coder_visible_in_events
test_recovery_return_to_architect_visible_in_packet_detail
test_merge_dirty_target_event_visible_as_blocker
```

Fixture/demo data must include:

```text
context builder started/completed
architect started/completed
coder started/completed with model
acceptance T1 failed
recovery switch coder
verifier return_to_architect
reviewer rework_to_coder
merge dirty target repo
blocked safety
```

---

## 12. Acceptance criteria addendum

Mission Control Center is not complete unless:

```text
1. Live Events panel is visible on dashboard.
2. Packet detail shows latest packet events in Overview.
3. Events tab shows full event list.
4. Event rows show role/actor, stage, executor, and model if available.
5. Architect/context/coder/verifier/reviewer/merge events are represented.
6. Agent start events include executor_id and model when available.
7. Recovery/stability events from TZ-017 are represented in API shape.
8. UI can display retry same coder, switch coder, return architect, escalate, retry merge, and block decisions.
9. Feature summary shows recovery summary if active.
10. Packet detail shows Recovery / Stability block.
11. Demo data includes recovery/stability events.
12. Playwright verifies model names are visible for agent events.
13. UI never requires raw logs to understand who is currently working.
```

---

## 13. Do not do in this addendum

```text
Do not implement the recovery policy here.
Do not change retry behavior here.
Do not fake model names if unknown.
Do not replace structured logs with DB events; keep both.
Do not show only raw JSON payloads.
Do not hide events behind debug-only UI.
Do not make events depend on old FEAT/W01/P01 IDs.
```

---

## 14. Final coder report additions

Coder must additionally report:

```text
Live Events panel added: yes/no
Feature recent events API added: yes/no
Packet events API added: yes/no
Agent model visible in events: yes/no
Architect/context events represented: yes/no
Verifier/reviewer events represented: yes/no
Recovery summary shape added: yes/no
Recovery events rendered: yes/no
Event filters added: yes/no
Tests added
Tests run
Remaining blockers
```
