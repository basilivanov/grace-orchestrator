# TZ 019 — GRACE Mission Control Center: admin UI, observability, artifacts, durations, self-improvement

Audience: Flash coder / literal executor.

Goal: build a calm, readable, operational admin UI for `grace-orchestrator` that shows what is happening with features, waves, packets, runs/attempts, artifacts, evidence, events, durations, live timers, and self-improvement work.

Interface name:

```text
GRACE Mission Control Center
```

This task is about admin UI/data/API/test foundation. It must not change orchestration semantics, retry policy, acceptance pipeline, merge behavior, or safety gates.

---

## 0. Product intent

The user must quickly understand:

```text
1. What is running now.
2. Where problems are.
3. Which packets are ready, running, failed/rejected, accepted, or merged.
4. Which attempts happened and how long every attempt took.
5. Where artifacts are: logs, evidence, diff, screenshots, test output.
6. Why a packet was accepted, rejected, failed, blocked, or stuck.
7. Which tasks are self-improvement and therefore modify GRACE itself.
8. How long the feature/wave/packet has already been running.
```

Main user scenario:

```text
User sees a problem
→ clicks packet
→ sees current state and reason
→ opens Runs/Artifacts
→ understands what happened
```

Priority:

```text
runs + artifacts + events + durations + tests
```

Without these, UI becomes a pretty empty shell.

---

## 1. Stack constraints

Keep current stack:

```text
FastAPI
HTML/templates
CSS
vanilla JavaScript
current backend/control plane
Playwright for browser tests
```

Do not add:

```text
React
Vue
Svelte
separate frontend build stack
new workflow engine
heavy dashboard library
websockets-only architecture without polling fallback
```

Use WebSocket if already available, but keep polling fallback.

---

## 2. Core UX principle

The UI must not be overloaded.

Main principle:

```text
Overview first → Detail on click → Deep debug only when needed
```

Meaning:

```text
Main screen: summary + feature list + selected feature packets.
Packet click: detailed state, runs, artifacts, events, spec.
Deep debug: raw JSON, full event payloads, full logs, artifact previews.
```

Do not build a dense cockpit that shows workers, events, artifacts, counters, shortcuts, legends, raw JSON, and logs all at once.

---

## 3. Identity model: UID vs slug

The control plane uses NanoID-style UIDs as canonical IDs:

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

UI links/actions/API calls must use UID values.

Display both in detail views:

```text
Title: Admin UI timers
Slug: admin-ui-timers
UID: feat_AbC123xYz9
```

Do not derive IDs from title/slug/order.
Do not parse `W01`, `P01`, or `FEAT-...` from IDs.
Use wave/packet order fields for display labels like `W01` and `P01`.

---

## 4. Information model

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

---

## 5. Desktop layout

Default desktop layout: calm 2-column layout.

```text
┌──────────────────────────────────────────────────────────────┐
│ GRACE Mission Control Center      Live · 2 running · 1 failed │
├──────────────────────────────────────────────────────────────┤
│ Status Summary                                                │
│ [Running 2] [Ready 5] [Needs attention 1] [Merged 12]         │
├───────────────────────┬──────────────────────────────────────┤
│ Features              │ Selected Feature                     │
│                       │ Waves / Packets                      │
└───────────────────────┴──────────────────────────────────────┘
```

A third diagnostics column is allowed only as advanced mode/drawer, not default.

---

## 6. Top bar

Top bar shows only essentials:

