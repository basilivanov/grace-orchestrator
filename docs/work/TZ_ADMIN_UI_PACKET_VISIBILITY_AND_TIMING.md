# TZ: Improve Admin UI packet visibility and timing readability

Date: 2026-06-10
Status: ready for coder
Priority: P1 operator UX / live-run usability
Scope: admin UI readability only; no control-plane lifecycle rewrite

## 1. Problem

During live-run monitoring at `http://127.0.0.1:8042/admin`, the packet is technically visible, but the operator can easily miss it.

Observed UI state:

```text
supervisor: down
1 workers
1 features
1 packets
1 running
```

The actual packet appears in the left pane, but it is visually weak:

```text
Live: backend-1w
Untitled packet
Running
attempt 2/3
started 10:29:06
```

The user feedback is that it is not obvious where the task is, what is currently happening, when it started, how long it has been running, and what the pipeline stage cards mean.

Current pain points:

1. The left packet/task list has low visual priority and poor contrast.
2. The selected task does not look like the central object of the page.
3. The pipeline cards truncate or hide useful timing/meta information.
4. It is hard to see at a glance:
   - current status;
   - started at;
   - finished at;
   - elapsed time while running;
   - duration after finish;
   - attempt number;
   - worker id;
   - current stage.
5. The UI has data, but the data is too scattered across the page.

## 2. Goal

Make the admin UI usable as a live operator console.

When a packet is running, the operator must understand in one glance:

```text
What task is running?
What packet is selected?
What stage is active?
When did it start?
How long has it been running?
Which attempt is it?
Which worker is running it?
If finished, when did it finish and how long did it take?
```

This task is about visibility and layout, not backend semantics.

## 3. Non-goals

Do not change packet lifecycle semantics.
Do not change worker lifecycle semantics.
Do not change health/watchdog behavior.
Do not add process-kill logic.
Do not add direct DB mutations.
Do not redesign the whole admin console.
Do not introduce React or a frontend build step.
Keep the existing server-rendered Jinja/HTMX approach.

## 4. Required UX changes

### 4.1 Left pane: make packets visible as real task cards

The left pane should clearly show packets/tasks, not just weak text hidden inside feature/wave nesting.

For each packet card, show:

```text
[Running] P1 / packet title
Add done endpoint
packet: pkt_fMG...
Started: 10:29:06
Elapsed: 00:31:42  # if running
Attempt: 2/3
Worker: live-wr-1123176  # if known
```

If completed:

```text
[Rejected] P1 / packet title
Started: 10:29:06
Finished: 10:34:51
Duration: 00:05:45
Attempt: 2/3
```

Requirements:

- Increase packet title size and contrast.
- Use a clear status badge: Running / Failed / Rejected / Accepted / Merged / Cancelled.
- Highlight the selected packet with visible border/background.
- Show at least started time and elapsed/duration.
- Keep feature/wave context, but do not let it visually dominate the packet.
- Avoid ultra-thin gray labels for critical fields.

### 4.2 Add a detail summary header for the selected packet

At the top of the right detail pane, add a compact summary block.

For running packet:

```text
Status: Running
Started: 10:29:06
Elapsed: 00:31:42
Finished: —
Attempt: 2/3
Worker: live-wr-1123176
Stage: Coder run
```

For finished packet:

```text
Status: Rejected
Started: 10:29:06
Finished: 10:34:51
Duration: 00:05:45
Attempt: 2/3
Worker: live-wr-1123176
Stage: Reviewer gate
```

Requirements:

- This summary must be visible without opening tabs.
- Use monospace for timestamps/durations.
- Use strong labels and readable values.
- Do not hide elapsed/duration in small card metadata only.
- If a field is unknown, show `—`, not empty space.

### 4.3 Pipeline cards: show timing and avoid unreadable truncation

Current pipeline cards are visually present but too cryptic. Make each stage card show a consistent mini-layout:

```text
Coder run
Running
10:29:06 → now
31m 42s
```

or:

```text
Reviewer gate
Rejected
10:29:06
```

or:

```text
T1 tests
Skipped
NORMAL profile
```

Requirements:

- Every stage card must show:
  - stage title;
  - status;
  - relevant time or duration when available;
  - short meta line.
- Avoid long truncated text like `no separate run (NORMAL ...` as primary content.
- For skipped NORMAL stages, show concise text:
  - `Skipped`
  - `NORMAL profile`
- For running stage, show elapsed time prominently.
- For failed/rejected stage, show failure status prominently.
- Pipeline cards may wrap to two rows, but important text must remain readable.

### 4.4 Add or improve “Current run” block

Add a block near the selected packet detail, before Dev Replay, titled:

```text
CURRENT RUN
```

Suggested fields:

```text
Run: attempt 2/3
State: running
Worker: live-wr-1123176
Executor: coder-opencode
Started: 10:29:06
Elapsed: 00:31:42
Last event: coder run started / reviewer rejected / etc.
```

Requirements:

- This should help the operator understand the live execution without opening Events, Logs, or Attempts.
- If no run exists yet, show `No run started yet`.
- If run is finished, show `Finished` and `Duration`.

