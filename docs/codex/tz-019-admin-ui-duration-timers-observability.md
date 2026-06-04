# TZ 019 — GRACE Mission Control Center: текущая админка по факту кода

Audience: Flash coder / literal executor.

Это единственный канонический файл TZ-019. Не создавать `tz-019b`, `tz-019c` и addendum-файлы.

Цель: привести существующую админку к аккуратному рабочему состоянию, опираясь только на то, что уже есть в коде сейчас.

Видимое имя интерфейса:

```text
GRACE Mission Control Center
```

---

## 1. Что сейчас реально есть

Файлы:

```text
src/grace_control/api/main.py
src/grace_control/ui/templates/dashboard.html
src/grace_control/api/routers/packets.py
src/grace_control/api/routers/workers.py
src/grace_control/api/routers/recovery.py
src/grace_control/api/routers/self_evolution.py
src/grace_control/api/ws_broadcast.py
src/grace_control/db/schema.py
```

Текущий dashboard endpoint:

```text
GET /api/dashboard
```

`/api/dashboard/v2` сейчас нет. В этом TZ не ссылаться на него как на существующий.

Текущая админка уже умеет:

```text
3 колонки на десктопе: features / waves+packets / inspector
мобильную навигацию панелями при ширине меньше 700px
header counters: ready, running, merged, failed+rejected, workers
polling /api/dashboard каждые 5 секунд
WebSocket /ws
переподключение WebSocket
dark/light theme toggle
Legend modal
Self panel
feature cards
wave cards
packet cards
packet inspector
вкладки inspector: Overview, Runs, Events, Artifacts
recovery block в Overview
  recovery ladder info: odd attempts → RETRY_SAME_CODER (skip verifier),
    even attempts → RUN_VERIFIER (classify problem), attempt 7 → NEW_ARCHITECT
```

Текущие PacketState из схемы:

```text
draft
ready
running
accepted
merged
rejected
blocked
failed
cancelled
```

Не описывать как уже реализованное:

```text
active_stage
active_role
active_model
active_provider
stage_history
per-stage timers
event severity
image preview
/api/dashboard/v2
```

---

## 2. Текущие API по факту

### `/api/dashboard`

Возвращает:

```text
features[]
  id, slug, title, status, waves, created_at, blocked_recovery_count
waves[]
  id, title, order, status, packets, created_at
packets[]
  id, title, state, acceptance_profile, attempt_count, max_attempts,
  feature_id, wave_id, created_at, updated_at, recovery
workers[]
stats{}
```

Баг сейчас:

```text
dashboard_data() использует PacketRun, но импортирует только Feature, Wave, Packet, Worker.
```

Исправить импорт:

```python
from grace_control.db.schema import Feature, Wave, Packet, PacketRun, Worker
```

### `/api/packets/{packet_id}`

Возвращает packet detail и `runs[]`:

```text
id, feature_id, wave_id, slug, title, description, state,
acceptance_profile, attempt_count, max_attempts, spec_json, recovery,
runs, created_at, updated_at
```

Run fields:

```text
id, run_number, status, evidence_path, started_at, finished_at, duration_ms
```

### `/api/events`

Поддерживает:

```text
entity_type
entity_id
event_type
limit
```

Для `event_type=recovery_*` фильтрует все `recovery_%` события.

### Artifacts

Сейчас есть:

```text
GET /api/packets/{packet_id}/runs/{run_id}/artifacts
GET /api/packets/{packet_id}/runs/{run_id}/artifacts/file?path=...&tail=200
GET /api/artifacts/{packet_id}/{run_id:path}
```

Важно: endpoint чтения файла сейчас читает файл как текст. Поэтому не обещать полноценный image/binary preview.

---

## 3. Целевой UI на текущей реализации

Это не новый дизайн с нуля. Нужно привести текущий `dashboard.html` к понятному виду, сохранив текущий стек:

