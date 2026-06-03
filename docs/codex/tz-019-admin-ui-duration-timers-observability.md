# TZ 019 — Admin UI duration/timer observability for feature, wave, packet, attempts

Audience: Flash coder / literal executor.

Goal: make the admin UI useful for watching long-running GRACE work. The user must see, in a human-readable way, how long each feature/wave/packet/attempt has been running or took after completion/failure.

This is primarily an admin UI observability task. It must not change orchestration semantics, retries, acceptance, merge behavior, or safety gates.

---

## 0. Product requirement

The admin UI must answer these questions at a glance:

```text
How long has this feature been running?
How long has this wave been running?
How long has this packet been running?
How long did each attempt take, including failed attempts?
Where exactly is time being spent?
```

The UI must show both:

```text
1. live elapsed timers for currently running entities
2. final duration for completed/failed/cancelled entities and attempts
```

This is important because real golden/self-improvement/admin tasks may take many minutes, and repeated failures should not hide the time cost of earlier attempts.

---

## 1. Identity model reminder

The control plane now uses NanoID-style UIDs as canonical IDs:

```text
Feature.id = feat_<nanoid>
Wave.id    = wave_<nanoid>
Packet.id  = pkt_<nanoid>
```

Slugs/titles are display metadata only:

```text
Feature.slug
Wave.slug
Packet.slug
```

Admin UI links/actions/API calls must use UID fields.

The UI may display both:

```text
Title: Admin UI timers
Slug: admin-ui-timers
UID: feat_AbC123xYz9
```

Do not derive IDs from slugs/titles/order. Do not parse `W01`, `P01`, or `FEAT-...` from IDs.

---

## 2. Human-readable duration format

Add a shared helper for formatting durations.

Suggested file:

```text
src/grace_control/ui/time_format.py
```

or if there is already a UI helpers module, use that.

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

Russian pluralization can be simple but should be readable:

```text
1 секунда, 2 секунды, 5 секунд
1 минута, 2 минуты, 5 минут
1 час, 2 часа, 5 часов
1 день, 2 дня, 5 дней
```

If pluralization is too much for first patch, use neutral short units:

```text
1ч 12м 05с
26м 30с
```

But preferred UI text is full human-readable Russian:

```text
1 час 12 минут 05 секунд
26 минут 30 секунд
```

Do not show raw seconds as primary display.

---

## 3. Data model / timestamps needed

Audit existing schema first. Reuse existing timestamp fields if present.

Required logical timestamps:

### Feature

```text
created_at
started_at
finished_at
updated_at
```

### Wave

```text
created_at
started_at
finished_at
updated_at
```

### Packet

```text
created_at
started_at
finished_at
updated_at
```

### Packet attempt / run

```text
created_at
started_at
finished_at
attempt_number
status
executor_id/model if available
```

If exact fields already exist under different names, do not duplicate them. Add computed properties/API fields instead.

If some started/finished fields are missing, add them in the smallest safe way:

```text
started_at set when entity enters RUNNING / first packet in wave starts / first packet in feature starts
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

Do not make timestamp changes that alter state machine behavior.

---

## 4. Duration semantics

### 4.1 Completed duration

If entity has `started_at` and `finished_at`:

```text
duration_seconds = finished_at - started_at
```

Display:

```text
Длилось: 26 минут 30 секунд
```

### 4.2 Live duration

If entity has `started_at` but no `finished_at` and is active/running:

```text
elapsed_seconds = now - started_at
```

Display live updating timer:

```text
Идёт: 07 минут 12 секунд
```

### 4.3 Queued/waiting duration

If entity has `created_at` but no `started_at`:

```text
waiting_seconds = now - created_at
```

Display:

```text
Ожидает: 03 минуты 04 секунды
```

### 4.4 Failed attempt duration

Every failed attempt must show its own duration.

Example:

```text
Attempt #1 — failed — 7 минут 14 секунд
Attempt #2 — failed — 6 минут 59 секунд
Attempt #3 — accepted — 8 минут 03 секунды
```

Failed attempts must not be hidden behind the current packet total.

---

## 5. API response requirements

Add computed fields to existing admin/API endpoints used by the UI.

Do not break existing response fields.

Recommended fields for feature/wave/packet objects:

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

For attempts/runs:

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

If there is no admin-specific API and templates query DB directly, compute these values server-side before rendering.

---

## 6. Admin UI display requirements

### 6.1 Feature header

Feature detail page must show:

```text
Feature title
UID: feat_...
Slug: ...
Status: running / completed / blocked / failed
Started: 2026-06-03 21:10:12
Elapsed: 12 минут 08 секунд  ← live timer if active
Duration: 1 час 04 минуты 22 секунды  ← final if terminal
```

The elapsed timer must update live in the browser without page reload.

Simple JavaScript `setInterval(..., 1000)` is enough.

### 6.2 Wave section

Each wave card/row must show:

```text
W01 · Wave title
UID: wave_...
Slug: ...
Status: running / completed / blocked
Elapsed/Duration: ...
Packets: 3 total, 2 merged, 1 running
```

Use wave order from DB/order field for display (`W01`), not from ID.

### 6.3 Packet section

Each packet card/row must show:

```text
P01 · Packet title
UID: pkt_...
Slug: ...
Profile: FAST/NORMAL/STRICT
State: running / accepted / rejected / merged / blocked
Elapsed/Duration: ...
Attempts: 3
```

Use packet display order from explicit order/spec_json/display_order if available, not from ID.

### 6.4 Attempts table

Every packet detail must show all attempts/runs, including failed ones.

Columns:

```text
Attempt
Status
Executor/model
Started
Finished
Duration
Summary/reason
Report link
```

Example:

```text
#1  failed    coder-flash       20:11:02 → 20:18:16   7 минут 14 секунд   T1 failed
#2  failed    coder-flash       20:19:05 → 20:26:04   6 минут 59 секунд   no_changes_produced
#3  accepted  coder-agy-sonnet  20:27:10 → 20:35:13   8 минут 03 секунды acceptance passed
```

No attempt row should disappear after retry.

### 6.5 Timeline view

Add or update a compact timeline if existing admin UI has one.

Timeline should show:

```text
feature started
wave started
packet attempt #1 started
attempt #1 failed after 7 минут 14 секунд
attempt #2 started
attempt #2 failed after 6 минут 59 секунд
attempt #3 accepted after 8 минут 03 секунды
packet merged
wave completed
feature completed
```

This can be text-only in MVP.

---

## 7. Live timer implementation

Client-side live timers should use data attributes.

Example rendered HTML:

```html
<span class="live-duration" data-started-at="2026-06-03T18:10:12Z" data-finished-at="">
  7 минут 02 секунды
