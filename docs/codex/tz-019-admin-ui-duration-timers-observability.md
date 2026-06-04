# TZ 019 — GRACE Mission Control Center: admin UI observability, stages, events, recovery

Audience: Flash coder / literal executor.

This is the single canonical TZ for the GRACE admin UI work.

It replaces and consolidates:

```text
docs/codex/tz-019-admin-ui-duration-timers-observability.md
docs/codex/tz-019b-admin-ui-stage-actor-status-observability.md
docs/codex/tz-019c-admin-event-stream-and-recovery-observability.md
```

After this consolidation, `tz-019b-*` and `tz-019c-*` must not be recreated. Any future admin UI observability changes belong in this file or in a new numbered TZ.

Interface name:

```text
GRACE Mission Control Center
```

Goal: make the current `grace-orchestrator` admin UI operationally useful for watching long-running GRACE work. The UI must show features, waves, packets, runs/attempts, artifacts, evidence, events, active stage/actor, live durations, recovery decisions, and self-improvement work in one calm interface.

This task is UI/API/data/test observability work. It must not change orchestration semantics, retry policy, deterministic acceptance, reviewer gates, merge behavior, or safety gates.

---

## 0. Current implementation baseline

Do not implement this as a greenfield dashboard. The current code already contains important pieces that must be kept and extended.

Already implemented in current codebase:

```text
FastAPI app
HTML template dashboard
vanilla JavaScript dashboard code
/api/packets/
/api/workers/
/api/dashboard/v2
/api/events
/api/artifacts/{packet_id}/{run_id:path}
/ws WebSocket endpoint
src/grace_control/api/ws_broadcast.py
src/grace_control/api/routers/recovery.py
RecoveryController
Recovery session stubs
packet inspector recovery section
recovery_* event filtering
```

Existing Dashboard v2 capabilities to preserve:

```text
WebSocket real-time updates
initial REST fetch for packets/workers/health
state_change broadcasts on claim/release/cancel/merge
stats cards
timeline dots: ready → running → accepted → merged
packet artifact/evidence modal
worker status display
tooltips
```

Existing recovery capabilities to preserve:

```text
POST /api/recovery/evaluate/{packet_id}
GET /api/recovery/packets/{packet_id}
GET /api/recovery/features/{feature_id}
Dashboard API includes packet recovery data
Packet detail includes recovery data
/api/events supports recovery_* prefix filtering
WebSocket can broadcast recovery_update
PacketExecutor can honor spec_json.recovery.requested_executor_id
Recovery session stubs exist but session_resume_available=false
```

Therefore this TZ is mainly about consolidation and completion:

```text
rename/shape the UI as GRACE Mission Control Center
move from flat packet table toward feature → wave → packet hierarchy
show duration and live timer fields everywhere they matter
show active_stage, active_role, executor/model/provider and next_action
show compact live events and full filtered event history
show recovery/stability status without raw JSON hunting
add tests that catch JavaScript/template regressions
```

---

## 1. Non-goals and safety constraints

Do not add:

```text
React
Vue
Svelte
separate frontend build stack
heavy dashboard library
new workflow engine
websockets-only design without REST/polling fallback
new recovery engine competing with RecoveryController
new acceptance semantics
new merge semantics
```

Do not bypass:

```text
scope guard
deterministic acceptance
reviewer gates
STRICT packet protections
merge preflight
human/safety blockers
```

Do not auto-cancel or auto-recover anything as part of UI warnings. Stuck detection in this TZ is display-only unless existing recovery policy explicitly decides otherwise.

---

## 2. Product intent

The user must understand in a few seconds:

```text
1. What is running now.
2. Where problems are.
3. Which features/waves/packets are ready, running, accepted, merged, rejected, failed, blocked, or stale.
4. Which role/agent/model is active now.
5. Which stage is active now.
6. How long the feature/wave/packet/stage/attempt has been running.
7. Which attempts happened and how long each took.
8. Where artifacts are: logs, evidence, diff, screenshots, test output.
9. Why a packet was accepted, rejected, failed, blocked, retried, switched, returned to architect, or merged.
10. Which tasks are self-improvement and therefore modify GRACE itself.
```

