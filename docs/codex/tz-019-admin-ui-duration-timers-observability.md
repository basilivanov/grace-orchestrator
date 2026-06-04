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

## 3. Что нужно сделать

### 3.1 Переименовать видимую админку

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

### 3.2 Починить `/api/dashboard`

Добавить импорт `PacketRun`, чтобы dashboard не падал при сборке recovery data.

Acceptance:

```text
GET /api/dashboard возвращает 200, когда в БД есть features/packets/runs.
```

### 3.3 Починить recovery block

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

### 3.4 Починить статусы Self panel

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

### 3.5 Сделать timeline честным

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

### 3.6 Duration без фантазий

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

### 3.7 Events tab

Оставить совместимость с текущим Event schema:

```text
timestamp, event_type, entity_type, entity_id, payload, trace_id
```

Добавить readable labels для текущих событий:

```text
packet_claimed
packet_released
packet_cancelled
packet_merge_failed
packet_merged
recovery_classified
recovery_retry_same_coder
recovery_switch_coder
recovery_return_to_architect
recovery_escalate_architect
recovery_retry_verifier
recovery_retry_reviewer
recovery_retry_merge
recovery_block_feature
recovery_no_action
self_evolution_update
```

Не требовать severity column в этом TZ.

### 3.8 Artifacts tab

Правило:

```text
text/log/json/md/py/yaml можно preview как text
image/binary/file только показать metadata, если отдельный безопасный preview не реализован
```

Acceptance:

```text
клик по image/binary artifact не ломает UI/server.
```

### 3.9 WebSocket updates

Сейчас claim/release делают broadcast `state_change`.

Проверить/добавить быстрые updates для:

```text
cancel
successful merge
```

Polling оставить как fallback.

---

## 4. Out of scope

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

## 5. Тесты

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

## 6. Acceptance checklist

Готово, когда:

```text
не создано tz-019b/tz-019c/addendum
этот MD остался единственным TZ-019
видимый UI = GRACE Mission Control Center
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

## 7. Coder report

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
