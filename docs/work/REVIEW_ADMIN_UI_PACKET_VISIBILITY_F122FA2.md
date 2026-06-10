# Review: Admin UI packet visibility and timing (`f122fa2`)

Date: 2026-06-10
Reviewer: ChatGPT
Commit reviewed: `f122fa276dd45d5b7a9074a2515a8613a5c73d35`
Task: `docs/work/TZ_ADMIN_UI_PACKET_VISIBILITY_AND_TIMING.md`

## Verdict

**PARTIAL / needs follow-up before accepting as UX-complete.**

The patch is scoped correctly: it changes only UI/template/filter/CSS files and does not touch backend lifecycle or control-plane behavior.

It does add useful information:

- packet cards in the left pane now show stage, attempt, started time, duration;
- selected packet detail now has a `CURRENT RUN` block;
- pipeline cards now show some timing/meta;
- new filters were added for elapsed time and stage selection.

However, the original UX pain is not fully solved yet:

1. Left-pane packet text is still very small and muted (`11px` base, `10px` metadata), so the task may still be hard to see.
2. `finished` is derived from `packet.updated_at`, not the actual last run `finished_at`.
3. Pipeline cards still do not clearly show `started → finished/now` and elapsed for running stages.
4. Required tests/template smoke were not added.

## Scope reviewed

Changed files:

```text
src/grace_control/ui/admin_template_filters.py
src/grace_control/ui/static/admin.css
src/grace_control/ui/templates/admin/_detail.html
src/grace_control/ui/templates/admin/_master.html
```

No backend/service/state-machine files were changed. That part matches the intended boundary.

## Positive findings

### 1. Backend lifecycle was not touched

The diff is limited to UI templates, CSS and Jinja filters. This is good: the task was operator UX only, not lifecycle behavior.

### 2. Left pane got more packet metadata

`_master.html` now renders packet title plus stage, attempt, started time, duration and size:

```html
<span class="pkt-title">{{ p.title or p.slug or p.id }}</span>
<span class="pkt-stage muted">{{ p.stage.label or '—' }}</span>
<span class="pkt-attempts muted">{{ p.attempt_count }}/{{ p.max_attempts }}</span>
{% if p.started_at %}<span class="pkt-time muted">{{ p.started_at | fmt_time_short }}</span>{% endif %}
{% if p.duration_seconds %}<span class="pkt-duration muted">{{ p.duration_seconds | fmt_duration }}</span>{% endif %}
```

This is directionally correct.

### 3. Current Run block was added

`_detail.html` now renders a dedicated `CURRENT RUN` block with:

```text
attempt
state
worker
model
started
elapsed
finished
stage
```

This directly addresses part of the requested operator summary.

### 4. `/detail` now has more visible timing metadata

The selected packet metadata block already shows:

```text
started
finished
duration
attempt
worker
```

This helps even before opening sub-tabs.

### 5. New elapsed-time filter is useful

`fmt_elapsed_since()` computes live elapsed time from an ISO timestamp to now. This is useful for running packets.

## Findings

### MAJOR 1 — Left pane may still be too small and low-contrast

The original user complaint was that the packet existed but was almost invisible in the left pane.

The new CSS still sets:

```css
.tn-packet {
  font-size: 11px;
  color: var(--fg-2);
}
.tn-packet .pkt-stage,
.tn-packet .pkt-attempts,
.tn-packet .pkt-time,
.tn-packet .pkt-duration {
  font-size: 10px;
}
```

And the template renders important values with `muted`:

```html
<span class="pkt-stage muted">...</span>
<span class="pkt-attempts muted">...</span>
<span class="pkt-time muted">...</span>
<span class="pkt-duration muted">...</span>
```

That likely preserves the main UX problem: the task is technically there, but visually weak.

Required follow-up:

- Make selected/running packet title larger and higher contrast.
- Avoid `muted` for critical values on running packet cards.
- Use a visible status badge or stronger dot for running/failed states.
- Consider a two-line layout instead of squeezing everything into 10px inline text.

Suggested target:

```text
Title: 13-14px, fg
Status: visible badge
Meta: 11-12px, readable fg-2, not ultra-muted
Selected: stronger background + border
Running: visible accent
```

### MAJOR 2 — `finished` uses `packet.updated_at`, not run `finished_at`

In `_detail.html`:

```jinja2
{% set p_finished = p.packet.updated_at if p.packet else None %}
```

This is not semantically correct. `updated_at` means the packet row was updated. It is not necessarily the time when the current/last run finished.

This can show misleading finish time after retries, cancellation, state cleanup, manual edits, or other packet updates.

Required follow-up:

- Expose last run `finished_at` from `AdminAggregationService` packet detail DTO.
- Use that value in the template:

```text
p_finished = p.finished_at / last_run.finished_at
```

The detail DTO already derives `started_at` and `elapsed_seconds` from `last_run`; it should also expose `finished_at` directly.

### MAJOR 3 — Running duration is still split between two places

