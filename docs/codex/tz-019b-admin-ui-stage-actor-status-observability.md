# TZ 019b — Mission Control Center: stage/actor/status observability addendum

Audience: Flash coder / literal executor.

Parent spec:

```text
docs/codex/tz-019-admin-ui-duration-timers-observability.md
```

Goal: make every running/active packet understandable in the admin UI. The user must see not just `running`, but **who is working**, **what stage is active**, **how long it has been active**, **what happened before**, and **what the next expected transition is**.

This addendum is part of the Mission Control Center admin UI task. It must be implemented together with the dashboard/detail observability work, or at least the API fields must be prepared so UI can render it.

---

## 0. Problem

Current state labels are too vague:

```text
ready
claimed
running
evidence
accepted
merged
```

The UI says `running`, but the user cannot tell:

```text
who is running: coder, verifier, reviewer, architect, merge worker?
what exactly is running: agent, T0, T1, evidence verifier, reviewer, merge?
how long this stage has been running?
is it stuck or normal?
what is the next expected action?
what was the previous failure/reason?
```

Mission Control must make this explicit.

---

## 1. Required mental model

Separate three things:

```text
1. Packet lifecycle state
   READY / CLAIMED / RUNNING / EVIDENCE / ACCEPTED / MERGED / REJECTED / BLOCKED / FAILED

2. Active stage
   architect_plan / coder_agent / deterministic_acceptance / evidence_verifier / reviewer / merge / retry / blocked_waiting_user

3. Active actor/role
   architect / coder / deterministic_acceptance / evidence_verifier / reviewer / merge_worker / system / user
```

Do not collapse all of these into one `state=running`.

The UI should render a clear sentence like:

```text
Running · coder-agent · opencode · 6 минут 12 секунд
```

or:

```text
Evidence · evidence-verifier · agy-flash · 1 минута 04 секунды
```

or:

```text
Accepted · waiting for merge · 12 секунд
```

---

## 2. Canonical packet lifecycle states

Use existing states if already present, but UI must normalize them into readable labels.

Canonical display states:

```text
READY       → Ready
CLAIMED     → Claimed
RUNNING     → Running
EVIDENCE    → Evidence
REVIEW      → Review
ACCEPTED    → Accepted
MERGING     → Merging
MERGED      → Merged
REJECTED    → Rejected
BLOCKED     → Blocked
FAILED      → Failed
CANCELLED   → Cancelled
```

If code currently has no `REVIEW` or `MERGING` packet state, do not force a DB migration just for labels. Instead expose `active_stage` and render:

```text
state=RUNNING + active_stage=reviewer → Review
state=ACCEPTED + active_stage=merge → Merging / waiting merge
```

---

## 3. Required active_stage values

Expose `active_stage` on packet/run/dashboard/detail responses.

Allowed values:

```text
none
architect_context
architect_plan
architect_repair
packet_ready
worker_claim
coder_agent
git_change_detection
deterministic_t0
deterministic_t1
deterministic_t2
deterministic_acceptance
evidence_verifier
reviewer
merge_preflight
merge_apply
merge_verify
retry_scheduled
return_to_architect
blocked_waiting_user
blocked_safety
completed
failed
```

MVP minimum:

```text
packet_ready
worker_claim
coder_agent
deterministic_acceptance
evidence_verifier
reviewer
merge_apply
retry_scheduled
return_to_architect
blocked_safety
completed
failed
```

---

## 4. Required active_actor / active_role values

Expose `active_actor` or `active_role`.

Allowed role values:

```text
system
architect
context_builder
coder
deterministic_acceptance
evidence_verifier
reviewer
merge_worker
recovery_controller
user
unknown
```

Also expose executor/model when available:

```json
{
  "active_role": "coder",
  "active_executor_id": "coder-flash",
  "active_model": "deepseek-chat",
  "active_provider": "openrouter"
}
```

For deterministic stages:

