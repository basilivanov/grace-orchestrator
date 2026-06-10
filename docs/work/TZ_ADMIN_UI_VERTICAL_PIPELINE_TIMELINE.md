# TZ: Admin UI — replace horizontal pipeline cards with vertical timeline/table

Date: 2026-06-10
Status: ready for coder
Priority: P1 operator UX follow-up
Scope: admin UI readability only
Depends on: `docs/work/TZ_ADMIN_UI_PACKET_VISIBILITY_AND_TIMING.md`
Related review: `docs/work/REVIEW_ADMIN_UI_PACKET_VISIBILITY_F122FA2.md`

## 1. Problem

The previous admin UI patch improved packet visibility and added `CURRENT RUN`, but the pipeline section still uses horizontal cards.

In the live UI, pipeline cards are too narrow. Timing is truncated or hidden:

```text
Materialized        p1 10:43:32 → 10:43:32
Executor selected   executor 10:43:33 → 10:43...
Coder run           live-wr-1133292 10:43:33 ...
```

The operator still cannot clearly see:

- when each stage started;
- when it finished;
- how long it took;
- which stage is current/terminal;
- whether cancellation is a terminal state;
- what was skipped due to NORMAL profile.

The UX issue is not lack of data. The issue is layout: horizontal cards compress time fields too much.

## 2. Goal

Replace the horizontal pipeline-card grid in the packet detail pane with a vertical timeline/table that shows stage timing without truncation.

The operator must be able to read each stage row in one pass:

```text
Status      Stage               Time range                Duration     Meta
Done        Materialized         10:43:32 → 10:43:32       0s           p1
Done        Executor selected    10:43:33 → 10:43:33       0s           coder-opencode
Done        Coder run            10:43:33 → 11:06:09       22m 36s      live-wr-1133292
Cancelled   Final state          11:06:09                  —            cancelled
Skipped     NORMAL profile       —                         —            T0, T1, T2, verifier
```

## 3. Non-goals

Do not change packet lifecycle semantics.
Do not change worker lifecycle semantics.
Do not change health/watchdog behavior.
Do not change agent execution logic.
Do not introduce React or a frontend build step.
Do not remove the existing Events / Spec / Attempts / Agent sessions / Evidence / Logs / Artifacts tabs.
Do not redesign the whole admin console.

This is a Jinja/HTMX/CSS readability patch, with minimal DTO additions only if needed for display.

## 4. Required UX changes

### 4.1 Replace horizontal cards with vertical timeline/table

Current:

```text
[Materialized] [Executor selected] [Coder run] [T0] [T1] ...
```

Required:

```text
PIPELINE

Done        Materialized         10:43:32 → 10:43:32       0s        p1
Done        Executor selected    10:43:33 → 10:43:33       0s        coder-opencode
Done        Coder run            10:43:33 → 11:06:09       22m 36s   live-wr-1133292
Cancelled   Final state          11:06:09                  —         cancelled
Skipped     NORMAL profile       —                         —         T0, T1, T2, verifier
```

Acceptable visual forms:

- vertical timeline rows;
- compact table;
- two-column layout where labels stay fixed and timing has enough width.

Not acceptable:

- horizontal stage cards that truncate timestamps;
- hidden title tooltips as the only way to see time;
- tiny `muted small` timing text for key runtime information.

### 4.2 Each stage row must show explicit timing

Every non-skipped stage row should show:

```text
started_at → finished_at
```

For running stage:

```text
started_at → now
elapsed duration
```

For done/failed stage:

```text
started_at → finished_at
duration
```

For instant stages where start and finish are equal:

```text
10:43:32 → 10:43:32
0s
```

If a timestamp is unknown:

```text
—
```

Do not show an incomplete clipped value such as:

```text
10:43...
```

### 4.3 Add terminal state row

When packet state is terminal and not already represented clearly, add a final row:

```text
Cancelled   Final state    11:06:09    —    cancelled
Rejected    Final state    11:06:09    —    rejected
Accepted    Final state    11:06:09    —    accepted
Merged      Final state    11:06:09    —    merged
```

For the current observed case, packet state is `cancelled`, but the old pipeline still visually ends around `Reviewer gate` / `Merge` pending. That is confusing.

Required behavior:

- If `packet.state == cancelled`, show a clear `Cancelled` terminal row.
- If `packet.state in rejected/failed/blocked/...`, show final row with that terminal status unless reviewer/failure row already makes it obvious.
- If `packet.state == running`, no terminal row; current active stage should show `→ now`.

### 4.4 Collapse skipped NORMAL-profile stages

The current horizontal pipeline spends a lot of space on skipped stages:

```text
T0 scope/lint
T1 tests
T2 smoke/e2e
Evidence verifier
```

For `NORMAL` profile, these should not be large separate rows unless there is real evidence data.

Required collapsed row:

```text
Skipped     NORMAL profile    —    —    T0 scope/lint, T1 tests, T2 smoke/e2e, Evidence verifier
```

If a STRICT/profile run has real evidence stage data, render the real stages as individual rows.

### 4.5 Keep stage rows clickable

Current cards are clickable and open the corresponding tab through HTMX.

Preserve that behavior:

- clicking `Coder run` opens Attempts or appropriate tab;
- clicking test/evidence stages opens Evidence;
- clicking reviewer opens Events/Review-related tab if currently mapped;
- terminal row may open Events.

Do not break `hx-get`, `hx-target`, `hx-swap`, `hx-push-url` behavior.

### 4.6 Keep optional mini progress strip only if useful

Optional: keep a tiny icon-only progress strip above the vertical table.

If kept:

- no long text;
- no timestamps;
- only colored dots/icons for overall progress.

The readable source of truth must be the vertical timeline/table.

## 5. Data requirements

