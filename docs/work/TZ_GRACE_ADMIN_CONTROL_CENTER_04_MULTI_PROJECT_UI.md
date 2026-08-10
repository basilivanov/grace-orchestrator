# TZ 04 — Multi-project Admin UI and entity drill-down

Depends on Stages 01-03.

## Objective

Extend the existing Jinja2 + HTMX Admin console into a project-aware Control Center using the Hub APIs created earlier.

Do not replace the current frontend stack with React/Vue/npm. Preserve server-rendered/HTMX architecture unless current `main` has already intentionally changed that architecture.

At the end of this stage an operator can navigate all projects and drill down through Feature -> Wave -> Packet -> Run/Stage using pretty views. Heavy global explorers are Stage 05.

## 1. Top-level shell

Add a persistent project selector and top-level navigation.

Required top-level views:

```text
Projects
Current Project
Events
Logs
Search
System/Diagnostics
```

Project selector must show at least:

```text
project name/key
online/degraded/offline/disabled indicator
```

Selecting a project must update URL/project context explicitly, not mutate process-global backend state.

## 2. URL model

Support canonical project-aware URLs:

```text
/admin
/admin/projects
/admin/p/{project_key}
/admin/p/{project_key}/feature/{feature_id}
/admin/p/{project_key}/wave/{wave_id}
/admin/p/{project_key}/packet/{packet_id}
/admin/p/{project_key}/system
```

Tabs may remain query-based/HTMX partials if that matches current Admin implementation.

A copied/deep-linked URL must reconstruct project/entity selection without relying on browser-global hidden state.

## 3. Projects Dashboard

`/admin` or `/admin/projects` becomes the multi-project landing view.

Each project card shows from Hub overview:

```text
name/key
status
Unix user metadata
project root identity
target branch + HEAD short SHA
GRACE version/code SHA
API/supervisor/DB health
workers active/total
READY/RUNNING/ACCEPTED/BLOCKED/FAILED counts
active parallel leases
merge owner/packet if any
last event
last error/attention item
state/worktree/evidence disk summary if available
```

Cards with attention sort before healthy idle cards.

Filters:

```text
All
Running
Attention
Blocked
Offline
Idle
```

One offline project renders its error card and does not make the page fail.

## 4. Project Overview

Reuse the existing Feature/Wave/Packet master tree and timeline concepts but source them through selected project's API/Hub client.

Feature row/card:

```text
id/slug/title/status
wave count
packet counts by state
total duration/tokens/cost if available
latest event
```

Wave:

```text
id/slug/title/order/status
packet state summary
duration
```

Packet compact row:

```text
state
attempt/max_attempt
worker
model
elapsed
scope summary
conflict_keys summary
depends_on summary
base SHA
integration base SHA
integration recheck
current typed wait reason
```

Avoid dumping full scope/spec JSON in the tree; use expandable/popover summary.

## 5. State and wait semantics

Use consistent labels for all packet states. Color cannot be the only signal.

Suggested semantics:

```text
READY                 neutral
RUNNING               blue
ACCEPTED              cyan
MERGED                green
REJECTED              orange
BLOCKED_RECOVERABLE   amber
BLOCKED_FINAL/FAILED  red
WAIT                   purple/neutral
```

Typed waits are first-class UI:

```text
waiting_for_dependency
waiting_for_scope_conflict
waiting_for_conflict_key
waiting_for_wave_completion
waiting_for_concurrency_slot
waiting_for_merge_slot
parallel_lease_lost
merge_lease_lost
```

A READY/ACCEPTED packet with a wait must display `WAIT: <reason>` rather than looking frozen.

## 6. Packet Detail

Make Packet Detail the main debugging page.

Header required fields where available:

```text
packet id/title
feature/wave
state
attempt
worker/executor/model
created/started/elapsed
acceptance profile
base SHA
current target SHA
integration base SHA
stale-base/recheck state
recommended action
```

For blocked/failed packet show an immediately visible Blocking panel:

```text
decided/blocked by
reason
failure class
failure stage
blocking issues
last failed command
exit code
stderr tail
```

No need to open Logs just to discover the primary failure.

## 7. Packet tabs

Required tabs:

```text
Overview
Timeline
Pipeline
Spec
Runs
Stages
Sessions
Evidence
Logs
Artifacts
Files
Git
Diagnostics
Raw
```

Stage 04 must wire at least Overview/Timeline/Pipeline/Spec/Runs/Stages/Sessions/Diagnostics to existing/project-local APIs. Heavy Logs/Artifacts/Files/Git/Raw behavior is completed in Stage 05, but tabs/routes can already exist with capability-aware placeholders.

## 8. Timeline

Packet timeline visually combines existing events/state transitions/stage lifecycle.

Each row/card:

```text
timestamp
event type/component
reason/entity
trace_id
payload collapsed indicator
```

Click opens the full payload JSON from canonical event/raw API.

Support filters appropriate to the packet timeline:

```text
event/component
run/stage
trace_id
text
```

Do not throw away events solely because they do not map to a pretty icon.

## 9. Pipeline / StageRun UI

Render pipeline as execution stages rather than a plain log stream.

Show known stages in actual runtime order, for example:

```text
context_builder
architect
executor
T0
T1
T2
browser
visual
reviewer
merge
```

Do not hard-code only these names; unknown/new `stage_key` still renders as a generic stage card.

Stage card fields:

```text
stage_key/status
start/finish/duration
loop_round/attempt_number
parent stage
worker/executor/model
tokens in/out/cost
error
trace_id
recovery reason
links to stdout/stderr/result/artifacts
```

Recovery chain should visually show return loops instead of flattening them away.

## 10. Runs and sessions

Runs tab:

```text
run id/number
status
worker/executor/model
timestamps/duration
base/integration SHA
size
```

Selecting a run updates run-dependent tabs.

Sessions tab renders session tree where capability exists. If not available, show a clear capability message, not an exception/empty broken card.

## 11. Project System view

Project system page displays:

```text
API/supervisor/DB/Git health
workers
runtime version/code SHA
uptime if available
effective configuration
packet/feature counts
ordinary/parallel/merge leases
wait summaries
```

Mask secrets in config.

## 12. Responsive behavior

Desktop can use master/detail layout.

Mobile must collapse to a single-column flow:

```text
Project selector
Search
Summary
Tree/list
Selected entity
Tabs
```

Do not force a three-column desktop control center into a 390px viewport.

## 13. Polling

Use HTMX partial polling, not full-page reloads.

Suggested cadence:

```text
project cards/stats: ~5s
running packet detail: ~2s
workers/system: ~5s
```

Polling must preserve active project/entity/tab and user scroll where practical.

## 14. Tests

Required minimum:

- projects page with 2 online projects;
- one offline project card without page failure;
- project selector deep link and back/forward semantics;
- same packet IDs in two projects never cross-wire detail;
- project Feature/Wave/Packet tree renders current project only;
- wait reason visible;
- blocked panel exposes primary reason;
- run selection changes run-dependent context;
- unknown stage key renders generically;
- sessions unavailable capability renders graceful banner;
- polling partial does not reset selected project/entity;
- mobile smoke at existing frontend acceptance viewport(s);
- existing single-project Admin UI regressions remain green where still applicable.

## 15. Acceptance

Stage 04 is complete when the operator can navigate from Projects -> selected project -> feature/wave/packet -> run/stage and understand current runtime/failure state without using global explorers or SSH.