```json
{
  "active_role": "deterministic_acceptance",
  "active_executor_id": "internal",
  "active_model": null
}
```

For merge:

```json
{
  "active_role": "merge_worker",
  "active_executor_id": "internal-merge",
  "active_model": null
}
```

---

## 5. Required timing fields per active stage

For each packet, expose:

```json
{
  "state": "running",
  "active_stage": "coder_agent",
  "active_role": "coder",
  "active_executor_id": "coder-flash",
  "active_stage_started_at": "2026-06-04T10:11:12Z",
  "active_stage_elapsed_seconds": 372,
  "active_stage_elapsed_human": "6 минут 12 секунд",
  "packet_elapsed_seconds": 912,
  "packet_elapsed_human": "15 минут 12 секунд"
}
```

Do not only show packet-level elapsed time. The user needs both:

```text
packet total elapsed
current stage elapsed
```

Example UI:

```text
▶ Add artifact viewer
Running · coder-agent · coder-flash
Stage: 6 минут 12 секунд · Packet: 15 минут 12 секунд
```

---

## 6. Required next_action field

Expose human-readable `next_action` for packet detail and compact rows.

Examples:

```text
waiting for worker claim
coder is editing files in worktree
running deterministic checks T1
waiting for evidence verifier
waiting for reviewer
ready to merge
merge preflight running
returning to architect for repack
blocked: user decision required
blocked: safety gate failed
retry scheduled
completed
```

API field:

```json
{
  "next_action": "running deterministic checks T1"
}
```

This is not a command. It is UI explanation.

---

## 7. Stage history / timeline events

Packet detail must show stage history, not only final state.

For each run/attempt, expose stage transitions:

```json
{
  "stage_history": [
    {
      "stage": "worker_claim",
      "role": "system",
      "started_at": "...",
      "finished_at": "...",
      "duration_human": "2 секунды",
      "summary": "worker claimed packet"
    },
    {
      "stage": "coder_agent",
      "role": "coder",
      "executor_id": "coder-flash",
      "started_at": "...",
      "finished_at": "...",
      "duration_human": "6 минут 12 секунд",
      "summary": "agent produced worktree changes"
    },
    {
      "stage": "deterministic_acceptance",
      "role": "deterministic_acceptance",
      "started_at": "...",
      "finished_at": "...",
      "duration_human": "18 секунд",
      "summary": "T0/T1/T2 passed"
    }
  ]
}
```

If a full stage-history table does not exist yet, derive it from events/PacketRun result_json as MVP.

Do not block the whole admin UI on perfect historical accuracy. But from now on, new runs should record stage transitions explicitly.

---

## 8. Packet row requirements

Compact packet row must show enough information to understand status without opening detail.

Required row fields:

```text
status icon/text
packet short title
lifecycle state
active stage
active actor/role
executor/model if available
attempt count
stage elapsed
packet elapsed/duration
last reason if failed/rejected/blocked
artifact count
```

Example rows:

```text
▶ Add artifact viewer   Running · coder-agent · coder-flash   stage 6м 12с · packet 15м 12с   attempt 2/3   artifacts: 3
◐ Evidence checks       Evidence · verifier · agy-flash       stage 1м 04с · packet 18м 33с   attempt 1/3   artifacts: 5
◆ Reviewer gate         Review · reviewer · codex-5.2         stage 2м 15с · packet 21м 10с   attempt 1/3   artifacts: 7
✓ Merge API hardening   Merged                              duration 9м 40с                attempts 1/3   artifacts: 9
! Mobile layout         Rejected · T1 failed                 duration 7м 14с                attempts 2/3   artifacts: 4
⛔ Git merge             Blocked · dirty target repo          after 12с                      attempts 1/3
```

Do not render only:

```text
running
```

That is not enough.

---

## 9. Feature and wave summary requirements

Feature/wave summary must show what role is currently active inside them.

Example feature card:

```text
GRACE Mission Control Center
12 packets · 7 merged · 2 running · 1 blocked
Active now: coder 1 · verifier 1
Longest running: Add artifact viewer · coder-agent · 15 минут 12 секунд
```

Example wave header:

```text
Wave 2 · Packet Detail + Artifacts
2 running · 1 ready · 3 merged
Active: reviewer on “Artifact preview” for 2 минуты 15 секунд
```

Add aggregate fields where possible:

```json
{
  "active_roles": {
    "coder": 1,
    "evidence_verifier": 1,
    "reviewer": 0,
    "merge_worker": 0
  },
  "longest_running_packet": {
    "id": "pkt_...",
    "title": "Add artifact viewer",
    "active_stage": "coder_agent",
    "elapsed_human": "15 минут 12 секунд"
  }
}
```

---

## 10. API response additions

Update `/api/dashboard/v2` feature/wave/packet objects with:

```json
{
  "state": "running",
  "state_label": "Running",
  "active_stage": "coder_agent",
  "active_stage_label": "Coder agent",
  "active_role": "coder",
  "active_role_label": "Coder",
  "active_executor_id": "coder-flash",
  "active_model": "deepseek-chat",
  "active_stage_started_at": "...",
  "active_stage_elapsed_seconds": 372,
  "active_stage_elapsed_human": "6 минут 12 секунд",
  "packet_elapsed_seconds": 912,
  "packet_elapsed_human": "15 минут 12 секунд",
  "next_action": "coder is editing files in worktree",
  "last_reason": null
}
```

Update `/api/packets/{packet_id}` response with:

```json
{
  "packet": {
    "state": "running",
    "active_stage": "coder_agent",
    "active_role": "coder",
    "active_executor_id": "coder-flash",
    "active_stage_elapsed_human": "6 минут 12 секунд",
    "next_action": "coder is editing files in worktree"
  },
  "runs": [
    {
      "attempt_number": 2,
      "status": "running",
      "active_stage": "coder_agent",
      "active_role": "coder",
      "stage_history": []
    }
  ]
}
```

Do not remove existing fields.

---

## 11. Status label mapping

Add one backend or frontend mapping helper. Prefer backend labels so API is easy to render.

Required mapping examples:

```text
packet_ready              → Ready
worker_claim              → Claimed
coder_agent               → Coder agent
git_change_detection      → Change detection
deterministic_t0          → T0 scope/lint
deterministic_t1          → T1 tests
deterministic_t2          → T2 full verification
deterministic_acceptance  → Acceptance checks
evidence_verifier         → Evidence verifier
reviewer                  → Reviewer
merge_preflight           → Merge preflight
merge_apply               → Merge
merge_verify              → Merge verify
retry_scheduled           → Retry scheduled
return_to_architect       → Return to architect
blocked_waiting_user      → Waiting for user
blocked_safety            → Safety blocked
completed                 → Completed
failed                    → Failed
```

---

## 12. Stuck detection

Add UI warning for suspicious long-running stages.

Thresholds should be configurable or constants:

```text
coder_agent > 20 min → warn
acceptance > 5 min → warn
verifier > 10 min → warn
reviewer > 15 min → warn
merge > 2 min → warn
claimed > 2 min without running → warn
```

UI examples:

```text
⚠ coder-agent running 28 минут — possibly stuck
⚠ claimed 4 минуты — worker may be stale
```

Do not auto-cancel in this task. UI warning only.

---

## 13. Events required for stage tracking

If current events are insufficient, add stage transition events:

```text
stage_started
stage_finished
stage_failed
```

Payload:

```json
{
  "packet_id": "pkt_...",
  "run_id": "run_...",
  "attempt_number": 2,
  "stage": "coder_agent",
  "role": "coder",
  "executor_id": "coder-flash",
  "model": "deepseek-chat",
  "started_at": "...",
  "finished_at": null,
  "summary": "agent started"
}
```