Main user path:

```text
User sees a problem
→ clicks feature or packet
→ sees state, stage, actor, next action, duration, last reason
→ opens Runs / Artifacts / Events / Recovery
→ understands what happened without reading raw logs first
```

Priority:

```text
runs + artifacts + events + durations + stage/actor + recovery + tests
```

Without these, the dashboard is only a pretty shell.

---

## 3. UX principle

Main principle:

```text
Overview first → Detail on click → Deep debug only when needed
```

Meaning:

```text
Main screen: status summary + feature list + selected feature waves/packets + compact live events.
Packet click: current state, current stage, actor, runs, artifacts, events, recovery, spec.
Deep debug: raw JSON, full payloads, full logs, artifact previews.
```

Do not show every worker, every event payload, every ID, every artifact, every shortcut, and raw JSON at the top level.

---

## 4. Stack constraints

Keep current stack:

```text
FastAPI
HTML templates
CSS
vanilla JavaScript
current backend/control plane
Playwright/browser tests
Python unit tests
```

Use WebSocket when available, but keep REST fallback:

```text
/ws for live state/recovery updates
/api/dashboard/v2 for full snapshot
/api/packets/{packet_id} for packet detail
/api/events for filtered history
```

If WebSocket disconnects, UI must visibly show offline/reconnecting and keep a polling fallback.

---

## 5. Identity model: UID vs slug

Canonical IDs are NanoID-style UIDs:

```text
Feature.id = feat_<nanoid>
Wave.id    = wave_<nanoid>
Packet.id  = pkt_<nanoid>
```

Slugs/titles are display/search metadata only:

```text
Feature.slug
Wave.slug
Packet.slug
```

UI links, API calls, buttons, packet detail, event filters, artifact fetches, and recovery calls must use UID values.

Display both in detail views:

```text
Title: Admin UI timers
Slug: admin-ui-timers
UID: feat_AbC123xYz9
```

Do not derive IDs from title/slug/order. Do not parse `W01`, `P01`, or `FEAT-...` from IDs. Use explicit order fields only for display labels.

---

## 6. Information hierarchy

UI hierarchy:

```text
Feature
  → Wave
    → Packet
      → Run / Attempt
        → Artifacts / Evidence / Events
```

Special feature type:

```text
Self-improvement Feature
```

Self-improvement means GRACE modifies itself:

```text
Mission Control UI
runner
orchestrator logic
prompts
acceptance gates
test system
policies
packet execution logic
artifact handling
```

Self-improvement work must be visibly labeled because it is higher-risk than ordinary target-project work.

---

## 7. Desktop layout

