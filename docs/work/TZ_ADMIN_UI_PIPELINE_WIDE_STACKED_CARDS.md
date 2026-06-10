# TZ: Admin UI — wide stacked pipeline cards, no log-like pipeline

Date: 2026-06-10
Status: ready for coder
Priority: P1 operator UX follow-up
Scope: admin UI only
Supersedes:
- `docs/work/TZ_ADMIN_UI_PIPELINE_STAGE_CARDS_NOT_LOG.md`
- `docs/work/TZ_ADMIN_UI_PIPELINE_STAGE_BLOCKS_FINAL.md`

## 1. Problem

The current pipeline UI is still not acceptable.

It technically contains stage data, but visually it still looks like a compact terminal/log dump:

```text
✓ Materialized Done
10:43:32 → 10:43:32 · 54m 31s · p1
✓ Executor selected Done
10:43:33 → 10:43:33 · 54m 31s · executor
● Coder run Running
10:43:33 → now · 45s · live-wr-1176011
○ Reviewer gate Pending
—
○ Merge Pending
—
— Skipped stages Skipped
T0 scope/lint, T1 tests, T2 smoke/e2e, Evidence verifier
```

This is not a readable operator UI.

The user asked for something simpler:

```text
Do not redesign everything.
Use the same stage blocks/cards if needed.
Just put them one under another, make the column wide, and write fields inside the block clearly.
```

## 2. Goal

Make the pipeline human-readable by rendering each meaningful stage as a **wide, separate, stacked card**.

Each stage card must be a visually bounded block with:

```text
Header row:   icon + stage name + status badge
Details row:  labelled facts: Time, Duration/Elapsed, Worker/Meta
```

Target shape:

```text
PIPELINE

┌────────────────────────────────────────────────────────────────────────────┐
│ ✓ Materialized                                                   [Done]     │
│ Time      10:43:32 → 10:43:32                                             │
│ Duration  0s                                                               │
│ Meta      p1                                                               │
└────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│ ✓ Executor selected                                              [Done]     │
│ Time      10:43:33 → 10:43:33                                             │
│ Duration  0s                                                               │
│ Meta      executor                                                         │
└────────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────────┐
│ ● Coder run                                                   [Running]     │
│ Time      10:43:33 → now                                                   │
│ Elapsed   45s                                                              │
│ Worker    live-wr-1176011                                                  │
└────────────────────────────────────────────────────────────────────────────┘
```

For terminal cancelled:

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ ✕ Final state                                             [Cancelled]      │
│ State     cancelled                                                        │
└────────────────────────────────────────────────────────────────────────────┘
```

For skipped NORMAL stages:

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ — Skipped by NORMAL profile                                  [Skipped]     │
│ Stages    T0 scope/lint · T1 tests · T2 smoke/e2e · Evidence verifier      │
└────────────────────────────────────────────────────────────────────────────┘
```

## 3. Non-goals

Do not change packet lifecycle.
Do not change worker lifecycle.
Do not change health/watchdog.
Do not change agent execution.
Do not change backend state semantics.
Do not introduce React/Vite/frontend build.
Do not redesign the whole admin page.

This is a Jinja/CSS display patch.

## 4. Required implementation approach

### 4.1 Use stacked cards, not table, not log text

Use a vertical container:

```html
<div class="pipeline-card-list">
  <div class="pipeline-card ...">...</div>
  <div class="pipeline-card ...">...</div>
</div>
```

CSS:

```css
.pipeline-card-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
```

Each stage card must occupy the full available width of the pipeline panel.

Do **not** render the pipeline as:

```html
<div>✓ Materialized <span>Done</span></div>
<div>10:43:32 → 10:43:32 · 45s · p1</div>
```

That is still a log.

### 4.2 Card layout must be explicit

Each card should have this structure or equivalent:

```html
<div class="pipeline-card is-running" hx-get="...">
  <div class="pipeline-card-head">
    <div class="pipeline-card-title">
      <span class="pipeline-card-icon">●</span>
      <span class="pipeline-card-name">Coder run</span>
    </div>
    <span class="pipeline-card-status badge severity-ok">Running</span>
  </div>

  <div class="pipeline-card-body">
    <div class="pipeline-fact">
      <span class="pipeline-fact-label">Time</span>
      <span class="pipeline-fact-value mono">10:43:33 → now</span>
    </div>
    <div class="pipeline-fact">
      <span class="pipeline-fact-label">Elapsed</span>
      <span class="pipeline-fact-value mono">45s</span>
    </div>
    <div class="pipeline-fact">
      <span class="pipeline-fact-label">Worker</span>
      <span class="pipeline-fact-value mono">live-wr-1176011</span>
    </div>
  </div>
</div>
```

