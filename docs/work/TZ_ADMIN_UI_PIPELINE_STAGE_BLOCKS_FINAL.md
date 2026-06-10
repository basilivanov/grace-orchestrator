# TZ: Admin UI — make pipeline human-readable stage blocks

Date: 2026-06-10
Status: ready for coder
Priority: P1 operator UX follow-up
Scope: admin UI only
Current bad implementation observed: `fbeedf7` / follow-up screenshots after `152cfe2`

## 1. Problem

The current pipeline UI still looks like a messy terminal/log output, not an operator UI.

Even after converting from horizontal cards, the pipeline is rendered as compact text lines:

```text
✓ Materialized Done
10:43:32 → 10:43:32 · 54m 31s · p1
✓ Executor selected Done
10:43:33 → 10:43:33 · 54m 31s · executor
✓ Coder run Done
10:43:33 → 10:45:42 · 2m 9s · live-wr-1133292
○ Reviewer gate Pending
—
○ Merge Pending
—
— Skipped stages Skipped
T0 scope/lint, T1 tests, T2 smoke/e2e, Evidence verifier
✕ Final state Cancelled
cancelled
```

This is not readable enough. It still feels like a raw log because:

- stages are not visually separated enough;
- status, title, timing, duration and meta blend together;
- green text dominates successful stages;
- pending/skipped rows add noise;
- the operator cannot instantly see the story of the packet.

The required output is **not** another text log. It must be a human-readable UI.

## 2. Goal

Make the pipeline section readable and calm.

Use **one wide block per meaningful stage**, stacked vertically. Reuse the old card/block visual language if helpful, but make each block full-width and readable.

A good target shape:

```text
PIPELINE

┌──────────────────────────────────────────────────────────────┐
│ ✓ Materialized                                      [Done]    │
│   Time: 10:43:32 → 10:43:32    Duration: 0s    Meta: p1       │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ ✓ Executor selected                                 [Done]    │
│   Time: 10:43:33 → 10:43:33    Duration: 0s    Meta: executor │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ ✓ Coder run                                         [Done]    │
│   Time: 10:43:33 → 10:45:42    Duration: 2m 9s               │
│   Worker: live-wr-1133292                                      │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ ✕ Final state                                    [Cancelled] │
│   State: cancelled                                           │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ — Skipped by NORMAL profile                       [Skipped]  │
│   T0 scope/lint · T1 tests · T2 smoke/e2e · Evidence verifier │
└──────────────────────────────────────────────────────────────┘
```

The important rule:

```text
One stage = one visually bounded block.
```

## 3. Non-goals

Do not change packet lifecycle.
Do not change worker lifecycle.
Do not change health/watchdog.
Do not change agent execution.
Do not change backend state names.
Do not introduce React/Vite/frontend build.
Do not redesign the entire admin page.

This is a Jinja/CSS display patch.

## 4. Required visual design

### 4.1 Use full-width vertical stage blocks

Pipeline should be a vertical list:

```html
<div class="pipeline-stage-list">
  <div class="pipeline-stage-block ...">...</div>
  <div class="pipeline-stage-block ...">...</div>
</div>
```

Each block should have:

- border;
- subtle background;
- left accent border or icon;
- first row with icon + stage title + status badge;
- second row with labelled timing fields;
- optional third row for worker/meta/reason.

Do not render stages as bare text lines.

### 4.2 Required block content

For each meaningful stage block:

```text
[icon] Stage label                         [Status badge]
Time: <started> → <finished/now>           Duration: <duration>
Meta/Worker/Reason: <short value>
```

Examples:

```text
✓ Materialized                             [Done]
Time: 10:43:32 → 10:43:32                 Duration: 0s
Meta: p1
```

```text
✓ Coder run                                [Done]
Time: 10:43:33 → 10:45:42                 Duration: 2m 9s
Worker: live-wr-1133292
```

```text
✕ Final state                              [Cancelled]
State: cancelled
```

### 4.3 Do not make all successful text bright green

The current UI uses too much green, making the pipeline look like terminal output.

Required:

- normal text color for stage title and time fields;
- green only for icon, status badge, or left border;
- red only for icon/status/border on cancelled/failed/rejected;
- skipped/pending muted but readable;
- no neon full-line text.

Bad:

```text
✓ Materialized Done
10:43:32 → 10:43:32 · 54m 31s · p1
```

