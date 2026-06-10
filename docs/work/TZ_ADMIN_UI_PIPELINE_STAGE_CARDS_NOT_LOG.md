# TZ: Admin UI — fix pipeline timeline so it is stage cards, not plain-text log

Date: 2026-06-10
Status: ready for coder
Priority: P1 operator UX follow-up
Scope: admin UI readability only
Depends on:
- `docs/work/TZ_ADMIN_UI_PACKET_VISIBILITY_AND_TIMING.md`
- `docs/work/TZ_ADMIN_UI_VERTICAL_PIPELINE_TIMELINE.md`

Current implementation commit observed: `fbeedf7`

## 1. Problem

The vertical pipeline implementation technically satisfies the data requirements, but visually it is not acceptable.

Current live UI looks like a plain-text log:

```text
Done
Materialized
10:43:32 → 10:43:32
41m 51s
p1
Done
Executor selected
10:43:33 → 10:43:33
41m 50s
executor
Done
Coder run
10:43:33 → 10:45:42
2m 9s
live-wr-1133292
...
```

This is hard to scan because fields are stacked as unrelated lines. The operator cannot quickly read:

```text
stage → status → time range → duration → meta
```

The result should not look like terminal output or raw logs. It should look like UI rows/cards.

## 2. Goal

Render pipeline as readable **vertical stage cards** or a real table. Preferred solution: vertical stage cards.

Each stage must be one visual unit:

```text
✓ Materialized                         [Done]
  10:43:32 → 10:43:32 · 0s · p1

✓ Executor selected                    [Done]
  10:43:33 → 10:43:33 · 0s · executor

✓ Coder run                            [Done]
  10:43:33 → 10:45:42 · 2m 9s · live-wr-1133292

✕ Final state                          [Cancelled]
  cancelled

— Skipped stages                        [Skipped]
  NORMAL profile · T0 scope/lint, T1 tests, T2 smoke/e2e, Evidence verifier
```

Alternative acceptable table form:

```text
Status      Stage               Time range                Duration     Meta
Done        Materialized         10:43:32 → 10:43:32       0s           p1
Done        Executor selected    10:43:33 → 10:43:33       0s           executor
Done        Coder run            10:43:33 → 10:45:42       2m 9s        live-wr-1133292
Cancelled   Final state          —                         —            cancelled
Skipped     Skipped stages       —                         —            NORMAL profile · T0/T1/T2/verifier
```

Do not render fields as separate vertical text lines without layout.

## 3. Non-goals

Do not change lifecycle semantics.
Do not change worker/packet state transitions.
Do not change health/watchdog.
Do not change agent execution.
Do not redesign the whole admin console.
Do not introduce React or a frontend build step.

This is a template/CSS/readability patch. Minimal read DTO/filter changes are allowed only if needed for display.

## 4. Required visual behavior

### 4.1 One stage = one card or one table row

For each pipeline row, the following fields must appear as one connected visual record:

```text
icon/status + stage label + status badge + time range + duration + meta
```

Bad:

```text
Done
Materialized
10:43:32 → 10:43:32
41m 51s
p1
```

Good:

```text
✓ Materialized    [Done]
  10:43:32 → 10:43:32 · 0s · p1
```

or:

```text
Done | Materialized | 10:43:32 → 10:43:32 | 0s | p1
```

### 4.2 Preferred design: vertical stage cards

Implement `.pipeline-stage-card` rows:

```html
<div class="pipeline-stage-card pipeline-stage-done">
  <div class="pipeline-stage-main">
    <span class="pipeline-stage-icon">✓</span>
    <span class="pipeline-stage-label">Materialized</span>
    <span class="pipeline-stage-status badge">Done</span>
  </div>
  <div class="pipeline-stage-sub mono">
    <span>10:43:32 → 10:43:32</span>
    <span>0s</span>
    <span>p1</span>
  </div>
</div>
```

Exact class names may differ, but the structure should be equivalent.

### 4.3 Do not color all row text green/red

Current view makes all successful stage text bright green. This makes the whole pipeline look like console output.

Required:

- use color on left border/icon/status badge;
- keep main text normal foreground;
- use subtle green/red only for status indicator;
- meta/timing should be readable but not neon.

Bad:

```text
Done
Materialized
10:43:32 → 10:43:32
```

all in bright green.

Good:

```text
✓ Materialized [Done]
```

where only `✓` / badge / border is green.

### 4.4 Time range and duration must be visually grouped

For every non-skipped stage, show:

```text
10:43:33 → 10:45:42 · 2m 9s
```

For running stage:

```text
10:43:33 → now · 41m 50s
```

For skipped/pending:

```text
—
```

Do not place time range and duration as unrelated separate lines unless they are still visibly inside the same card.

### 4.5 Skipped stages remain one muted card

NORMAL profile skipped stages must be one muted card:

```text
— Skipped stages [Skipped]
  NORMAL profile · T0 scope/lint, T1 tests, T2 smoke/e2e, Evidence verifier
```

Not four large rows. Not bright green/red.

### 4.6 Terminal state is separate and visually clear