```text
HTML
CSS
vanilla JavaScript
/api/dashboard
/api/packets/{packet_id}
/api/events
/api/packets/{packet_id}/runs/{run_id}/artifacts
/ws
```

Не добавлять React/Vue/Svelte и не заводить отдельную фронтенд-сборку.

---

### 3.1 Desktop layout

Оставить текущую 3-колоночную схему, но сделать её более понятной:

```text
┌─────────────────────────────────────────────────────────────────────┐
│ GRACE Mission Control Center  Ready  Running  Merged  Failed Workers│
│ Live / Offline   Last update   Legend   Self   Theme                │
├────────────────────┬──────────────────────────┬─────────────────────┤
│ Features           │ Selected feature          │ Packet inspector    │
│                    │ Waves / Packets           │ Overview/Runs/...   │
└────────────────────┴──────────────────────────┴─────────────────────┘
```

Колонки:

```text
Left panel  = список features
Center panel = выбранная feature, waves и packets
Right panel = inspector выбранного packet
```

Нельзя превращать экран в перегруженный cockpit. На верхнем уровне показывать только то, что нужно для выбора проблемы.

---

### 3.2 Header

Header должен показывать:

```text
GRACE Mission Control Center
Ready count
Running count
Merged count
Failed count = failed + rejected
Workers count
WebSocket status: connecting / Live / Offline
Last update time
Legend
Self
Theme toggle
```

Правила:

```text
Live зелёный только когда WebSocket открыт.
Offline красный, когда WebSocket закрыт.
Polling /api/dashboard остаётся fallback и продолжает работать.
Last update обновляется после успешного load().
```

Не показывать в header:

```text
длинные packet ids
сырые JSON payloads
полный worker list
полный event log
```

---

### 3.3 Left panel: Features

Feature card должна быть компактной.

Показывать:

```text
feature title
feature UID
feature slug, если есть
created_at как короткая дата/время
packet state counters
needs attention badge, если есть failed/rejected/blocked packets
recovery badge, если blocked_recovery_count > 0 или есть packet recovery
```

Пример:

```text
Mission Control Center polish
feat_x7A... · mission-control-center · today 14:20
Ready: 3  Running: 1  Failed: 1
Needs attention: 1
```

Click behavior:

```text
click feature → select feature
left selected card получает selected style
center panel перерисовывает waves/packets
right panel очищается, если packet не выбран
mobile переходит на экран selected feature
```

Empty state:

```text
No features yet
Run: grace architect plan feature.yaml
```

Loading state:

```text
Loading features...
```

Error state:

```text
Cannot load dashboard. Retrying via polling...
```

---

### 3.4 Center panel: Selected feature / Waves / Packets

Верх selected feature area:

```text
feature title
feature UID
feature slug
created_at
waves count
packets count
compact summary: ready/running/accepted/merged/rejected/failed/blocked
```

Пример:

```text
Mission Control Center polish
feat_x7A... · mission-control-center · 2026-06-04 14:20
3 waves · 12 packets · 1 running · 1 failed
```

Wave card:

```text
Wave 1: Foundation
4 pkt · created 14:21
```

Packet row/card должна показывать:

```text
state dot
packet title
short packet UID
created_at
state label
attempt_count / max_attempts
small recovery marker if packet.recovery exists
```

Пример:

```text
● Fix recovery rendering
pkt_abcd1234… · 14:31
Running 2/3
```

Для failed/rejected/blocked packet визуально должно быть понятно, что это проблема.

Click behavior:

```text
click packet → select packet
center packet получает selected style
right inspector loads /api/packets/{packet_id}
mobile переходит на packet inspector screen
```

Empty selected feature:

```text
Select a feature
```

Feature без waves/packets:

```text
No packets in this feature
```

---

### 3.5 Right panel: Packet inspector

Right panel открывается после выбора packet.

Верх inspector должен показывать:

```text
packet title
state badge
UID + copy button
attempt_count / max_attempts
acceptance_profile
created_at
updated_at
age / updated-after human duration
feature_id + copy button
wave_id
```