```text
GRACE Mission Control Center
Live / Offline
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

---

## 7. Status Summary

Show compact summary cards:

```text
Running: 2
Ready: 5
Needs attention: 1
Merged: 12
Workers: 3 active · 1 stale
```

Goal: user understands in 3 seconds whether system is healthy.

`Needs attention` includes:

```text
failed
rejected
blocked
stale worker
stuck running
missing artifacts after finished run
self-improvement packet waiting for reviewer/human approval
```

---

## 8. Duration and live timer requirements

The admin UI must clearly show time spent.

Required questions:

```text
How long has this feature been running?
How long has this wave been running?
How long has this packet been running?
How long did each attempt take, including failed attempts?
Where exactly is time being spent?
```

The UI must show:

```text
1. live elapsed timers for active feature/wave/packet
2. final durations for terminal feature/wave/packet
3. per-attempt duration for every run, including failed/rejected attempts
4. queued/waiting time where useful
```

Examples:

```text
Feature: Идёт 12 минут 08 секунд
Wave 1: Идёт 07 минут 22 секунды
Packet: Идёт 03 минуты 10 секунд
Attempt #1 — failed — 7 минут 14 секунд
Attempt #2 — failed — 6 минут 59 секунд
Attempt #3 — accepted — 8 минут 03 секунды
```

Failed attempts must never disappear after retry.

---

## 9. Human-readable duration format

Add shared duration formatting helper.

Suggested backend file:

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

Do not show raw seconds as the primary display.

---

## 10. Timestamp and duration data model

Audit existing schema first. Reuse existing timestamp fields if present.

Required logical timestamps:

```text
Feature: created_at, started_at, finished_at, updated_at
Wave: created_at, started_at, finished_at, updated_at
Packet: created_at, started_at, finished_at, updated_at
PacketRun/Attempt: created_at, started_at, finished_at, attempt_number, status
```

If exact fields already exist under different names, do not duplicate. Add computed API fields instead.

If started/finished fields are missing, add minimal safe fields:

```text
started_at set when entity enters active/running lifecycle
finished_at set when entity reaches terminal state
```

Terminal states include:

```text
merged
rejected
blocked
cancelled
completed
failed
```

Do not alter state machine semantics.

---

## 11. Duration semantics

Completed duration:

```text
if started_at and finished_at:
  duration_seconds = finished_at - started_at
  display: Длилось: 26 минут 30 секунд
```

Live elapsed duration:

```text
if started_at and no finished_at and active:
  elapsed_seconds = now - started_at
  display: Идёт: 07 минут 12 секунд
```

Queued/waiting duration:

```text
if created_at and no started_at:
  waiting_seconds = now - created_at
  display: Ожидает: 03 минуты 04 секунды
```

Attempt duration:

```text
attempt started_at/finished_at = per-attempt runtime
packet started_at/finished_at = whole packet lifecycle runtime
wave started_at/finished_at = aggregate wave lifecycle runtime
feature started_at/finished_at = aggregate feature lifecycle runtime
```

Do not reset packet `started_at` on retry unless this is a new attempt record.
Do not overwrite old attempt durations.

---

## 12. Left column: Features

Feature list example:

```text
SolarSage Onboarding
14 packets
1 running · 1 failed · elapsed 18 минут 12 секунд

DeepCalm Avito
8 packets
all ok · duration 42 минуты 10 секунд

GRACE Self-Improvement       Self-improvement
3 packets
waiting for review
```

For each feature show:

```text
title
packets count
compact status
progress bar
elapsed/duration human time
warning badge if problems
Self-improvement badge if applicable
```

Do not show here:

```text
all packet IDs
raw JSON
full event log
artifacts list
```

---

## 13. Selected Feature area

Selected feature shows waves/packets.

Example:

```text
SolarSage Onboarding
UID: feat_AbC123xYz9
Slug: solarsage-onboarding
Elapsed: 18 минут 12 секунд

Wave 1 · Foundation · Идёт 12 минут 30 секунд
✓ Auth migration              merged      duration 4 минуты 10 секунд
▶ Artifacts viewer            running     elapsed 2 минуты 04 секунды
○ Dashboard polish            ready       waiting 5 минут 11 секунд

Wave 2 · UI
! Mobile layout               failed      duration 7 минут 14 секунд
○ Timeline                    ready
```

Packets should be compact rows/cards, not large tiles.

For each packet row show:

```text
short title
state
attempt count
elapsed/duration
last reason if failed/rejected
artifact count indicator
self-improvement badge if applicable
```

Example:

```text
▶ Artifacts viewer     running     attempt 2/3     elapsed 2 минуты 04 секунды     artifacts: 6
! Mobile layout        failed      tests failed     duration 7 минут 14 секунд     artifacts: 4
```

---

## 14. Packet Detail opening

Packet detail opens only after clicking a packet.

Desktop:

```text
right drawer or full-width detail panel below board
```

Mobile:

```text
separate drill-down screen
```

Packet detail header example:

```text
Packet: Artifacts viewer
UID: pkt_XyZ123AbC9
Slug: artifacts-viewer
State: RUNNING
Attempt: 2/3
Worker: worker-a13f
Elapsed: 2 минуты 04 секунды
Next: waiting for worker release
```

Tabs:

```text
Overview | Runs | Artifacts | Events | Spec
```

---

## 15. Packet Detail: Overview

Overview shows only the most important things:

```text
goal
current state
next action
last run result
failure/rejection reason
acceptance profile
worker/executor
started/finished time
elapsed/duration
artifact count
```

Example:

```text
Goal:
Show logs, diffs and test output for each run.