Default desktop layout: calm two-column layout plus compact live events.

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ GRACE Mission Control Center      Live · 2 running · 1 failed · 3 workers │
├────────────────────────────────────────────────────────────────────────────┤
│ Status Summary                                                            │
│ [Running 2] [Ready 5] [Needs attention 1] [Merged 12] [Workers 3/1 stale] │
├───────────────────────┬──────────────────────────────────┬────────────────┤
│ Features              │ Selected Feature                 │ Live Events    │
│                       │ Waves / Packets                  │ latest 20      │
└───────────────────────┴──────────────────────────────────┴────────────────┘
```

If the third events panel makes the screen overloaded, it may collapse into a right drawer or bottom panel, but compact live events must remain discoverable and visible enough to show current activity.

Do not use a dense cockpit by default.

---

## 8. Mobile layout

Mobile must not be a squeezed desktop table.

Mobile structure:

```text
Top status summary
Feature cards
Selected feature screen
Packet cards
Packet detail tabs
Events tab
Artifacts tab
Recovery tab
```

Mobile requirements:

```text
No horizontal-only tables for core flow
Packet row/card title remains readable
State/stage/actor visible without opening raw JSON
Last 3 feature events visible on feature screen
Full events available in packet detail Events tab
```

---

## 9. Top bar and status summary

Top bar shows essentials only:

```text
GRACE Mission Control Center
Live / Offline / Reconnecting
Running
Ready
Needs attention
Merged
Workers summary
Last update
```

Example:

```text
GRACE Mission Control Center      Live · 2 running · 1 failed · 3 workers
```

Do not show in top bar:

```text
long IDs
raw timestamps
full worker list
full event list
shortcuts
status legend
raw JSON
```

Status summary cards:

```text
Running: 2
Ready: 5
Needs attention: 1
Merged: 12
Workers: 3 active · 1 stale
Recovery: 1 active
```

`Needs attention` includes:

```text
failed
rejected
blocked
stale worker
stuck running
missing artifacts after finished run
self-improvement packet waiting for reviewer/human approval
active recovery decision
```

---

## 10. Feature list

Feature cards show:

```text
title
slug
packet count
compact status
progress bar
elapsed/duration human time
active roles summary
longest-running packet if any
warning badge if problems
recovery badge if active
self-improvement badge if applicable
```

Example:

```text
GRACE Mission Control Center        Self-improvement
12 packets · 7 merged · 2 running · 1 blocked
Active now: coder 1 · verifier 1
Longest: Add artifact viewer · coder-agent · 15 минут 12 секунд
Recovery: switch coder 3 минуты назад
```

Do not show here:

```text
all packet IDs
raw JSON
full event log
full artifact list
```

---

## 11. Selected feature area

Selected feature shows waves and packets.

Example:

```text
SolarSage Onboarding
UID: feat_AbC123xYz9
Slug: solarsage-onboarding
Elapsed: 18 минут 12 секунд
Recovery: inactive

Wave 1 · Foundation · Идёт 12 минут 30 секунд
✓ Auth migration              merged       duration 4 минуты 10 секунд
▶ Artifacts viewer            running      coder-agent · coder-flash · stage 2 минуты 04 секунды
○ Dashboard polish            ready        waiting 5 минут 11 секунд

Wave 2 · UI
! Mobile layout               failed       T1 failed · duration 7 минут 14 секунд · recovery: retry same coder
○ Timeline                    ready
```

Packets should be compact rows/cards, not huge tiles.

---

## 12. Packet lifecycle, active stage, active role

Separate three concepts:

```text
1. Packet lifecycle state
   READY / CLAIMED / RUNNING / EVIDENCE / REVIEW / ACCEPTED / MERGING / MERGED / REJECTED / BLOCKED / FAILED / CANCELLED

2. Active stage
   architect_plan / coder_agent / deterministic_acceptance / evidence_verifier / reviewer / merge / retry / blocked_waiting_user / etc.

3. Active actor/role
   architect / coder / deterministic_acceptance / evidence_verifier / reviewer / merge_worker / recovery_controller / system / user