### 4.5 Improve visual contrast and density

The current dark UI is too low-contrast in important areas.

Required style changes:

- Make selected packet and selected feature/wave visibly active.
- Increase contrast for critical metadata.
- Use consistent spacing and alignment for time fields.
- Use status colors consistently:
  - Running: blue/green accent.
  - Failed/Rejected: red accent.
  - Accepted/Merged: green accent.
  - Pending/Skipped: muted but readable.
- Avoid showing critical fields as tiny, low-contrast gray text.

## 5. Data requirements

Prefer using existing data already available in admin aggregation:

- packet id;
- packet title / slug;
- packet state;
- attempt_count / max_attempts;
- started_at;
- finished_at;
- elapsed_seconds;
- worker_id;
- model / executor_id;
- pipeline stages;
- state machine data;
- runs summary.

If a field is missing from the template context but exists in `AdminAggregationService`, pass it through the existing DTO. Do not add heavy DB loops.

If elapsed time is computed server-side, it can update on page refresh/HTMX refresh. Live ticking in JS is optional and not required for this task.

## 6. Files likely involved

Likely files:

```text
src/grace_control/api/routers/admin_ui.py
src/grace_control/services/admin_aggregation_service.py
src/grace_control/ui/templates/admin/*.html
src/grace_control/ui/static/*
tests/grace_control/services/test_admin_aggregation_service.py
```

Use actual existing template file names in the repo.

## 7. Implementation guidance

### 7.1 Keep HTMX/Jinja approach

Do not introduce React/Vite/frontend build.

This is a server-rendered admin console. Use existing template structure.

### 7.2 Add small template helpers if needed

Acceptable helpers:

```text
format_time(dt)
format_duration(seconds)
status_badge_class(state)
stage_badge_class(status)
short_id(id)
```

Prefer existing filter/helper location if present.

### 7.3 Duration formatting

Format elapsed/duration as readable text.

Examples:

```text
00:00:08
00:03:42
01:12:09
```

or compact:

```text
8s
3m 42s
1h 12m
```

Pick one style and use it consistently.

For running packet:

```text
Elapsed = now - started_at
Finished = —
```

For finished packet:

```text
Duration = finished_at - started_at
Finished = finished_at
```

### 7.4 Preserve existing page structure

Do not remove current Events / Spec / Attempts / Agent sessions / Evidence / Logs / Artifacts tabs.

The task is to make the top-level operator view understandable before opening tabs.

## 8. Tests required

Add/update tests for aggregation/template data. Exact test location may follow existing test structure.

Required checks:

### 8.1 Admin aggregation includes timing fields

For a running packet with started_at and no finished_at, assert DTO contains enough fields to render:

```text
started_at
finished_at = None or "—"
elapsed_seconds > 0
is_running = true
attempt_count
max_attempts
worker_id
```

### 8.2 Finished packet duration

For a finished packet, assert DTO/template context can render:

```text
started_at
finished_at
duration/elapsed_seconds
is_running = false
```

### 8.3 Pipeline stage compact metadata

Assert pipeline stages include enough data to render title/status/meta/time without relying on long truncated text.

### 8.4 Template smoke

At minimum, `GET /admin?packet_id=<id>` should return 200 and include visible key strings:

```text
CURRENT RUN
Started
Elapsed or Duration
Attempt
Worker
```

If full HTML assertions are too brittle, keep them minimal but useful.

## 9. Manual acceptance checklist

After implementation, run a live scenario and open:

```text
http://127.0.0.1:8042/admin
```

The operator should immediately see:

- the selected/running packet in the left pane;
- packet title and status without squinting;
- status, started time, elapsed/duration, attempt, worker in the right pane;
- readable pipeline stage cards;
- no critical metadata hidden in tiny gray truncated text.

## 10. Suggested verification commands

```bash
pytest tests/grace_control/services/test_admin_aggregation_service.py -q
pytest tests/grace_control/api -q
pytest tests/grace_control -q
```

Runtime smoke:

```bash
PYTHONPATH=. GRACE_LIVE_AGENT_TESTS=1 GRACE_DEV_TOOLS_ENABLED=1 GRACE_FAST_FAIL=1 \
  python3 -u tests_live/runner/wave_resume_runner.py \
    --scenario backend-1w \
    --api-url http://127.0.0.1:8042 \
    --source-dir . \
    --target-dir /tmp/grace-live-test \
    --timeout 900 \
    --keep-artifacts
```

Then open:

```text
http://127.0.0.1:8042/admin
```

## 11. Acceptance criteria

Accepted when:

1. Running packet is visually obvious in the left pane.
2. Selected packet has a clear summary header with status/timing/attempt/worker.
3. Pipeline cards show readable status and timing/meta.
4. Current run is understandable without opening sub-tabs.
5. Existing admin tabs still work.
6. No lifecycle/control-plane behavior changed.
7. Tests pass.

## 12. Notes for reviewer

This is a UX readability patch. Judge it by operator clarity during a live run.

The expected improvement is not “more data”, but “the existing data is impossible to miss”.