Важно:

```text
Packet не имеет started_at/finished_at.
Поэтому не писать `runtime`, если считаем created_at → updated_at.
Писать `Age`, `Updated after`, `Approx. life` или русское `Возраст/обновлялся`.
```

Timeline:

```text
Показывать только реальные packet states:
draft → ready → running → accepted → merged
```

Терминальные branches показывать отдельно:

```text
rejected
blocked
failed
cancelled
```

Если хочется оставить claimed/evidence, то только как derived events, и только когда они реально найдены в `/api/events` или `result_json`.

---

### 3.6 Inspector tab: Overview

Overview должен отвечать на вопрос: “что с packet сейчас?”

Показывать:

```text
Status
Last run status
Last run duration human-readable, если duration_ms есть
Last run evidence_path, если есть
Runs count
Next action, derived from current state
Recovery block, если есть recovery
```

Next action можно оставить derived, без новых API fields:

```text
ready → Waiting for worker claim
running → Agent executing
accepted → Ready to merge
merged → Complete
failed → Needs manual/recovery decision
rejected → Can retry / recovery may decide
blocked → Blocked, inspect reason
cancelled → Cancelled
```

Recovery block должен читать текущие snake_case поля:

```text
failure_class
action
reason
current_executor_id
next_executor_hint
decision_id
```

Возможные действия (action):
```text
RETRY_SAME_CODER, SWITCH_CODER, RETURN_TO_ARCHITECT,
ESCALATE_ARCHITECT, RETRY_VERIFIER, RETRY_REVIEWER,
RETRY_MERGE, BLOCK_FEATURE, NEW_ARCHITECT, NO_ACTION
```

Для `NEW_ARCHITECT` в spec_json может быть поле `new_architect.architect_context.summary` — показывать его в админке если есть.

Пример:

```text
Recovery
retryable_coder · switch_coder
Reason: T1 failed twice
coder-flash → coder-strong
Decision: recd-...
```

Если recovery отсутствует:

```text
Recovery: none
```

---

### 3.7 Inspector tab: Runs

Runs tab показывает все runs из `/api/packets/{packet_id}`.

Для каждого run:

```text
Run number
status
executor_id, если API добавит или если брать из отдельного run endpoint/result_json
started_at
finished_at
duration_ms as human duration
evidence_path
```

Текущий packet detail не отдаёт executor_id в runs. Не писать в UI, что executor гарантированно доступен, пока не добавлен в response.

Click behavior:

```text
click run → load artifacts for this run into Artifacts tab or switch to Artifacts tab
```

Empty state:

```text
No runs yet
```

---

### 3.8 Inspector tab: Events

Events tab использует текущий endpoint:

```text
GET /api/events?entity_type=packet&entity_id={packet_id}
```

Event row:

```text
time
event readable label
event_type raw small
payload compact preview
trace_id if exists
```

Readable labels для текущих событий:

```text
packet_claimed = Packet claimed by worker
packet_released = Packet released
packet_cancelled = Packet cancelled
packet_merge_failed = Merge failed
packet_merged = Packet merged
recovery_classified = Recovery classified failure
recovery_retry_same_coder = Recovery: retry same coder
recovery_switch_coder = Recovery: switch coder
recovery_return_to_architect = Recovery: return to architect
recovery_escalate_architect = Recovery: escalate architect
recovery_retry_verifier = Recovery: retry verifier
recovery_retry_reviewer = Recovery: retry reviewer
recovery_retry_merge = Recovery: retry merge
recovery_block_feature = Recovery: block feature
recovery_no_action = Recovery: no action
recovery_new_architect = Recovery: switch architect
self_evolution_update = Self-evolution update
```

Не добавлять обязательный severity field в этом TZ.

Empty state:

```text
No events yet
```

Error state:

```text
Cannot load events
```

---

### 3.9 Inspector tab: Artifacts

Artifacts tab работает с текущими endpoints:

```text
GET /api/packets/{packet_id}/runs/{run_id}/artifacts
GET /api/packets/{packet_id}/runs/{run_id}/artifacts/file?path=...&tail=200
```

Default state:

```text
Select a run to view artifacts
```

Если selected packet имеет runs, можно автоматически загрузить artifacts последнего run при открытии Artifacts tab.

Artifact row:

```text
icon by type
name/path
size KB
safe action
```

Text preview разрешён только для:

```text
log
txt
json
md
py
yaml
yml
```

Для image/file/binary:

```text
показать metadata
не вызывать text preview
показать сообщение: Preview is not available for this file type yet
```

Acceptance:

```text
click по image/binary artifact не вызывает read_text preview и не ломает UI/server.
```

---

### 3.10 Self panel flow

Self panel сейчас скрывает main dashboard и показывает форму self-evolution.

Оставить текущий flow:

```text
click Self → show Self panel, hide dashboard
click Self again → return dashboard
```

Self form:

```text
Title
Description
Acceptance profile: FAST/NORMAL/STRICT
Max files
Launch Self-Evolution
```

Sessions list card:

```text
title
status
session id
feature_id link, if exists
error, if exists
context summary, if exists
cancel button for non-terminal statuses
```

Status colors:

```text
completed = success
executed = warning / completed with failures
failed = error
cancelled = neutral/error
pending, collecting_context, planning, executing, verifying = in progress
```

Click feature link:

```text
close Self panel
select produced feature in dashboard
```

---

### 3.11 Legend modal

Legend должна соответствовать реальным states:

```text
Draft
Ready
Running
Accepted
Merged
Rejected
Blocked
Failed
Cancelled
```

Если в UI не показывается Draft, можно не добавлять его в header counters, но Legend должна не противоречить DB states.

---

### 3.12 Mobile flow

Mobile не должен быть сжатой таблицей.

Текущий mobile flow сохранить:

```text
Screen 1: Features
Screen 2: Selected feature / Waves / Packets
Screen 3: Packet inspector
```

Навигация:

```text
Features → click feature → Waves/Packets
Waves/Packets → click packet → Inspector
Back from Inspector → Waves/Packets
Back from Waves/Packets → Features
```

Mobile header/crumb:

```text
Features
Features / {feature title}
{feature title} / {packet title}
```

Mobile требования:

```text
packet title не должен обрезаться до полной нечитаемости
state badge виден без горизонтального scroll
tabs в inspector остаются touch-friendly
Back button всегда возвращает на предыдущий уровень
right panel не должен быть просто hidden без возможности открыть selected packet
```

---

### 3.13 Loading, empty, error, offline states

Для всех панелей должны быть понятные состояния:

```text
Loading dashboard...
No features yet
Select a feature
No packets in this feature
Select a packet
No runs yet
No events yet
No artifacts
Cannot load dashboard
Cannot load packet
Cannot load events
Cannot load artifacts
Offline, retrying...
```

Ошибки не должны ломать весь экран. Если не загрузился inspector, левая и центральная панели должны остаться рабочими.

---

## 4. Что нужно сделать

### 4.1 Переименовать видимую админку

В `dashboard.html` заменить:

```text
<title>GRACE</title>
logo `GRACE`
```

на:

```text
<title>GRACE Mission Control Center</title>
GRACE Mission Control Center
```

### 4.2 Починить `/api/dashboard`

Добавить импорт `PacketRun`, чтобы dashboard не падал при сборке recovery data.

Acceptance:

```text
GET /api/dashboard возвращает 200, когда в БД есть features/packets/runs.
```

### 4.3 Починить recovery block

API отдаёт snake_case:

```text
failure_class
current_executor_id
next_executor_hint
```

JS сейчас читает camelCase:

```text
failureClass
currentExecutorId
nextExecutorHint
```

Нужно читать snake_case.

Acceptance:

```text
Recovery block показывает failure_class, action, reason, current_executor_id, next_executor_hint.
```

