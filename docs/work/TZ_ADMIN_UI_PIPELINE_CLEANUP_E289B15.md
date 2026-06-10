# TZ: Cleanup for admin UI pipeline cards after `e289b15`

Date: 2026-06-10
Status: ready for coder
Priority: P1 cleanup before UX acceptance
Scope: admin UI pipeline + commit hygiene
Related implementation: `e289b158db8bda2801d13c4cae86397e9b911e9f`
Related TZ: `docs/work/TZ_ADMIN_UI_PIPELINE_WIDE_STACKED_CARDS.md`

## 1. Current status

The direction in `e289b15` is now mostly correct.

The pipeline template was changed to real wide stacked cards:

```text
pipeline-card-list
pipeline-card
pipeline-card-head
pipeline-card-body
pipeline-fact-label
pipeline-fact-value
```

This is the right UI direction and should be kept.

However, the patch still needs cleanup before acceptance.

## 2. Problems to fix

### 2.1 Non-UI changes leaked into UI commit

The `e289b15` diff includes files outside the admin UI pipeline task:

```text
scripts/api_watchdog.py
tests_live/runner/wave_resume_runner.py
```

This TZ is about admin UI only. Watchdog and live-runner behavior must not be changed as a side-effect of a UI patch.

Required:

- Either revert those changes from the UI patch/follow-up;
- or move them to a separate explicitly named commit/TZ with its own reason and tests.

For this admin UI cleanup, preferred action: **revert unrelated watchdog/runner changes**.

### 2.2 Duplicate `duration_label` assignment

In `pipeline_visible_rows`, `duration_label` is assigned twice in a row:

```python
row["duration_label"] = _pipeline_duration(...)
row["duration_label"] = _pipeline_duration(...)
```

Required:

- Remove the duplicate assignment.
- Add/keep a small test if existing coverage is nearby, or rely on current pipeline tests if already enough.

### 2.3 Pending Reviewer/Merge still appear as prominent cards

`pipeline_visible_rows` currently appends all non-skipped stages, including pending stages.

For running packets, `Reviewer gate Pending` and `Merge Pending` should not appear as full prominent cards. They were not reached yet and add noise.

For terminal packets, unreached pending Reviewer/Merge cards are even more confusing.

Required behavior:

- Do not render unreached pending stages as full cards.
- Specifically hide or collapse pending `reviewer` and `merge` stages when they are not reached.
- Optional: show one small secondary collapsed card/line:

```text
Not reached
Reviewer gate · Merge
```

But default preferred behavior: **hide them**.

Keep pending stages only if they are truly the current active meaningful stage. In current data, the active running stage is `Coder run`, so reviewer/merge pending should be hidden.

### 2.4 Skipped NORMAL block should be visually secondary and labelled clearly

Current collapsed skipped row is acceptable in concept, but label should be more human-friendly:

Preferred:

```text
Skipped by NORMAL profile
Stages: T0 scope/lint · T1 tests · T2 smoke/e2e · Evidence verifier
```

Instead of a generic:

```text
Skipped stages
```

Required:

- Rename collapsed skipped row label to `Skipped by NORMAL profile`.
- Use `Stages` as the fact label instead of `Meta` if easy.
- Keep it muted/secondary.

### 2.5 Worker/Meta label is too broad

Current template labels meta as `Worker` for any row with status in `running/done/failed`:

```jinja2
{{ 'Worker' if row.status in ('running', 'done', 'failed') else 'Meta' }}
```

That can mislabel `p1` or `executor` as `Worker`.

Required:

- Add explicit `meta_label` to pipeline row DTO/helper.
- Examples:

```text
Materialized:        meta_label = Meta,   meta = p1
Executor selected:   meta_label = Meta,   meta = executor
Coder run:           meta_label = Worker, meta = live-wr-...
Skipped NORMAL:      meta_label = Stages, meta = T0/T1/T2/verifier
Final state:         meta_label = State,  meta = cancelled/rejected/etc.
```

Do not infer label from only status.

## 3. Required implementation details

### 3.1 Keep current wide-card structure

Do not go back to horizontal cards or plain text.

Keep this structure:

```html
<div class="pipeline-card-list">
  <div class="pipeline-card ...">
    <div class="pipeline-card-head">...</div>
    <div class="pipeline-card-body">...</div>
  </div>
</div>
```

### 3.2 Update `pipeline_visible_rows`

Rules:

```text
for each stage:
  if status == skipped and stage is NORMAL profile stage:
      collect into skipped_normal list
      continue

  if status == pending and key in reviewer/merge and not current active stage:
      collect into not_reached list or skip
      continue

  append meaningful row

if skipped_normal:
  append muted row label='Skipped by NORMAL profile', meta_label='Stages'

if packet_state is terminal and not already obvious:
  append terminal row label='Final state', meta_label='State'
```

### 3.3 Add `meta_label`

Each pipeline row should include:

```python
{
  "label": "Coder run",
  "status": "running",
  "status_label": "Running",
  "time_range": "11:45:17 → now",
  "duration_label": "45s",
  "meta_label": "Worker",
  "meta": "live-wr-1176011",
  ...
}
```

Template should render:

```jinja2
<span class="pipeline-fact-label">{{ row.meta_label or 'Meta' }}</span>
```

not derive it from status.

## 4. Tests required

Keep the existing 893-passing suite and add/update focused tests.

### 4.1 No prominent pending reviewer/merge cards

For running packet where current stage is `Coder run`, assert rendered pipeline does **not** show prominent full cards for:

```text
Reviewer gate Pending
Merge Pending
```

If a collapsed `Not reached` row is implemented, assert it is secondary and contains:

```text
Not reached
Reviewer gate
Merge
```

### 4.2 Skipped NORMAL label

Assert collapsed skipped row includes:

```text
Skipped by NORMAL profile
Stages
T0 scope/lint
T1 tests
T2 smoke/e2e
Evidence verifier
```

### 4.3 Meta labels are correct

Assert rendered facts include appropriate labels:

```text
Materialized -> Meta: p1
Coder run -> Worker: live-wr-...
Final state -> State: cancelled
Skipped -> Stages: T0/T1/T2/verifier
```

### 4.4 Duration regression

Keep or add assertion that instant completed stages render:

```text
Duration 0s
```

not packet elapsed.

### 4.5 Commit hygiene / changed files

Manual review check:

This cleanup commit should not change:

```text
scripts/api_watchdog.py
tests_live/runner/wave_resume_runner.py
```

unless a separate non-UI task explicitly requires it.

## 5. Acceptance criteria

Accepted when:

1. `pipeline-card-list` wide stacked UI remains.
2. Pending unreached Reviewer/Merge do not appear as prominent cards.
3. Collapsed skipped row is labelled `Skipped by NORMAL profile`.
4. Pipeline row metadata has explicit labels: Meta / Worker / State / Stages.
5. Duplicate `duration_label` assignment is removed.
6. Completed instant stages still show `0s`.
7. No unrelated watchdog/runner changes are included in the UI cleanup.
8. Tests pass.
9. Live screenshot is readable in 3 seconds.

## 6. Reviewer note

The `e289b15` direction should not be thrown away. It is close.

This task is cleanup and acceptance-hardening:

```text
keep the wide cards
remove noise
fix labels
remove unrelated changes
```