```

Do not collapse all of this into only `state=running`.

Readable examples:

```text
Running · coder-agent · coder-flash · 6 минут 12 секунд
Evidence · evidence-verifier · verifier-flash · 1 минута 04 секунды
Accepted · waiting for merge · 12 секунд
Rejected · deterministic T1 failed · recovery: retry same coder
```

---

## 13. Canonical display states

Use existing DB states if already present. UI/API may normalize display labels without forcing migrations.

Canonical display labels:

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

If code does not have separate `REVIEW` or `MERGING` packet states, render based on state + active_stage:

```text
state=running + active_stage=reviewer → Review
state=accepted + active_stage=merge_apply → Merging / waiting merge
```

---

## 14. Active stage values

Expose `active_stage` on dashboard, packet detail, run/attempt, and event responses where possible.

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

## 15. Active role / actor values

Expose `active_role` or `active_actor`.

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

Also expose executor/model/provider when available:

```json
{
  "active_role": "coder",
  "active_executor_id": "coder-flash",
  "active_model": "deepseek-chat",
  "active_provider": "openrouter"
}
```

For deterministic/internal stages:

```json
{
  "active_role": "deterministic_acceptance",
  "active_executor_id": "internal",
  "active_model": null,
  "active_provider": null
}
```

Do not fake model/provider. Use null when unknown.

---

## 16. Next action

Expose human-readable `next_action` for packet rows and detail views.

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

This is not a command. It is a UI explanation.

---

## 17. Duration and live timer requirements

The UI must answer:

```text
How long has this feature been running?
How long has this wave been running?
How long has this packet been running?
How long has this current stage been running?
How long did each attempt take, including failed attempts?
Where exactly is time being spent?
```

The UI must show:

```text
1. live elapsed timers for active feature/wave/packet/stage
2. final durations for terminal feature/wave/packet/stage/attempt
3. per-attempt duration for every run, including failed/rejected attempts
4. queued/waiting time where useful
```

Examples:

```text
Feature: Идёт 12 минут 08 секунд
Wave 1: Идёт 07 минут 22 секунды
Packet: Идёт 03 минуты 10 секунд
Stage: coder-agent · 02 минуты 04 секунды
Attempt #1 — failed — 7 минут 14 секунд
Attempt #2 — failed — 6 минут 59 секунд
Attempt #3 — accepted — 8 минут 03 секунды
```

Failed attempts must never disappear after retry.

---

## 18. Human-readable duration helper

Add or reuse shared duration formatting helper.

Preferred backend file:

```text
src/grace_control/ui/time_format.py
```

Required function:

```python
def format_duration(seconds: int | float | None) -> str:
    ...
```

Rules:

```text
None / negative / invalid → "—"
0..59 seconds → "12 секунд"
60..3599 seconds → "26 минут 30 секунд"
3600..86399 seconds → "1 час 12 минут 05 секунд"
>= 86400 seconds → "1 день 03 часа 20 минут 10 секунд"
```

Preferred Russian pluralization:

```text
1 секунда, 2 секунды, 5 секунд
1 минута, 2 минуты, 5 минут
1 час, 2 часа, 5 часов
1 день, 2 дня, 5 дней
```

If full pluralization is too expensive for MVP, use one consistent short format everywhere:

```text
1ч 12м 05с
26м 30с
```

Do not show raw seconds as primary UI text.

---

## 19. Timestamp and duration semantics

Audit existing schema first. Reuse existing timestamp fields when present.

Required logical timestamps:

```text
Feature: created_at, started_at, finished_at, updated_at
Wave: created_at, started_at, finished_at, updated_at
Packet: created_at, started_at, finished_at, updated_at
PacketRun/Attempt: created_at, started_at, finished_at, attempt_number/run_number, status
Stage history: stage, role, started_at, finished_at, duration
```

If exact fields already exist under different names, do not duplicate. Add computed API fields instead.

Duration rules:

```text
completed duration = finished_at - started_at
live elapsed = now - started_at when active and no finished_at
waiting duration = now - created_at when not started
attempt duration = per PacketRun started_at/finished_at/duration_ms
stage duration = stage finished_at - stage started_at, or now - stage_started_at if active
```

Do not reset packet `started_at` on retry unless creating a new attempt record. Do not overwrite old attempt durations.

---

## 20. Stage history / timeline

Packet detail must show stage history, not only final state.

For each run/attempt, expose or derive:

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

If a full stage-history table does not exist yet, derive MVP history from events and PacketRun `result_json`. New runs should record explicit stage transition events.

---

## 21. Packet row requirements

Compact packet row/card must show enough status without opening detail.

Required fields:

```text
status icon/text
short title
lifecycle state
active stage
active role/actor
executor/model if available
attempt count
stage elapsed
packet elapsed/duration
last reason if failed/rejected/blocked
artifact count
recovery hint if active
self-improvement badge if applicable
```

Example rows:

```text
▶ Add artifact viewer   Running · coder-agent · coder-flash   stage 6м 12с · packet 15м 12с   attempt 2/3   artifacts: 3
◐ Evidence checks       Evidence · verifier · verifier-flash  stage 1м 04с · packet 18м 33с   attempt 1/3   artifacts: 5
◆ Reviewer gate         Review · reviewer · codex-5.2         stage 2м 15с · packet 21м 10с   attempt 1/3   artifacts: 7
✓ Merge API hardening   Merged                                duration 9м 40с                attempts 1/3   artifacts: 9
! Mobile layout         Rejected · T1 failed                  duration 7м 14с                recovery: retry same coder
⛔ Git merge             Blocked · dirty target repo           after 12с                      attempts 1/3
```

Do not render only:

```text
running
```

---

## 22. Packet detail

Clicking a packet opens detail as route, drawer, or modal. It must be usable on desktop and mobile.

Required sections/tabs:

```text
Overview
Runs / Attempts
Artifacts / Evidence
Events
Recovery / Stability
Spec
Raw JSON
```

Overview shows:

```text
title
UID / slug
lifecycle state
active stage
active role
executor/model/provider
next_action
elapsed/duration
attempt count
last reason
recovery summary
artifact count
latest 5 packet events
```

Runs / Attempts shows every run, not only the latest:

```text
Attempt #1 — failed — coder-flash — 7 минут 14 секунд
Attempt #2 — failed — coder-flash — 6 минут 59 секунд
Attempt #3 — running — coder-strong — stage coder-agent 2 минуты 01 секунда
```

Artifacts / Evidence shows:

```text
artifact type
path/name
run/attempt
created_at if known
preview/open action
copy path action
missing artifact warning if expected but absent
```

---

## 23. Always-visible event stream

Mission Control must include a compact live event stream.

Desktop behavior:

```text
Compact Live Events panel shows latest 20 events for selected feature.
Packet detail Overview shows latest 5 packet events.
Events tab shows full filtered event list.
```

Mobile behavior:

```text
Feature screen shows latest 3 feature events.
Packet detail has Events tab.
```

The events panel must not overwhelm the main dashboard, but the user must see live activity without opening raw logs.

---

## 24. Event types

Normalize or emit event types for all major stages.

Architect/context:

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

Worker/coder:

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

Deterministic acceptance:

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

Evidence verifier:

```text
evidence_verifier_started
evidence_verifier_completed
evidence_verifier_failed
evidence_verifier_rework_to_coder
evidence_verifier_return_to_architect
```

Reviewer:

```text
reviewer_started
reviewer_completed
reviewer_failed
reviewer_accepted
reviewer_rework_to_coder
reviewer_return_to_architect
reviewer_blocked
```

Merge:

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

Stage tracking:

```text
stage_started
stage_finished
stage_failed
```

Recovery/stability:

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
recovery_update
```