### 4.4 Починить статусы Self panel

Backend использует статусы:

```text
pending
collecting_context
planning
executing
verifying
completed
executed
failed
cancelled
```

UI не должен ждать статус `done`.

Маппинг:

```text
completed = success
executed = completed with warnings
failed = error
cancelled = cancelled
pending/collecting_context/planning/executing/verifying = in progress
```

### 4.5 Сделать timeline честным

Сейчас timeline показывает:

```text
ready → claimed → running → evidence → accepted → merged
```

Но реальные packet states:

```text
draft, ready, running, accepted, merged, rejected, blocked, failed, cancelled
```

Нужно либо:

```text
A. показывать timeline только по реальным states
```

либо:

```text
B. показывать claimed/evidence только как derived stage, если это реально видно из events/result_json
```

Не показывать claimed/evidence как реальные состояния БД.

### 4.6 Duration без фантазий

Сейчас UI показывает raw seconds.

Сделать маленький formatter в JS:

```text
ms/sec → human-readable duration
```

Использовать только текущие поля:

```text
run duration = duration_ms
running run elapsed = now - started_at, если started_at есть и finished_at нет
packet age = updated_at - created_at, но подписать как age/updated-after, не как точное runtime
```

Не писать, что есть точное packet runtime, пока в Packet нет started_at/finished_at.

### 4.7 Events tab

Оставить совместимость с текущим Event schema:

```text
timestamp, event_type, entity_type, entity_id, payload, trace_id
```

Добавить readable labels для текущих событий, перечисленных в разделе UI Events.

Не требовать severity column в этом TZ.

### 4.8 Artifacts tab

Правило:

```text
text/log/json/md/py/yaml можно preview как text
image/binary/file только показать metadata, если отдельный безопасный preview не реализован
```

Acceptance:

```text
клик по image/binary artifact не ломает UI/server.
```

### 4.9 WebSocket updates

Сейчас claim/release делают broadcast `state_change`.

Проверить/добавить быстрые updates для:

```text
cancel
successful merge
```

Polling оставить как fallback.

---

## 5. Out of scope

Не делать в этом TZ:

```text
новый /api/dashboard/v2
новый frontend framework
переписывание dashboard с нуля
active_stage как DB/API поле
active_role как DB/API поле
model/provider tracking
stage_history table
per-stage timers
event severity DB field
полноценный image viewer
interactive recovery buttons
policy editor
manual approve/reject controls
новые orchestration semantics
```

---

## 6. Тесты

Добавить минимальные тесты:

```text
/api/dashboard returns 200 with features/packets/runs
/api/dashboard не падает из-за PacketRun
/api/packets/{packet_id} возвращает runs и recovery snake_case
/api/events recovery_* filter работает
dashboard HTML содержит GRACE Mission Control Center
inline JS/template smoke test без syntax error
recovery block рендерит snake_case fields
Self panel корректно рендерит completed/executed
Artifacts tab не preview image/binary как text
mobile smoke: feature → packet → inspector
```

Не запускать в тестах реальные внешние агенты или live git merge.

---

## 7. Acceptance checklist

Готово, когда:

```text
не создано tz-019b/tz-019c/addendum
этот MD остался единственным TZ-019
видимый UI = GRACE Mission Control Center
Desktop layout: header + features + waves/packets + inspector
Mobile flow: features → waves/packets → inspector
/api/dashboard PacketRun bug исправлен
recovery UI читает snake_case
Self panel понимает completed/executed
Timeline не врёт про несуществующие states
Duration labels human-readable и честные
Events tab работает с текущей schema
Artifacts tab безопасен для non-text files
cancel/merge обновляют dashboard через WS или polling
нет нового frontend framework
тесты добавлены и проходят
```

---

## 8. Coder report

Report format:

```text
Summary
Files changed
Bugs fixed
UI behavior changed
API behavior changed
Tests added
Tests run
Remaining known gaps
```