all bright green.

Good:

```text
✓ Materialized [Done]
Time: 10:43:32 → 10:43:32  Duration: 0s
```

where only `✓`/badge/border is green.

### 4.4 Reduce noise from pending stages

Do not show large noisy blocks for meaningless pending stages if packet is already terminal.

For a cancelled packet, the important story is:

```text
Materialized → Executor selected → Coder run → Final state: Cancelled
```

Pending Reviewer/Merge rows should either:

- be hidden when packet is terminal and the stage was never reached; or
- be collapsed under a small muted line:

```text
Not reached: Reviewer gate, Merge
```

Do not make `Reviewer gate Pending` and `Merge Pending` visually equal to real completed stages.

### 4.5 Collapse skipped NORMAL profile stages

NORMAL-profile skipped stages should be one muted block, not multiple rows:

```text
— Skipped by NORMAL profile [Skipped]
T0 scope/lint · T1 tests · T2 smoke/e2e · Evidence verifier
```

This block should be visually secondary and placed after real/reached stages, or below terminal state if that reads better.

### 4.6 Correct duration display

Do not show `54m 31s` as duration for instant stages like Materialized and Executor selected if start and finish are equal.

Correct:

```text
Materialized: 10:43:32 → 10:43:32, Duration: 0s
Executor selected: 10:43:33 → 10:43:33, Duration: 0s
Coder run: 10:43:33 → 10:45:42, Duration: 2m 9s
```

If a stage is running:

```text
Coder run: 10:43:33 → now, Elapsed: 54m 31s
```

Only the current running stage should use elapsed-to-now. Completed instant stages must not inherit total packet elapsed.

### 4.7 Keep click behavior, but not at cost of readability

If stages are clickable, preserve HTMX behavior:

- Coder run → Attempts tab;
- Evidence/test stages → Evidence tab;
- Final state → Events tab;
- Skipped block can be non-clickable or Evidence tab.

The clickable area should be the whole block.

## 5. Concrete layout recommendation

Use this structure in `_detail.html`:

```jinja2
<section class="pipeline-view">
  <h2 class="pipeline-h">PIPELINE</h2>
  <div class="pipeline-stage-list">
    {% for row in pipeline_rows %}
      <div class="pipeline-stage-block pipeline-stage-{{ row.status }} severity-{{ row.severity }}"
           {% if row.target_tab %}hx-get="..." hx-target="#packet-tab-content" ...{% endif %}>
        <div class="pipeline-stage-head">
          <div class="pipeline-stage-title-wrap">
            <span class="pipeline-stage-icon">{{ row.icon }}</span>
            <span class="pipeline-stage-title">{{ row.label }}</span>
          </div>
          <span class="pipeline-stage-badge badge severity-{{ row.severity }}">{{ row.status_label }}</span>
        </div>

        <div class="pipeline-stage-facts">
          {% if row.time_range %}
            <div class="pipeline-fact">
              <span class="pipeline-fact-label">Time</span>
              <span class="pipeline-fact-value mono">{{ row.time_range }}</span>
            </div>
          {% endif %}
          {% if row.duration %}
            <div class="pipeline-fact">
              <span class="pipeline-fact-label">Duration</span>
              <span class="pipeline-fact-value mono">{{ row.duration }}</span>
            </div>
          {% endif %}
          {% if row.meta %}
            <div class="pipeline-fact pipeline-fact-wide">
              <span class="pipeline-fact-label">Meta</span>
              <span class="pipeline-fact-value">{{ row.meta }}</span>
            </div>
          {% endif %}
        </div>
      </div>
    {% endfor %}
  </div>
</section>
```

Exact variable names may differ. The final rendered shape must match the intent.

## 6. Concrete CSS recommendation

Use something close to this:

```css
.pipeline-stage-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.pipeline-stage-block {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-left: 4px solid var(--border-2);
  border-radius: 8px;
  padding: 10px 12px;
}

.pipeline-stage-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.pipeline-stage-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.pipeline-stage-icon {
  width: 18px;
  text-align: center;
  flex: 0 0 18px;
}

.pipeline-stage-title {
  color: var(--fg);
  font-size: 13px;
  font-weight: 650;
}

.pipeline-stage-facts {
  margin-top: 7px;
  padding-left: 26px;
  display: grid;
  grid-template-columns: minmax(220px, auto) minmax(120px, auto) minmax(180px, 1fr);
  gap: 8px 18px;
  align-items: baseline;
}

.pipeline-fact-label {
  color: var(--fg-muted);
  text-transform: uppercase;
  font-size: 10px;
  letter-spacing: .04em;
  margin-right: 6px;
}

.pipeline-fact-value {
  color: var(--fg-2);
  font-size: 12px;
}

.pipeline-fact-value.mono,
.pipeline-fact .mono {
  white-space: nowrap;
}

.pipeline-stage-done { border-left-color: var(--sev-ok-soft); }
.pipeline-stage-running { border-left-color: var(--accent); }
.pipeline-stage-cancelled,
.pipeline-stage-rejected,
.pipeline-stage-failed { border-left-color: var(--sev-crit); }
.pipeline-stage-skipped,
.pipeline-stage-pending { border-left-color: var(--border-2); opacity: .85; }
```

Important:

- no `text-overflow: ellipsis` for time fields;
- no all-green text;
- no bare newline-separated fields.

## 7. Data / helper rules

### 7.1 Meaningful rows only

Build visible rows using rules:

```text
include real reached stages: done/running/failed
hide pending stages after terminal state unless they were reached
collapse skipped NORMAL stages into one skipped block
add final terminal state block when packet is terminal
```

### 7.2 Duration rules

For each stage:

```text
if status == running:
    duration = now - started_at
elif started_at and finished_at:
    duration = finished_at - started_at
elif duration_ms exists:
    duration = duration_ms
else:
    duration = —
```

Do not use packet total elapsed as the duration of every stage.

### 7.3 Terminal state block

For cancelled packet:

```text
label = Final state
status_label = Cancelled
meta = cancelled
severity = critical or attention
```

It should be visually clear and separate.

## 8. Tests required

Keep existing tests and add/update these:

### 8.1 Stage block structure smoke

Assert rendered detail HTML contains:

```text
pipeline-stage-block
pipeline-stage-head
pipeline-stage-facts
```

and does not rely on old plain text layout as the only pipeline representation.

### 8.2 Instant stages show 0s

For a stage with equal `started_at` and `finished_at`, assert duration is `0s` or equivalent, not packet elapsed time.

### 8.3 Terminal packet hides unreached pending noise

For cancelled packet, assert:

```text
Final state
Cancelled
```

is present, and pending Reviewer/Merge rows are either hidden or shown only in a collapsed `Not reached` line.

### 8.4 Skipped NORMAL profile is collapsed

Assert there is one skipped block for NORMAL skipped stages:

```text
Skipped by NORMAL profile
T0 scope/lint
T1 tests
T2 smoke/e2e
Evidence verifier
```

### 8.5 No all-green text class on stage body

At least via template structure: severity class should be on card/badge/icon, not on every text value.

## 9. Acceptance criteria

Accepted only when live screenshot shows:

1. Pipeline is not a text log.
2. Each meaningful stage is a separate full-width block/card.
3. Stage title, status, time, duration and meta are visually grouped.
4. Completed instant stages show `0s`, not total packet elapsed.
5. Coder run shows its real duration.
6. Cancelled final state is obvious.
7. Pending unreached Reviewer/Merge do not dominate cancelled packet view.
8. Skipped NORMAL stages are collapsed and visually secondary.
9. Current Run block remains below/near pipeline.
10. Tests pass.

## 10. Manual rejection examples

Reject if it looks like:

```text
✓ Materialized Done
10:43:32 → 10:43:32 · 54m 31s · p1
✓ Executor selected Done
10:43:33 → 10:43:33 · 54m 31s · executor
```

Reject if it looks like:

```text
Done
Materialized
10:43:32 → 10:43:32
54m 31s
p1
```

Accept if it looks like separate readable blocks:

```text
✓ Materialized                         [Done]
Time: 10:43:32 → 10:43:32             Duration: 0s
Meta: p1

✓ Coder run                            [Done]
Time: 10:43:33 → 10:45:42             Duration: 2m 9s
Worker: live-wr-1133292

✕ Final state                          [Cancelled]
State: cancelled
```

## 11. Reviewer note

This must be reviewed visually, not only by tests.

The question is:

```text
Can a human operator understand the packet story in 3 seconds?
```

If no, reject.