Use actual existing row variables; class names may differ only if the rendered UI matches.

### 4.3 Facts must be labelled

Do not write:

```text
10:43:33 → now · 45s · live-wr-1176011
```

inside a single line as the only detail.

Write labelled rows:

```text
Time      10:43:33 → now
Elapsed   45s
Worker    live-wr-1176011
```

or a labelled grid:

```text
Time: 10:43:33 → now      Elapsed: 45s      Worker: live-wr-1176011
```

Labels are required because the operator is scanning under stress.

### 4.4 Do not color the whole text green/red

Use color only for:

- left border;
- icon;
- badge.

Main text must use normal foreground colors.

Bad:

```text
✓ Materialized Done
10:43:32 → 10:43:32 · 45s · p1
```

all bright green.

Good:

```text
✓ Materialized                                      [Done]
Time      10:43:32 → 10:43:32
Duration  0s
Meta      p1
```

where only `✓`, badge, and left border are green.

### 4.5 Hide unreached pending stages in terminal states

When packet is terminal, unreached pending stages like Reviewer gate and Merge must not appear as full cards.

For cancelled terminal packet, show:

```text
Materialized
Executor selected
Coder run
Final state: Cancelled
Skipped by NORMAL profile
```

Do not show big rows/cards for:

```text
Reviewer gate Pending
Merge Pending
```

Optional small muted collapsed line is acceptable:

```text
Not reached: Reviewer gate · Merge
```

but it must be visually secondary.

### 4.6 Running packet behavior

For running packet, show reached stages and the current running stage.

Example:

```text
✓ Materialized [Done]
Time      11:45:16 → 11:45:16
Duration  0s
Meta      p1

✓ Executor selected [Done]
Time      11:45:17 → 11:45:17
Duration  0s
Meta      executor

● Coder run [Running]
Time      11:45:17 → now
Elapsed   45s
Worker    live-wr-1176011

— Skipped by NORMAL profile [Skipped]
Stages    T0 scope/lint · T1 tests · T2 smoke/e2e · Evidence verifier
```

Do not show Reviewer/Merge pending as prominent full cards while Coder run is running.

### 4.7 Correct duration rules

This is mandatory.

Completed instant stages must show `0s`, not packet elapsed.

Rules:

```text
if stage.status == running:
    label = Elapsed
    value = now - started_at
elif stage.started_at and stage.finished_at:
    label = Duration
    value = finished_at - started_at
elif stage.duration_ms is available:
    label = Duration
    value = duration_ms
else:
    value = —
```

Do not use packet-level elapsed as fallback for individual completed stage duration.

Bad current behavior:

```text
Materialized 10:43:32 → 10:43:32 · 54m 31s
Executor selected 10:43:33 → 10:43:33 · 54m 31s
```

Correct:

```text
Materialized 10:43:32 → 10:43:32 · 0s
Executor selected 10:43:33 → 10:43:33 · 0s
```

## 5. Concrete CSS target

Use or adapt this exact shape:

```css
.pipeline-card-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.pipeline-card {
  width: 100%;
  box-sizing: border-box;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-left: 4px solid var(--border-2);
  border-radius: 8px;
  padding: 10px 12px;
}

.pipeline-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.pipeline-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.pipeline-card-icon {
  width: 18px;
  flex: 0 0 18px;
  text-align: center;
}

.pipeline-card-name {
  color: var(--fg);
  font-size: 13px;
  font-weight: 650;
}

.pipeline-card-status {
  flex: 0 0 auto;
}

.pipeline-card-body {
  margin-top: 8px;
  padding-left: 26px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px 16px;
}

.pipeline-fact {
  min-width: 0;
}

.pipeline-fact-label {
  display: block;
  color: var(--fg-muted);
  text-transform: uppercase;
  font-size: 10px;
  letter-spacing: .04em;
  margin-bottom: 2px;
}

.pipeline-fact-value {
  color: var(--fg-2);
  font-size: 12px;
}

.pipeline-fact-value.mono {
  white-space: nowrap;
}

.pipeline-card.is-done { border-left-color: var(--sev-ok-soft); }
.pipeline-card.is-running { border-left-color: var(--accent); }
.pipeline-card.is-cancelled,
.pipeline-card.is-rejected,
.pipeline-card.is-failed { border-left-color: var(--sev-crit); }
.pipeline-card.is-skipped,
.pipeline-card.is-pending { border-left-color: var(--border-2); opacity: .86; }
```

Responsive fallback:

```css
@media (max-width: 1100px) {
  .pipeline-card-body {
    grid-template-columns: 1fr;
  }
}
```