Current:
Running, waiting for worker release.

Timing:
Started 20:11:02
Elapsed 2 минуты 04 секунды

Last run:
Rejected, tests failed after 7 минут 14 секунд.

Artifacts:
6 files available.
```

---

## 16. Packet Detail: Timeline

Timeline shows packet lifecycle.

Successful scenario:

```text
Ready → Claimed → Running → Evidence → Accepted → Merged
```

Rejected/retry scenario:

```text
Ready → Running → Rejected after 7 минут 14 секунд → Retry Ready
```

Failed terminal:

```text
Ready → Running → Failed after 3 минуты 20 секунд
```

Timeline should be simple, text-first, and readable. Do not make complex graphs.

---

## 17. Packet Detail: Runs / Attempts

Runs tab shows every attempt, including failed attempts.

Columns:

```text
Attempt
Status
Executor/model
Started
Finished
Duration
Summary/reason
Artifacts
Report link
```

Example:

```text
#1  failed    coder-flash       20:11:02 → 20:18:16   7 минут 14 секунд   T1 failed        artifacts: 6
#2  failed    coder-flash       20:19:05 → 20:26:04   6 минут 59 секунд   no_changes       artifacts: 4
#3  accepted  coder-agy-sonnet  20:27:10 → 20:35:13   8 минут 03 секунды acceptance passed artifacts: 8
```

No attempt row should disappear after retry.

---

## 18. Packet Detail: Artifacts

Artifacts are not shown on the main screen, only artifact count indicator.

Artifacts tab groups:

```text
Logs
- stdout.log
- stderr.log

Evidence
- evidence.json

Diff
- diff.patch