The top metadata block shows this for running packets:

```jinja2
{% if p_duration %}{{ p_duration | fmt_duration }}
{% elif p_started and p_state == 'running' %}running…
{% else %}—{% endif %}
```

So the first timing block can still show only `running…`, while the actual elapsed value appears lower in `CURRENT RUN`.

The task asked that elapsed/duration be impossible to miss. Splitting it like this weakens the UX.

Required follow-up:

- In the first metadata block, show the same elapsed value as `CURRENT RUN`:

```jinja2
{% if p.is_running and p_started %}{{ p_started | fmt_elapsed_since }}
{% elif p_duration %}{{ p_duration | fmt_duration }}
{% else %}—{% endif %}
```

- Prefer label `elapsed` for running and `duration` for finished, or show both clearly.

### MAJOR 4 — Pipeline cards still do not show clear `started → now/finished`

Pipeline card metadata now shows `s.meta`, `started_at`, and `duration_ms` when present:

```jinja2
{% if s.meta %}<span>{{ s.meta }}</span>{% endif %}
{% if s.started_at and s.status != 'skipped' and s.status != 'pending' %}
  <span class="muted small"> · {{ s.started_at | fmt_time_short }}</span>
{% endif %}
{% if s.duration_ms and s.duration_ms > 0 %}
  <span class="muted small"> · {{ s.duration_ms | fmt_duration_ms }}</span>
{% endif %}
```

This is better than before, but still not the requested compact timeline:

```text
Coder run
Running
10:29:06 → now
31m 42s
```

Required follow-up:

- For running stage, show `started → now` and elapsed.
- For finished stage, show `started → finished` if `finished_at` is known.
- If `finished_at` is not available in stage DTO, expose it in the aggregation layer.
- Keep `s.meta` as a short secondary line, not the main content.

### MAJOR 5 — No tests were added

The task required at least minimal tests for:

- admin aggregation timing fields;
- finished packet duration;
- template smoke with `CURRENT RUN`, `Started`, `Elapsed/Duration`, `Attempt`, `Worker`.

This patch changed 4 UI files and added no tests.

Required follow-up:

- Add one template smoke test for selected packet detail.
- Add one aggregation DTO test ensuring `finished_at` is exposed from last run.
- Add one filter test for `fmt_elapsed_since` if there is an existing filter test file.

### MINOR 1 — `last_skippable_stage` name is confusing

The filter returns the last non-skipped/non-pending stage, but the name `last_skippable_stage` reads like “last stage that can be skipped”.

Prefer:

```text
last_active_stage
last_reached_stage
last_non_pending_stage
```

Not a blocker.

### MINOR 2 — `last_skippable_stage` docstring says “or first stage” but code returns last stage

Docstring:

```text
return the last non-skipped stage, or the first stage
```

Code:

```python
return stages[-1] if stages else None
```

Fix either docstring or behavior.

### MINOR 3 — `fmt_elapsed_since` docstring examples do not match output

Docstring says it returns `00:31:42` or `5m 12s`, but implementation never returns `HH:MM:SS`; it returns compact `1h 2m`, `5m 12s`, or `12s`.

Not a blocker, but update the docstring.

## Acceptance criteria check

| Criterion | Status |
|---|---|
| Running packet visually obvious in left pane | PARTIAL — more fields added, but still too small/muted |
| Selected packet summary header with status/timing/attempt/worker | PARTIAL — added, but not at top enough and finished source wrong |
| Pipeline cards readable with status/timing/meta | PARTIAL — some timing, but not `start → now/finish` |
| Current run understandable without opening tabs | PARTIAL/PASS — block exists, but should use correct finished time |
| Existing admin tabs still work | PASS by inspection; no tab code removed |
| No lifecycle/control-plane behavior changed | PASS |
| Tests pass / tests added | FAIL — no tests added in this patch |

## Required follow-up patch

Minimum follow-up to accept as UX-complete:

1. Expose `finished_at` from last `PacketRun` in `AdminAggregationService.get_packet_detail()`.
2. Use `last_run.finished_at`, not `packet.updated_at`, for the detail finished timestamp.
3. Show running elapsed in the top timing metadata block, not only in `CURRENT RUN`.
4. Increase left-pane packet card readability:
   - larger title;
   - stronger selected/running state;
   - avoid muted 10px for critical timing/status.
5. Improve pipeline cards for active/running stage:
   - show `started → now`;
   - show elapsed prominently.
6. Add minimal tests:
   - template smoke for `/admin?packet_id=...` contains `CURRENT RUN`, `Started`, `Elapsed`/`Duration`, `Attempt`, `Worker`;
   - aggregation test for finished_at from last run.

## Final decision

Do not reject the whole direction. The patch is a useful first pass and keeps backend behavior safe.

But do not mark the admin UX task complete yet. The user complaint was specifically about visibility and operational clarity during a live run, and this patch still risks leaving key data too small/muted and partly semantically wrong.