For MVP, if adding events is too big, derive current stage from existing run/result_json fields but still add API fields.

---

## 14. UI placement

### Main dashboard

Each packet row must show:

```text
State · Stage · Actor/executor · stage elapsed · attempt count
```

### Packet detail overview

Show a clear current work block:

```text
Current work
Role: Coder
Executor: coder-flash
Stage: Coder agent
Stage elapsed: 6 минут 12 секунд
Packet elapsed: 15 минут 12 секунд
Next: coder is editing files in worktree
```

### Runs tab

Each run must show:

```text
attempt status
active/final stage
executor/model
duration
stage history expand/collapse
```

### Events tab

Stage events must be visible and filterable:

```text
stage_started
stage_finished
stage_failed
```

---

## 15. Tests required

Add API tests:

```text
test_dashboard_packet_includes_active_stage_role_executor
test_dashboard_packet_running_not_only_running_label
test_packet_detail_includes_current_work_block_fields
test_packet_detail_run_includes_stage_history
test_active_stage_elapsed_human_present
test_next_action_present_for_running_packet
test_stuck_detection_marks_long_running_coder
test_stuck_detection_marks_claimed_without_running
```

Add UI/template tests:

```text
test_packet_row_shows_stage_actor_and_elapsed
test_packet_detail_current_work_block_rendered
test_runs_tab_shows_stage_history
test_feature_summary_shows_active_roles
test_wave_summary_shows_active_stage
```

Add Playwright tests:

```text
test_running_packet_shows_who_is_working
  open dashboard with seeded running coder packet
  assert visible: Running, coder-agent, coder-flash, elapsed

test_verifier_packet_shows_evidence_stage
  assert visible: Evidence, evidence-verifier, executor, elapsed

test_reviewer_packet_shows_review_stage
  assert visible: Review, reviewer, executor, elapsed

test_merge_packet_shows_merge_stage
  assert visible: Merge/Merging, merge_worker, elapsed

test_stuck_packet_warning_visible
  seeded coder stage > threshold
  assert warning visible
```

All Playwright tests must fail on `pageerror` and `console.error` as defined in TZ-019.

---

## 16. Demo data requirements

Mission Control demo seed must include packets in these active stages:

```text
ready
claimed
coder_agent running
deterministic_acceptance running
evidence_verifier running
reviewer running
merge_apply running
accepted waiting merge
rejected after tests failed
blocked safety
merged
```

This is required so the UI can be visually tested without a live agent run.

---

## 17. Acceptance criteria addendum

Mission Control Center is not complete unless:

```text
1. A running packet row shows active stage, not only running.
2. A running packet row shows active role/actor.
3. A running packet row shows executor/model when available.
4. A running packet row shows current stage elapsed time.
5. Packet detail has a Current work block.
6. Runs tab shows stage history or derived stage timeline.
7. Feature summary shows active roles count.
8. Wave summary shows active stage/role information.
9. Stuck stages are visibly warned.
10. Demo data includes coder/verifier/reviewer/merge active examples.
11. Playwright confirms coder/verifier/reviewer/merge labels are visible.
12. No UI displays ambiguous bare `running` without explaining who/what is running.
```

---

## 18. Do not do in this addendum

```text
Do not change state machine semantics.
Do not auto-cancel stuck packets.
Do not implement recovery/escalation here.
Do not hide raw state; show readable label plus raw state in detail if needed.
Do not use colors as the only indicator.
Do not parse role/stage from packet ID or branch name.
```

---

## 19. Final coder report additions

Coder must additionally report:

```text
active_stage API fields added: yes/no
active_role/actor API fields added: yes/no
executor/model visible: yes/no
stage elapsed visible: yes/no
packet current work block added: yes/no
stage history/timeline added: yes/no
stuck warnings added: yes/no
demo data covers coder/verifier/reviewer/merge: yes/no
Playwright stage/actor tests added: yes/no
```