Use existing stage DTO fields where possible:

```text
key
label
status
started_at
finished_at
duration_ms
meta
target_tab
```

If `finished_at` is missing for some stage, add it in the admin read-model only.

Do not change lifecycle behavior. This is display/read DTO only.

### 5.1 Stage row derived fields

Template or filter should derive:

```text
status_label
status_severity
time_range_label
duration_label
meta_label
```

Examples:

```text
time_range_label = "10:43:33 → now"       # running
elapsed/duration = "22m 36s"

time_range_label = "10:43:33 → 11:06:09"  # done/failed
elapsed/duration = "22m 36s"

time_range_label = "—"                    # skipped/pending
elapsed/duration = "—"
```

## 6. Files likely involved

Likely files:

```text
src/grace_control/ui/templates/admin/_detail.html
src/grace_control/ui/static/admin.css
src/grace_control/ui/admin_template_filters.py
src/grace_control/services/admin_aggregation_service.py  # only if finished_at/stage DTO fields are missing
tests/grace_control/api/test_admin_ui.py or nearest existing admin UI tests
tests/grace_control/services/test_admin_aggregation_service.py
```

Keep changes small.

## 7. Implementation guidance

### 7.1 Template shape

Replace:

```html
<div class="pipeline-stages">
  <div class="stage ...">...</div>
</div>
```

with something like:

```html
<div class="pipeline-timeline">
  {% for row in pipeline_rows %}
    <div class="pipeline-row pipeline-row-{{ row.status }}"
         hx-get="..."
         hx-target="#packet-tab-content"
         hx-swap="outerHTML"
         hx-push-url="...">
      <div class="pipeline-row-status">{{ row.status_label }}</div>
      <div class="pipeline-row-stage">{{ row.label }}</div>
      <div class="pipeline-row-time mono">{{ row.time_range }}</div>
      <div class="pipeline-row-duration mono">{{ row.duration }}</div>
      <div class="pipeline-row-meta">{{ row.meta }}</div>
    </div>
  {% endfor %}
</div>
```

Use actual available data/context names.

### 7.2 CSS guidance

Suggested layout:

```css
.pipeline-timeline {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.pipeline-row {
  display: grid;
  grid-template-columns: 88px minmax(160px, 1.2fr) minmax(180px, 1fr) 90px minmax(180px, 1fr);
  gap: 12px;
  align-items: center;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-left: 3px solid var(--border-2);
  border-radius: 6px;
  background: var(--bg-2);
}

.pipeline-row-time,
.pipeline-row-duration {
  white-space: nowrap;
  overflow: visible;
  text-overflow: clip;
}
```

Responsive fallback:

```css
@media (max-width: 1100px) {
  .pipeline-row {
    grid-template-columns: 90px 1fr;
  }
  .pipeline-row-time,
  .pipeline-row-duration,
  .pipeline-row-meta {
    grid-column: 2;
  }
}
```

Important: do not make timing fields ellipsis-truncated.

### 7.3 Filtering skipped stages

Add helper/filter if useful:

```text
pipeline_visible_rows(stages, packet_state, packet_finished_at, acceptance_profile)
```

Rules:

- Group skipped NORMAL stages into one row.
- Keep real evidence/test stages separate when not skipped.
- Add terminal state row for cancelled/rejected/accepted/merged if needed.

Keep this helper deterministic and unit-testable.

## 8. Tests required

### 8.1 Template smoke test

Create or update admin UI template/API smoke test.

Assert selected packet detail HTML includes:

```text
PIPELINE
CURRENT RUN
Materialized
Executor selected
Coder run
```

and includes readable time separators:

```text
→ now
```

or:

```text
→
Duration
```

depending on test fixture state.

### 8.2 No truncated pipeline timing by CSS class

A simple assertion is enough:

- CSS for pipeline time/duration should not include `text-overflow: ellipsis`.
- Or template should not use old `.stage-meta` cards as primary pipeline display.

### 8.3 Collapsed NORMAL skipped stages

Test that NORMAL-profile skipped stages render one collapsed row containing:

```text
NORMAL profile
T0
T1
T2
Evidence verifier
```

and do not render four large independent skipped cards.

### 8.4 Terminal cancelled row

For a cancelled packet, assert the detail HTML includes:

```text
Cancelled
Final state
```

### 8.5 Stage timing DTO test

If aggregation is changed, test that rows/stages include:

```text
started_at
finished_at
elapsed/duration
status
label
```

## 9. Acceptance criteria

Accepted when:

1. Horizontal stage cards are no longer the primary pipeline view.
2. Pipeline is readable vertically/table-like.
3. Stage timing is fully visible, not truncated.
4. Running stage shows `started → now` and elapsed.
5. Finished stage shows `started → finished` and duration.
6. Cancelled packet shows a clear terminal `Cancelled / Final state` row.
7. NORMAL skipped stages are collapsed into one readable row.
8. Current Run block remains present.
9. Existing tabs/click behavior still works.
10. Tests pass.

## 10. Manual acceptance checklist

Run live scenario and open:

```text
http://127.0.0.1:8042/admin
```

Select the packet.

The operator should be able to read the full pipeline without hovering:

```text
Materialized          10:43:32 → 10:43:32       0s
Executor selected     10:43:33 → 10:43:33       0s
Coder run             10:43:33 → 11:06:09       22m 36s
Cancelled             11:06:09                  —
Skipped NORMAL        T0, T1, T2, verifier
```

If any timestamp or duration is clipped with `...`, the task is not accepted.

## 11. Notes for reviewer

This is not a backend correctness task. Review by looking at the live operator screen.

The key question:

```text
Can I understand exactly what happened in the pipeline without opening tabs or hovering?
```

If the answer is no, reject the patch as UX-incomplete.