## 6. Template target

The pipeline section should look like this structurally:

```jinja2
<section class="pipeline-view">
  <h2 class="pipeline-h">PIPELINE</h2>
  <div class="pipeline-card-list">
    {% for row in pipeline_rows %}
      <div class="pipeline-card is-{{ row.status_key }} severity-{{ row.severity }}"
           {% if row.target_tab %}hx-get="..." hx-target="#packet-tab-content" hx-swap="outerHTML" hx-push-url="..."{% endif %}>
        <div class="pipeline-card-head">
          <div class="pipeline-card-title">
            <span class="pipeline-card-icon">{{ row.icon }}</span>
            <span class="pipeline-card-name">{{ row.label }}</span>
          </div>
          <span class="pipeline-card-status badge severity-{{ row.severity }}">{{ row.status_label }}</span>
        </div>
        <div class="pipeline-card-body">
          {% for fact in row.facts %}
            <div class="pipeline-fact">
              <span class="pipeline-fact-label">{{ fact.label }}</span>
              <span class="pipeline-fact-value {{ 'mono' if fact.mono else '' }}">{{ fact.value }}</span>
            </div>
          {% endfor %}
        </div>
      </div>
    {% endfor %}
  </div>
</section>
```

If there is no `pipeline_rows` DTO yet, build the rows in a small template helper/filter. Keep it deterministic and tested.

## 7. Required visible rows

### Running packet example

For a running packet in coder stage, visible cards should be:

```text
Materialized [Done]
Executor selected [Done]
Coder run [Running]
Skipped by NORMAL profile [Skipped]
```

Do not show Reviewer gate / Merge as prominent pending cards.

### Cancelled packet example

For cancelled packet after coder run, visible cards should be:

```text
Materialized [Done]
Executor selected [Done]
Coder run [Done or Failed/Cancelled depending data]
Final state [Cancelled]
Skipped by NORMAL profile [Skipped]
```

Optional small secondary line:

```text
Not reached: Reviewer gate · Merge
```

## 8. Tests required

### 8.1 Structure test

Rendered packet detail HTML must contain:

```text
pipeline-card-list
pipeline-card
pipeline-card-head
pipeline-card-body
pipeline-fact-label
pipeline-fact-value
```

### 8.2 No log layout test

Rendered HTML must not use the old plain layout as primary pipeline rendering.

Reject if stage values are rendered as consecutive naked lines without `pipeline-card` wrappers.

### 8.3 Instant stage duration test

For a stage where `started_at == finished_at`, assert rendered duration is:

```text
0s
```

not packet elapsed.

### 8.4 Running stage test

For a running coder stage, assert rendered card contains:

```text
Coder run
Running
Time
→ now
Elapsed
Worker
```

### 8.5 Terminal cancelled test

For cancelled packet, assert rendered detail contains:

```text
Final state
Cancelled
State
cancelled
```

and does not show Reviewer/Merge as prominent full pending cards.

### 8.6 Skipped NORMAL test

Assert one collapsed card contains:

```text
Skipped by NORMAL profile
T0 scope/lint
T1 tests
T2 smoke/e2e
Evidence verifier
```

## 9. Acceptance criteria

Do not accept unless screenshot/live UI shows:

1. Pipeline is not a text log.
2. Each meaningful stage is a separate wide card/block.
3. Cards are stacked vertically and fill the pipeline panel width.
4. Stage name and status are in the card header.
5. Time/Duration/Worker/Meta are labelled facts inside the card.
6. Green/red is used only as accent, not for all text.
7. Completed instant stages show `0s`.
8. Running stage shows `→ now` and elapsed.
9. Unreached pending stages do not dominate the view.
10. Skipped NORMAL stages are collapsed.
11. Current Run block remains intact.
12. Tests pass.

## 10. Visual rejection examples

Reject if it still looks like:

```text
✓ Materialized Done
10:43:32 → 10:43:32 · 54m 31s · p1
✓ Executor selected Done
10:43:33 → 10:43:33 · 54m 31s · executor
```

Reject if it still looks like:

```text
Done
Materialized
10:43:32 → 10:43:32
54m 31s
p1
```

Reject if successful rows are entirely bright green.

Accept if it looks like:

```text
[wide card]
✓ Materialized                                      [Done]
Time      10:43:32 → 10:43:32
Duration  0s
Meta      p1

[wide card]
● Coder run                                        [Running]
Time      10:43:33 → now
Elapsed   45s
Worker    live-wr-1176011
```

## 11. Reviewer note

This must be reviewed by screenshot/live UI, not only by test pass.

The operator question is:

```text
Can I understand the packet story in 3 seconds?
```

If no, reject.