</span>
```

JS:

```text
Every 1 second:
  find .live-duration elements
  if data-finished-at exists: keep final duration
  else compute now - started_at
  update text using same human-readable formatter logic
```

Important:

```text
server-side formatter and JS formatter must use the same visible rules
```

If exact Russian pluralization is hard in JS, use short unit format in JS and server:

```text
1ч 02м 03с
26м 30с
```

But do not mix raw seconds with formatted text.

---

## 8. Polling / refresh

Live timers can update client-side without API polling.

But state changes still need refresh.

MVP options:

```text
Option A: simple page auto-refresh every 10 seconds
Option B: HTMX refresh partial sections every 5–10 seconds
Option C: fetch JSON endpoint every 5 seconds
```

Choose the smallest existing pattern in the project.

Do not introduce React.

Do not overbuild websockets.

---

## 9. Backend helpers

Add pure helper functions and tests:

```python
def compute_duration_seconds(started_at, finished_at, now=None) -> int | None: ...
def compute_elapsed_seconds(started_at, finished_at, state, now=None) -> int | None: ...
def format_duration(seconds) -> str: ...
```

Tests:

```text
test_format_duration_seconds
test_format_duration_minutes_seconds
test_format_duration_hours_minutes_seconds
test_format_duration_days_hours_minutes_seconds
test_compute_completed_duration
test_compute_live_elapsed_duration
test_compute_waiting_duration
```

Use fixed fake `now`, not real time.

---

## 10. Data integrity / state handling

Do not infer durations from ID strings.
Do not infer wave/packet order from UID.
Do not reset `started_at` on retry unless this is a new attempt record.
Do not overwrite old attempt durations.
Do not hide failed attempts.
Do not mark feature/wave duration as completed until terminal state.

For packet attempts:

```text
attempt started_at/finished_at = per-attempt runtime
packet started_at/finished_at = whole packet lifecycle runtime
feature/wave started_at/finished_at = aggregate lifecycle runtime
```

---

## 11. Tests required

Create/update tests depending on project structure:

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
test_format_duration_invalid_returns_dash
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

If UI tests are heavy, start with API/template unit tests. Do not use real LLM/agents in these tests.

---

## 12. Acceptance criteria

Done only if:

1. Admin UI shows feature elapsed live timer while feature is active.
2. Admin UI shows wave elapsed live timer while wave is active.
3. Admin UI shows packet elapsed live timer while packet is active.
4. Admin UI shows final feature/wave/packet duration after terminal state.
5. Admin UI shows every packet attempt duration, including failed attempts.
6. Durations are human-readable, not raw seconds.
7. Durations look like `26 минут 30 секунд` or equivalent consistent short form.
8. UID model is respected: links/actions use `feat_...`, `wave_...`, `pkt_...`; slugs are display only.
9. No logic parses `W01/P01/FEAT-...` from IDs.
10. Existing golden/self-improvement workflows are not changed.

---

## 13. Do not do in this task

Do not change retry policy.
Do not change worker execution semantics.
Do not change acceptance pipeline.
Do not change merge behavior.
Do not introduce React/websockets.
Do not implement recovery/escalation here.
Do not require real agent runs in tests.
Do not show raw seconds as the main UI value.

---

## 14. Final coder report format

Coder must report:

```text
Files changed
Duration formatter implemented: yes/no
Feature timer shown: yes/no
Wave timer shown: yes/no
Packet timer shown: yes/no
Attempt durations shown including failed attempts: yes/no
Live timer JS added: yes/no
UID links/actions preserved: yes/no
Tests added
Tests run
Remaining blockers
```