Images
- screenshot.png
```

For each artifact show:

```text
name
type
size
preview button
download button
copy path button
```

Preview rules:

```text
text/log: tail by default + show full
JSON: pretty print
image: thumbnail + open preview
patch/diff: monospace view
```

---

## 19. Packet Detail: Events

Main screen must not show full event log.

Overview may show last 3 events:

```text
12:01 Execution started
12:03 Tests failed after 2 минуты 10 секунд
12:04 Retry scheduled
```

Full Events tab shows:

```text
timestamp
event type
human-readable message
collapsed payload
trace_id with copy button
```

Filters:

```text
lifecycle
worker
errors
merge
notifications
```

---

## 20. Packet Detail: Spec

Spec tab shows readable `spec_json`:

```text
title
scope
acceptance criteria
expected changes
non-goals
risk/complexity
raw JSON/YAML collapsed
```

Raw JSON is collapsed by default.

---

## 21. Self-improvement support

Self-improvement packets must be visibly different from product packets.

Feature list:

```text
GRACE Self-Improvement        Self-improvement
3 packets
1 running · 1 waiting approval
```

Packet row:

```text
! Fix artifact run id     self-improvement     waiting reviewer     elapsed 5 минут 10 секунд
```

Detail safety banner:

```text
Self-improvement packet: changes GRACE itself.
Do not auto-merge without required gates.
```

Detail fields:

```text
affected subsystem
risk level
required gates
reviewer status
human approval status
rollback note
artifacts/evidence
```

Example:

```text
Affected subsystem: Mission Control UI
Risk: Medium
Required gates: JS syntax, backend tests, Playwright smoke, reviewer
Rollback: revert packet branch
```

Checklist:

```text
Required gates
✓ JS syntax check
✓ Backend tests
✓ API contract tests
✓ Playwright smoke
✓ Mobile viewport test
○ Reviewer approval
○ Human approval
```

Acceptance:

```text
self-improvement feature visible in feature list
self-improvement packet has badge
safety banner visible in detail
affected subsystem visible
required gates checklist visible
passed/missing gates visible
self-improvement packets cannot be confused with product packets
```

---

## 22. Mobile layout

Do not try to fit desktop dashboard onto mobile.

Use drill-down:

```text
Screen 1: Features
Screen 2: Waves / Packets
Screen 3: Packet Detail
Screen 4: Artifacts / Logs
```

Requirements:

```text
390px without horizontal scroll
430px without horizontal scroll
sticky top bar
back button
breadcrumb
large packet rows
bottom tabs only in packet detail
artifacts/logs on separate screen
minimum counters
IDs shortened in summary, full UID via tap/copy
live timers visible but compact
```

---

## 23. API: dashboard endpoint

Add:

```text
GET /api/dashboard/v2
```

Response shape:

```json
{
  "system": {
    "health": "ok",
    "live": true,
    "last_event_at": "...",
    "active_workers": 1,
    "stale_workers": 0
  },
  "stats": {
    "features": 3,
    "waves": 7,
    "packets_total": 24,
    "ready": 5,
    "running": 2,
    "accepted": 1,
    "merged": 12,
    "rejected": 1,
    "failed": 1,
    "needs_attention": 2
  },
  "features": []
}
```

Feature/wave/packet objects should include computed timing fields where applicable:

```json
{
  "id": "feat_...",
  "slug": "admin-ui-timers",
  "title": "Admin UI timers",
  "state": "running",
  "created_at": "...",
  "started_at": "...",
  "finished_at": null,
  "duration_seconds": null,
  "elapsed_seconds": 422,
  "duration_human": null,
  "elapsed_human": "7 минут 02 секунды"
}
```

For terminal states:

```json
{
  "duration_seconds": 1590,
  "duration_human": "26 минут 30 секунд",
  "elapsed_seconds": null,
  "elapsed_human": null
}
```

Keep old `/api/dashboard` if needed, but new UI should use `/api/dashboard/v2`.

---

## 24. API: packet detail endpoint

Add/extend:

```text
GET /api/packets/{packet_id}
```

Response includes:

```json
{
  "packet": {},
  "feature": {},
  "wave": {},
  "runs": [],
  "events": [],
  "artifacts": [],
  "next_action": "waiting_for_worker",
  "self_improvement": {
    "enabled": false,
    "affected_subsystem": null,
    "risk_level": null,
    "required_gates": [],
    "rollback_note": null
  }
}
```

For runs/attempts include timing fields:

```json
{
  "attempt_number": 1,
  "status": "failed",
  "started_at": "...",
  "finished_at": "...",
  "duration_seconds": 434,
  "duration_human": "7 минут 14 секунд",
  "executor_id": "coder-flash",
  "summary": "scope guard failed"
}
```

For regular packets:

```json
"self_improvement": {"enabled": false}
```

---

## 25. API: artifact endpoints

Add/fix:

```text
GET /api/packets/{packet_id}/runs/{run_id}/artifacts
GET /api/packets/{packet_id}/runs/{run_id}/artifacts/file?path=...
```

Requirements:

```text
run_id works as R01 and full packet_id-R01, or choose one canonical format and document it
frontend/backend use one canonical format
endpoint must not double-prefix run ID
if run not found → clear error
UI shows "Run not found", not "No artifacts"
```

Regression must catch bug shape:

```text
packet_id-packet_id-R01
```

---

## 26. Frontend structure

Keep vanilla JS.

Suggested files:

```text
src/grace_control/ui/static/
  dashboard.js
  api.js
  state.js
  render_features.js
  render_packets.js
  render_packet_detail.js
  render_artifacts.js
  mobile_nav.js
  timers.js
  dashboard.css
```

If no JS build exists, one physical JS file is acceptable, but it must be clearly structured by sections.

---

## 27. Live timer implementation

Use client-side timers with data attributes.

Rendered HTML example:

```html
<span class="live-duration" data-started-at="2026-06-03T18:10:12Z" data-finished-at="">
  7 минут 02 секунды