---

## 25. Event payload requirements

Events must be DB-backed, not only logs.

Each major event should include as much context as known:

```json
{
  "feature_id": "feat_...",
  "feature_slug": "...",
  "wave_id": "wave_...",
  "packet_id": "pkt_...",
  "run_id": "run_...",
  "attempt_number": 2,
  "role": "coder",
  "executor_id": "coder-flash",
  "model": "deepseek-chat",
  "provider": "openrouter",
  "stage": "coder_agent",
  "status": "started",
  "summary": "Coder agent started",
  "trace_id": "...",
  "payload": {}
}
```

If model/provider are unknown, use null. Do not fake them.

For deterministic stages:

```text
role = deterministic_acceptance
executor_id = internal
model = null
provider = null
```

---

## 26. Event display

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
12:08:43  Recovery    switch_coder          coder-flash → coder-strong
```

Do not display only raw event names.

---

## 27. Event severity and filters

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

Color may help, but text labels must always be present.

Events tab filters:

```text
All
Lifecycle
Agents
Acceptance
Verifier
Reviewer
Merge
Recovery
Errors
```

Current `/api/events` already supports `entity_type`, `entity_id`, `event_type`, and `recovery_*` prefix filtering. Extend it if needed, do not replace it blindly.

Preferred additional filters:

```text
feature_id
wave_id
packet_id
run_id
stage
role
severity
limit
```

---

## 28. Recovery / Stability UI

Mission Control must show feature-stability state, not only packet state.

Current code already has RecoveryController and recovery API endpoints. UI should surface them clearly.

Feature summary should show:

```text
Recovery: active / inactive
Retries: 2 coder, 0 verifier, 0 reviewer, 1 merge
Last recovery: switched coder 3 минуты назад
Blocked: no / yes
```

Packet row should show recovery hint if active:

```text
! Tests failed · recovery: retry same coder
! Tests failed twice · recovery: switch coder
⤴ Scope impossible · returning to architect
⛔ Dirty target repo · true blocker
```

Packet detail Recovery / Stability block:

```text
Recovery / Stability
Failure class: retryable_coder
Decision: switch coder
Reason: T1 failed twice
Previous executor: coder-flash
Next executor: coder-strong
Attempt: 3/4
Decision ID: rec_...
```

If no recovery decision:

```text
Recovery: inactive
```

---

## 29. Recovery API contract

Keep existing endpoints:

```text
POST /api/recovery/evaluate/{packet_id}
GET /api/recovery/packets/{packet_id}
GET /api/recovery/features/{feature_id}
```

Dashboard/packet responses should include recovery summary:

```json
{
  "recovery": {
    "active": true,
    "failure_class": "retryable_coder",
    "action": "switch_coder",
    "reason": "T1 failed twice",
    "current_executor_id": "coder-flash",
    "next_executor_hint": "coder-strong",
    "decision_id": "..."
  }
}
```

When `action=switch_coder`, current code may store next executor under:

```text
spec_json.recovery.requested_executor_id
```

Do not hardcode executor IDs outside configured executor/profile selection.

---

## 30. Dashboard API additions

Update `/api/dashboard/v2` feature/wave/packet objects without removing existing fields.

Feature-level recommended fields:

```json
{
  "id": "feat_...",
  "slug": "...",
  "title": "...",
  "status": "running",
  "state_label": "Running",
  "packet_counts": {},
  "active_roles": {},
  "longest_running_packet": {},
  "recent_events": [],
  "recovery_summary": {},
  "elapsed_seconds": 123,
  "elapsed_human": "2 минуты 03 секунды"
}
```

Packet-level recommended fields:

```json
{
  "id": "pkt_...",
  "title": "...",
  "state": "running",
  "state_label": "Running",
  "active_stage": "coder_agent",
  "active_stage_label": "Coder agent",
  "active_role": "coder",
  "active_role_label": "Coder",
  "active_executor_id": "coder-flash",
  "active_model": "deepseek-chat",
  "active_provider": "openrouter",
  "active_stage_started_at": "...",
  "active_stage_elapsed_seconds": 372,
  "active_stage_elapsed_human": "6 минут 12 секунд",
  "packet_elapsed_seconds": 912,
  "packet_elapsed_human": "15 минут 12 секунд",
  "next_action": "coder is editing files in worktree",
  "last_reason": null,
  "artifact_count": 3,
  "recovery": null
}
```

---

## 31. Packet detail API additions

Update `/api/packets/{packet_id}` without removing existing fields.

Recommended shape:

```json
{
  "packet": {
    "id": "pkt_...",
    "state": "running",
    "active_stage": "coder_agent",
    "active_role": "coder",
    "active_executor_id": "coder-flash",
    "active_stage_elapsed_human": "6 минут 12 секунд",
    "next_action": "coder is editing files in worktree",
    "recovery": null
  },
  "runs": [
    {
      "attempt_number": 2,
      "status": "running",
      "active_stage": "coder_agent",
      "active_role": "coder",
      "duration_human": "—",
      "stage_history": []
    }
  ],
  "artifacts": [],
  "events": [],
  "recovery": null
}
```

---

## 32. WebSocket behavior

Keep existing `/ws` endpoint and `broadcast_event()` mechanism.

WebSocket messages should include enough data for the dashboard to update compact state:

```json
{
  "type": "state_change",
  "packet_id": "pkt_...",
  "state": "running",
  "active_stage": "coder_agent",
  "active_role": "coder",
  "worker_id": "worker-a13f"
}
```

Recovery update example:

```json
{
  "type": "recovery_update",
  "packet_id": "pkt_...",
  "action": "switch_coder",
  "reason": "T1 failed twice"
}
```

When WebSocket disconnects:

```text
show Reconnecting / Offline indicator
retry connection
continue periodic REST snapshot refresh
never leave stale Live indicator active
```

---

## 33. Stuck detection

Add UI warnings for suspicious long-running stages.

Thresholds should be constants or config:

```text
coder_agent > 20 min → warn
acceptance > 5 min → warn
verifier > 10 min → warn
reviewer > 15 min → warn
merge > 2 min → warn
claimed > 2 min without running → warn
```

Examples:

```text
⚠ coder-agent running 28 минут — possibly stuck
⚠ claimed 4 минуты — worker may be stale
```

This TZ only displays warnings. It must not auto-cancel, auto-merge, or bypass recovery policy.

---

## 34. Artifact requirements

The dashboard already has packet artifact/evidence modal behavior. Extend it into a clearer packet detail section.

Artifact display must show:

```text
run/attempt
artifact type
filename/path
summary if available
created_at if available
open/preview action
copy path action
missing expected artifact warning
```

Common artifact categories:

```text
logs
evidence
diff
screenshots
test output
review report
acceptance report
raw result_json
```

If artifact content is too large, show metadata and provide explicit open/download/preview action.

---

## 35. JavaScript/template safety tests

We had real regressions where JavaScript/template mistakes were visible only after opening the admin UI. This TZ must include tests that catch those earlier.

Required tests:

```text
template renders without syntax-breaking quotes
inline JavaScript parses successfully
Dashboard page loads in browser test
Dashboard can render empty data
Dashboard can render demo data with ready/running/accepted/merged/rejected/failed/blocked
Packet click opens detail/modal/drawer
WebSocket disconnect does not crash UI
REST fallback still works
Event filters do not throw JS errors
Recovery block renders active and inactive states
Mobile viewport smoke test
```

Preferred test levels:

```text
Python unit tests for API shaping/formatters
JS syntax smoke test for dashboard template
Playwright test for actual browser rendering
```

Do not rely only on backend unit tests for UI work.

---

## 36. Demo/fixture data for UI tests

Tests should include representative packets:

```text
ready packet
running coder packet
running verifier packet
running reviewer packet
accepted waiting merge packet
merged packet
rejected T1 failed packet
blocked safety packet
packet with recovery switch coder
self-improvement packet
packet with artifacts
packet with missing expected artifact
```

This is needed so the UI does not only work for the happy path.

---

## 37. Acceptance checklist

Implementation is done only when this checklist is true:

```text
One canonical TZ-019 file exists
Old tz-019b and tz-019c addendum files are removed
Dashboard visible title says GRACE Mission Control Center
Existing Dashboard v2 WebSocket behavior still works
REST fallback still works
Feature → Wave → Packet hierarchy visible or prepared in /api/dashboard/v2
Packet rows show state + active stage + active role, not just state
Packet rows show duration/elapsed information
Packet detail shows runs/attempts and failed attempts remain visible
Packet detail shows artifacts/evidence
Packet detail shows events
Packet detail shows recovery/stability block
Live Events panel or compact event area is visible
Recovery events render as human text, not only raw event names
Self-improvement work is visibly labeled
Stuck warnings are display-only
No orchestration/acceptance/merge safety semantics are changed
JS syntax/template smoke tests exist
Playwright/browser smoke test exists
Mobile viewport smoke test exists
Existing tests still pass
```

---

## 38. Report format for coder

When implementing this TZ, report:

```text
Summary
Files changed
Existing code reused
API fields added
UI sections added
Events rendered
Recovery rendered
Duration/timer behavior
JS syntax tests added: yes/no
Playwright tests added: yes/no
Tests run
Remaining blockers
```

---

## 39. Notes for future TZs

Future improvements should be separate TZs if they change behavior rather than observability:

```text
interactive retry/recover buttons
manual approve/reject actions
real session resume beyond stubs
worker control actions
policy editing UI
self-improvement approval workflow
```

This file is the observability/admin UI specification, not a new control-plane behavior policy.