For cancelled packet, show:

```text
✕ Final state [Cancelled]
  cancelled
```

For rejected/failed:

```text
✕ Final state [Rejected]
  rejected
```

For accepted/merged:

```text
✓ Final state [Accepted]
  accepted
```

Do not leave the operator with pending Reviewer/Merge rows that visually contradict packet state.

### 4.7 Keep click behavior

If the previous row had `hx-get` to open a tab, preserve the behavior on the new card/row.

Click targets:

- Coder run → Attempts or existing target tab;
- Evidence/test stages → Evidence;
- Reviewer/terminal → Events or existing target tab;
- Skipped stages may be non-clickable or open Evidence.

## 5. Suggested CSS

Preferred stage card layout:

```css
.pipeline-stage-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.pipeline-stage-card {
  border: 1px solid var(--border);
  border-left: 3px solid var(--border-2);
  border-radius: 8px;
  background: var(--bg-2);
  padding: 9px 12px;
}

.pipeline-stage-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.pipeline-stage-icon {
  width: 18px;
  flex: 0 0 18px;
  text-align: center;
}

.pipeline-stage-label {
  font-weight: 600;
  color: var(--fg);
  min-width: 0;
}

.pipeline-stage-status {
  margin-left: auto;
  flex: 0 0 auto;
}

.pipeline-stage-sub {
  margin-top: 4px;
  padding-left: 26px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  color: var(--fg-2);
  font-size: 12px;
}

.pipeline-stage-card.is-done { border-left-color: var(--sev-ok-soft); }
.pipeline-stage-card.is-running { border-left-color: var(--accent); }
.pipeline-stage-card.is-failed,
.pipeline-stage-card.is-cancelled { border-left-color: var(--sev-crit); }
.pipeline-stage-card.is-skipped,
.pipeline-stage-card.is-pending { border-left-color: var(--border-2); }
```

Important:

- no `text-overflow: ellipsis` on timestamp/duration;
- no 5 independent lines per stage;
- no neon green whole text block.

## 6. Template guidance

Replace current pipeline plaintext/grid output with card rows.

Pseudo-Jinja:

```jinja2
<section class="pipeline-view">
  <h2 class="pipeline-h">Pipeline</h2>
  <div class="pipeline-stage-list">
    {% for row in pipeline_rows %}
      <div class="pipeline-stage-card is-{{ row.status }}"
           {% if row.clickable %}hx-get="..." hx-target="#packet-tab-content" ...{% endif %}>
        <div class="pipeline-stage-main">
          <span class="pipeline-stage-icon">{{ row.icon }}</span>
          <span class="pipeline-stage-label">{{ row.label }}</span>
          <span class="pipeline-stage-status badge severity-{{ row.severity }}">{{ row.status_label }}</span>
        </div>
        <div class="pipeline-stage-sub mono">
          {% if row.time_range %}<span>{{ row.time_range }}</span>{% endif %}
          {% if row.duration %}<span>{{ row.duration }}</span>{% endif %}
          {% if row.meta %}<span>{{ row.meta }}</span>{% endif %}
        </div>
      </div>
    {% endfor %}
  </div>
</section>
```

Use actual data/filter names from current code.

## 7. Tests required

Keep existing tests from `fbeedf7`, but add/adjust assertions so the bad current rendering cannot pass.

### 7.1 Assert card/table structure exists

Template smoke should assert HTML contains one of:

```text
pipeline-stage-card
```

or:

```text
pipeline-row
```

but not only naked text blocks.

### 7.2 Assert stage fields are grouped in one row/card

For a known stage, assert same card/row contains:

```text
Materialized
Done
10:43
```

Do not require exact timestamp if brittle; use stable fixture values if available.

### 7.3 Assert no neon full-text status class misuse

If practical, assert the main stage label is not rendered with severity color class directly. Severity should be on card/badge/icon, not all text.

### 7.4 Existing behavior still covered

Keep tests for:

- collapsed NORMAL skipped stages;
- cancelled terminal row;
- selected packet detail smoke;
- current run block.

## 8. Acceptance criteria

Accepted when:

1. Pipeline no longer looks like a plain-text log.
2. Each stage is a visually bounded card or real table row.
3. Stage label, status, time range, duration, and meta are grouped together.
4. Whole successful row text is not neon green.
5. Skipped NORMAL stages are one muted card/row.
6. Cancelled final state is one clear red/critical/attention card/row.
7. Timestamps and durations are readable without hover and without truncation.
8. Current Run block remains present.
9. Existing HTMX click behavior still works.
10. Tests pass.

## 9. Manual acceptance checklist

Open live admin page and inspect the selected packet.

Reject if pipeline still resembles:

```text
Done
Materialized
10:43 → 10:43
41m
p1
```

Accept if it resembles:

```text
✓ Materialized [Done]
  10:43:32 → 10:43:32 · 0s · p1

✓ Coder run [Done]
  10:43:33 → 10:45:42 · 2m 9s · live-wr-1133292

✕ Final state [Cancelled]
  cancelled
```

Reviewer should judge this by screenshot/live UI, not only by unit tests.