</span>
```

JS behavior:

```text
Every 1 second:
  find .live-duration elements
  if data-finished-at exists: keep final duration
  else compute now - started_at
  update text using the same visible formatting rules
```

Server and JS formatter must use the same visible format.

If full Russian pluralization in JS is too much, use the same short unit format on both backend and frontend.

---

## 28. Auto-refresh

Requirements:

```text
WebSocket updates dashboard state if available
polling fallback remains
refresh does not reset selected feature
refresh does not reset selected packet
refresh does not reset selected tab
offline websocket shows "Offline, retrying"
live timers continue updating between data refreshes
```

MVP options:

```text
Option A: page/section auto-refresh every 10 seconds
Option B: HTMX-like partial refresh every 5–10 seconds if existing pattern exists
Option C: fetch JSON endpoint every 5 seconds
```

Choose the smallest existing pattern.

Do not introduce React.
Do not overbuild websockets.

---

## 29. Empty/error states

Required states:

```text
no features
no packets
no runs
no artifacts
API error
WebSocket offline
worker stale
run not found
artifact file missing
self-improvement gates missing
missing timing fields
invalid timestamp
```

Show human-readable message instead of white screen/raw exception.

---

## 30. Visual style

Style:

```text
Calm, sparse, readable, operational.
```

Requirements:

```text
fewer colors
more whitespace
max 4 summary cards on first screen
compact packet rows
status badges with text
IDs small monospace only in detail
logs monospace only
raw JSON collapsed
important info not only in tooltip
color not the only signal
human-readable durations, not raw seconds
```

Do not build:

```text
Dense cockpit, many widgets, many colors, everything everywhere.
```

---

## 31. Static JavaScript syntax tests

Check all JS files:

```bash
node --check src/grace_control/ui/static/dashboard.js
node --check src/grace_control/ui/static/api.js
node --check src/grace_control/ui/static/state.js
node --check src/grace_control/ui/static/render_features.js
node --check src/grace_control/ui/static/render_packets.js
node --check src/grace_control/ui/static/render_packet_detail.js
node --check src/grace_control/ui/static/render_artifacts.js
node --check src/grace_control/ui/static/mobile_nav.js
node --check src/grace_control/ui/static/timers.js
```

If only one JS file exists, check that file.

Acceptance:

```text
CI fails on unclosed quote
CI fails on broken template literal
CI fails on invalid JS syntax
```

---

## 32. HTML/template smoke tests

Backend smoke test:

```text
GET /
GET /static/dashboard.js
GET /static/dashboard.css
GET /api/dashboard/v2
```

Acceptance:

```text
/ returns 200
HTML contains GRACE Mission Control Center
JS/CSS connected
JS/CSS return 200
/api/dashboard/v2 returns valid JSON
```

---

## 33. API contract tests

Cover:

```text
GET /api/dashboard/v2
GET /api/packets/{packet_id}
GET /api/packets/{packet_id}/runs/{run_id}/artifacts
GET /api/packets/{packet_id}/runs/{run_id}/artifacts/file?path=...
```

Dashboard required fields:

```json
{
  "system": {},
  "stats": {},
  "features": []
}
```

Packet detail required fields:

```json
{
  "packet": {},
  "runs": [],
  "events": [],
  "artifacts": [],
  "next_action": ""
}
```

Self-improvement packet required fields:

```json
{
  "self_improvement": {
    "enabled": true,
    "affected_subsystem": "",
    "risk_level": "",
    "required_gates": []
  }
}
```

Timing contract fields:

```text
elapsed_seconds / elapsed_human for active entities
duration_seconds / duration_human for terminal entities
run duration_human for every attempt
```

---

## 34. Artifact regression tests

Check both variants if compatibility is required:

```text
run_id = R01
run_id = packet_id-R01
```

Acceptance:

```text
artifacts found correctly
endpoint does not double-prefix
run not found returns clear error
UI shows Run not found, not No artifacts
regression fails for packet_id-packet_id-R01
```

---

## 35. Duration/timer tests

Create/update:

```text
tests/grace_control/ui/test_time_format.py
tests/api/test_admin_duration_fields.py
tests/ui/test_admin_duration_rendering.py
```

Required tests:

```text
test_format_duration_59_seconds
test_format_duration_26_minutes_30_seconds
test_format_duration_1_hour_2_minutes_3_seconds
test_format_duration_days_hours_minutes_seconds
test_format_duration_invalid_returns_dash
test_compute_completed_duration
test_compute_live_elapsed_duration
test_compute_waiting_duration
test_feature_running_has_elapsed_human
test_feature_completed_has_duration_human
test_wave_running_has_elapsed_human
test_packet_running_has_elapsed_human
test_failed_attempt_keeps_duration_human
test_attempts_table_includes_failed_attempts
test_admin_links_use_uid_not_slug
test_wave_display_order_not_parsed_from_uid
test_packet_display_order_not_parsed_from_uid
```

Use fixed fake `now`, not real clock.

---

## 36. Playwright tests

Playwright is mandatory acceptance gate.

### Test 1 — dashboard opens

```text
Open /
Check GRACE Mission Control Center title
Fail on pageerror
Fail on console.error
```

### Test 2 — overview renders

With seed/demo data:

```text
Status Summary visible
Feature list visible
Selected Feature visible
Wave list visible
Packet rows visible
feature/wave/packet timers visible
```

### Test 3 — packet detail opens

```text
Click packet
Check Packet Detail
Check Overview tab
Check Runs tab
Check Artifacts tab
Check Events tab
Check Spec tab
```

### Test 4 — runs and durations visible

```text
Open packet with multiple attempts
Check failed attempt row exists
Check failed attempt duration visible
Check running/current attempt elapsed visible if active
```

### Test 5 — artifacts visible

```text
Open packet with artifact fixtures
Go to Artifacts tab
Check artifacts list
Open stdout.log preview
Check preview text
```

### Test 6 — refresh does not reset selection

```text
Open Packet Detail
Go to Artifacts tab
Simulate refresh/websocket update
Check selected packet remains
Check selected tab remains
Check live timer still updates
```

### Test 7 — mobile viewport

Viewports:

```text
390x844
430x932
768x1024
1440x900
```

Acceptance:

```text
no horizontal scroll
feature list opens
packets open
packet detail opens
bottom tabs work
artifacts available
timers remain readable
```

### Test 8 — self-improvement visible

With seed data:

```text
GRACE Self-Improvement visible in feature list
Self-improvement badge visible
Packet detail shows safety banner
Required gates checklist visible
```

---

## 37. Console error gate

All Playwright tests must:

```text
fail on pageerror
fail on console.error
```

Any runtime JS error fails the test.

Whitelists only with explicit comment.

---

## 38. Demo data / fixtures

Add seed/demo scenario:

```text
1 normal feature
1 self-improvement feature
3 waves
8-12 packets
1 running packet
1 rejected packet
1 failed packet
1 accepted packet
1 merged packet
1 packet with multiple runs
1 packet with artifacts
1 stale worker
1 self-improvement packet waiting for reviewer
```

Artifact fixtures:

```text
stdout.log
stderr.log
tests.txt
evidence.json
diff.patch
screenshot.png
```

Timing fixtures:

```text
feature running for 1 hour 12 minutes 05 seconds
wave running for 26 minutes 30 seconds
packet running for 7 minutes 14 seconds
failed attempt duration 6 minutes 59 seconds
accepted attempt duration 8 minutes 03 seconds
queued packet waiting 3 minutes 04 seconds
```

Use demo data for:

```text
local manual check
Playwright
regression tests
screenshots
```

---

## 39. CI acceptance gate

CI must include:

```text
Backend tests
JS syntax tests
API contract tests
Duration/timer unit tests
Artifact regression tests
Playwright smoke tests
Playwright mobile tests
Self-improvement UI tests
```

Mission Control Center is not ready if:

```text
backend tests green but Playwright red
JS syntax check fails
console errors exist
artifacts do not open
mobile has horizontal scroll
packet detail does not show runs/events/artifacts
failed attempts are hidden
attempt durations missing
feature/wave/packet timers missing
self-improvement packet has no badge/checklist/safety banner
```

---

## 40. Implementation plan

### Wave 1 — Data/API + test foundation

```text
Rename UI to GRACE Mission Control Center
Add /api/dashboard/v2
Extend packet detail endpoint
Add timing computed fields to dashboard/detail responses
Fix artifact run id mismatch
Add self-improvement fields to packet detail
Add JS syntax check
Add backend smoke tests
Add API contract tests
Add duration/timer tests
Add artifact regression tests
Add basic Playwright setup
Add fail-on-console-error/pageerror gate
```

### Wave 2 — Simplified desktop UI

```text
Top bar
Status summary
Feature list
Selected feature view
Compact wave/packet rows
Feature/wave/packet live timers
Remove overloaded 3-column cockpit default
Packet detail opens by click
Desktop Playwright smoke tests
```

### Wave 3 — Packet Detail + Runs + Artifacts

```text
Overview tab
Runs tab with all attempts and durations
Artifacts tab
Events tab
Spec tab
Artifact preview
JSON preview
Image preview
Empty/error states
Artifact Playwright tests
```

### Wave 4 — Self-improvement UI

```text
GRACE Self-Improvement feature mode
Self-improvement badge
Safety banner in Packet Detail
Required gates checklist
Affected subsystem/risk/rollback fields
Playwright tests for self-improvement
```

### Wave 5 — Mobile

```text
Mobile drill-down navigation
Feature screen
Waves/Packets screen
Packet Detail screen
Artifacts/Logs screen
Bottom tabs
390px/430px viewport tests
No horizontal scroll gate
Mobile timer readability
```

### Wave 6 — Stability / polish / docs

```text
Demo seed data
WebSocket/polling refresh tests
Accessibility/basic UX checks
README update
Final screenshots
CI gate cleanup
```

---

## 41. Acceptance criteria

Mission Control Center is ready only if:

```text
1. / opens without JS errors.
2. All JS files pass node --check.
3. Playwright fails on pageerror and console.error.
4. Main screen is not overloaded.
5. Main screen shows summary, features, selected feature.
6. Feature row/card shows elapsed or final duration.
7. Wave row/card shows elapsed or final duration.
8. Packet row/card shows elapsed or final duration.
9. Packet detail opens by click.
10. Overview explains current packet state.
11. Runs tab shows every attempt.
12. Failed/rejected attempts remain visible after retry.
13. Every attempt has human-readable duration.
14. Running feature/wave/packet has live updating timer.
15. Terminal feature/wave/packet has final duration.
16. Artifacts tab shows real artifacts.
17. Events tab shows human-readable lifecycle.
18. Spec tab shows readable spec_json.
19. Refresh/WebSocket does not reset selected feature/packet/tab.
20. Artifact regression covers R01 and packet_id-R01.
21. Mobile 390px has no horizontal scroll.
22. Self-improvement feature visible separately.
23. Self-improvement packet has badge.
24. Self-improvement detail has safety banner.
25. Self-improvement detail has required gates checklist.
26. Empty/error states covered by tests.
27. CI fails if frontend runtime is broken.
28. UID model respected: links/actions use feat_/wave_/pkt_, slug is display only.
29. No logic parses W01/P01/FEAT- from IDs.
30. User understands in 3–5 seconds what is running, what failed, what is ready, where the problem packet is, where artifacts are, and which tasks modify GRACE itself.
```

---

## 42. Do not do in this task

```text
Do not change retry policy.
Do not change worker execution semantics.
Do not change acceptance pipeline behavior.
Do not change merge behavior.
Do not implement recovery/escalation.
Do not introduce React/Vue/Svelte.
Do not require real agent runs in tests.
Do not show raw seconds as primary UI.
Do not derive IDs from title/slug/order.
Do not hide failed attempts.
```

---

## 43. Final coder report format

Coder must report:

```text
Files changed
Dashboard v2 API implemented: yes/no
Packet detail endpoint extended: yes/no
Artifact endpoints fixed: yes/no
Duration formatter implemented: yes/no
Feature timer shown: yes/no
Wave timer shown: yes/no
Packet timer shown: yes/no
Attempt durations shown including failed attempts: yes/no
Live timer JS added: yes/no
Self-improvement UI added: yes/no
Mobile layout implemented/tested: yes/no
UID links/actions preserved: yes/no
JS syntax tests added: yes/no
Playwright tests added: yes/no
Tests run
Remaining blockers
```
