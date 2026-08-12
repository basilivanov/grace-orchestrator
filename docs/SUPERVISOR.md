# GRACE Supervisor

## Что это

Supervisor — единая точка входа для запуска GRACE Control Plane в dev-окружении. Заменяет ad-hoc bash-скрипты (`launch3.sh`) на управляемый процесс с собственным API.

Supervisor:
- Запускает процесс API (`run_api.py`) + N процессов workers (`live_worker.py`)
- Следит за ними: упал → перезапускает
- Следит за изменениями исходников: изменился `api/` → перезапускает API, изменился `core/` → перезапускает workers
- Exposes control API через unix-socket (`supervisor.sock`)
- Exposes control + status через публичное FastAPI (`/api/admin/lifecycle/*`)
- Idempotent cleanup: убирает orphaned worktree, state-файлы, stale DB leases

## Быстрый старт

```bash
# Запустить supervisor (API + 1 worker)
# source-dir по умолчанию = директория скрипта (авто-определяется)
scripts/live_supervisor.sh --target-dir /tmp/grace-live-wt

# Явно указать source-dir (если запускаете из другой директории)
scripts/live_supervisor.sh \
  --target-dir /tmp/grace-live-wt \
  --source-dir /path/to/grace-orchestrator

# После запуска проверить статус через канонический HTTP API
curl http://127.0.0.1:8042/api/admin/lifecycle/status

# Перезапустить API (например, после правок в api/)
curl -X POST http://127.0.0.1:8042/api/admin/lifecycle/restart/api

# Перезапустить workers
curl -X POST http://127.0.0.1:8042/api/admin/lifecycle/restart/workers

# Полный рестарт
curl -X POST http://127.0.0.1:8042/api/admin/lifecycle/restart/all

# Cleanup (орфаны, state, leases)
curl -X POST http://127.0.0.1:8042/api/admin/lifecycle/cleanup

# Остановить всё
curl -X POST http://127.0.0.1:8042/api/admin/lifecycle/shutdown
```

После bootstrap операторский control surface — только HTTP/OpenAPI. Полный
контракт доступен по `/openapi.json`; lifecycle endpoints перечислены ниже.
Control CLI и OpenCode runtime не являются поддерживаемыми поверхностями.
Внутренний mini-swe/generic subprocess backend используется только worker-ами
для исполнения packet. Admin/lifecycle service composition выполняется через
явную dependency injection-композицию и typed read models.

## API: `/api/admin/lifecycle/*`

### Read-only GET

| Endpoint | Описание |
|---|---|
| `GET /api/admin/lifecycle/status` | supervisor_state + список worker'ов + git sha |
| `GET /api/admin/lifecycle/versions` | версии кода запущенных процессов |
| `GET /api/admin/lifecycle/health/full` | deep health: все ли живы, есть ли DB worker'ы |

### Mutating POST (proxy to supervisor.sock)

| Endpoint | Описание |
|---|---|
| `POST /api/admin/lifecycle/restart/{target}` | `target` ∈ `api`\|`workers`\|`all`. Проксирует на supervisor.sock `POST /control/restart/{target}` |
| `POST /api/admin/lifecycle/cleanup` | Idempotent cleanup. Query params: `worktrees`, `state_files`, `stale_leases`, `stale_lease_minutes`, `stale_state_days` |
| `POST /api/admin/lifecycle/reload` | Re-prime mtime watcher (без рестарта детей) |
| `POST /api/admin/lifecycle/shutdown` | Graceful stop: SIGTERM → 5s → SIGKILL → exit |

Все эндпоинты видны в Swagger UI (`/docs`, tag `lifecycle`).

### Примеры с curl

```bash
# Read-only
curl -s http://127.0.0.1:8042/api/admin/lifecycle/status | jq .
curl -s http://127.0.0.1:8042/api/admin/lifecycle/health/full | jq .

# Mutating
curl -X POST http://127.0.0.1:8042/api/admin/lifecycle/restart/workers
curl -X POST 'http://127.0.0.1:8042/api/admin/lifecycle/cleanup?stale_lease_minutes=60'
curl -X POST http://127.0.0.1:8042/api/admin/lifecycle/reload
curl -X POST http://127.0.0.1:8042/api/admin/lifecycle/shutdown
```

### Авторизация

Управляется через `AuthMiddleware` (`src/grace_control/api/auth.py`):
- `GRACE_API_AUTH_ENABLED=false` (default) — все запросы проходят
- `GRACE_API_AUTH_ENABLED=true` + `GRACE_API_AUTH_TOKEN=<secret>`:
  - Localhost (`127.0.0.1`, `::1`) bypass — auth не требуется
  - External callers: `Authorization: Bearer <token>` или `X-Grace-Api-Token: <token>`
  - Неверный/отсутствующий токен → 401 `UNAUTHORIZED`

`/api/admin/lifecycle/*` — **admin surface**. В проде должен быть защищён: `GRACE_API_AUTH_ENABLED=true` + bind на localhost + reverse proxy для внешних вызовов.

## Supervisor control socket (unix-only)

Supervisor слушает на `$TARGET_DIR/supervisor.sock` через uvicorn. Это
**внутренний** канал, используемый HTTP lifecycle proxy и интеграционными
тестами; операторские команды выполняются через публичный API.

| Endpoint | Описание |
|---|---|
| `GET /control/status` | snapshot supervisor state |
| `POST /control/restart/{target}` | restart api\|workers\|all |
| `POST /control/cleanup` | idempotent cleanup (см. cleanup section) |
| `POST /control/reload` | re-prime mtime watcher |
| `POST /control/stop` | graceful stop |

Операторские вызовы не обращаются к этому сокету напрямую: используйте
`/api/admin/lifecycle/*` через HTTP API.

## Архитектура

```
                    ┌──────────────────────┐
                    │   live_supervisor.sh │  ← обёртка, настраивает env
                    └──────────┬───────────┘
                               │ exec
                    ┌──────────▼───────────┐
                    │  supervisor module   │
                    │   (Supervisor)       │
                    └────┬─────┬───────────┘
                         │     │
              ┌──────────▼─┐ ┌─▼──────────┐
              │  run_api.py│ │live_worker │  ← дочерние процессы
              │  :8042     │ │.py         │
              └────────────┘ └────────────┘
                    │
   ┌────────────────┼────────────────────────┐
   │                │                        │
   ▼                ▼                        ▼
Public API     Supervisor.sock         Mtime watcher
:8042          (unix, private)         (api/ → restart api
/lifecycle/*                            core/ → restart workers
   │                                    supervisor/ → restart all)
   │
   └─→ proxies POST to supervisor.sock
```

Supervisor — это Python-процесс (asyncio), который:
- Создаёт subprocess Popen для API и workers
- Запускает uvicorn на unix-socket `$TARGET_DIR/supervisor.sock`
- Опционально запускает mtime watcher (polling `os.stat` раз в 2 сек)
- Пишет `supervisor.json` с PID'ами, статусом, временем старта
- При получении SIGTERM/SIGINT перезапускает детей
- Периодически реапит orphan процессы (`pgrep -9 run_api.py|live_worker.py`)

## Auto-reload

По умолчанию включён. Supervisor раз в 2 секунды сканирует `source_dir/src/`:

- Изменения в `api/` → restart API
- Изменения в `core/`, `adapters/`, `services/`, `worker/`, `agent/` → restart workers
- Изменения в `supervisor.py`, `supervisor_client.py`, `supervisor/` → restart all
- Изменения в `docs/`, `tests/`, `*.md`, `__pycache__/`, `.git/`, `.venv/`, `node_modules/` → игнорируются

Отключение: `--no-watch` или `export GRACE_NO_WATCH=1`.

## Cleanup

`POST /api/admin/lifecycle/cleanup` запускает `SupervisorCleanupService` (`src/grace_control/services/supervisor_cleanup_service.py`).

Три независимые оси:

### 1. Worktree cleanup (default: on)
- Сканирует `$TARGET_DIR/.grace/worktrees/`
- Для каждой директории проверяет:
  1. `git worktree list --porcelain` — зарегистрирована ли в git?
  2. Есть ли в БД `Packet` в non-terminal state, ссылающийся на этот worktree?
- Если **обе** проверки дают "нет" → удаляет:
  - `git worktree remove --force`
  - `rm -rf` как fallback
  - `git branch -D agent/<slug>` для ветки

Conservative: если git или DB недоступны — **не трогает** worktree. Никогда не поднимает исключение.

### 2. State file cleanup (default: on, threshold: 7 days)
- Сканирует `$TARGET_DIR/.grace/state/`
- Удаляет файлы/директории старше `--stale-state-days N` (default 7)
- Использует `mtime` для сравнения

### 3. Stale lease cleanup (default: on, threshold: 30 min)
- Сканирует таблицу `Lease` в БД
- Для каждой записи с `expires_at < now - 30 min`:
  - Если underlying `Packet` в `CLAIMED` или `RUNNING` → переводит в `FAILED`
  - Удаляет `Lease`

Возвращает `CleanupReport`:
```json
{
  "worktrees_removed": ["pkt_001-attempt-0001", ...],
  "worktrees_kept":    ["pkt_002-attempt-0001"],
  "state_files_removed": ["old_pkt"],
  "state_files_kept":    ["recent_pkt"],
  "stale_leases_released": 3,
  "errors": [],
  "duration_seconds": 0.234
}
```

Идемпотентно: повторный запуск возвращает пустые списки `*_removed`. Можно безопасно повесить на cron.

## Формат `supervisor.json`

Пишется в `$TARGET_DIR/supervisor.json` атомарно (через `.tmp` + rename). Версия — `1`.

```json
{
  "version": 1,
  "api": {
    "role": "api",
    "pid": 12345,
    "started_at": 1717000000.123,
    "argv": ["python3", "/path/to/scripts/run_api.py"],
    "last_exit": null
  } | null,
  "workers": [
    {
      "role": "worker",
      "pid": 12346,
      "started_at": 1717000000.456,
      "argv": ["python3", "/path/to/scripts/live_worker.py"],
      "last_exit": null
    }
  ]
}
```

Также пишется `$TARGET_DIR/supervisor.pid` — PID самого supervisor (для `kill $(cat supervisor.pid)` из скриптов).

## Файлы окружения

| Файл | Что | Когда пишется |
|---|---|---|
| `$TARGET/supervisor.json` | Persisted state children | После каждого `_restart_api/_restart_workers` |
| `$TARGET/supervisor.pid` | Supervisor PID | При старте |
| `$TARGET/supervisor.sock` | Unix-socket для control API | При старте (удаляется при stop) |
| `$TARGET/api.log` | stderr/stdout API | Append-only |
| `$TARGET/worker.log` | stderr/stdout workers (все в одном) | Append-only |

## Graceful shutdown sequence

При `POST /control/stop` (или SIGTERM/SIGINT):

1. Supervisor ловит сигнал
2. `asyncio.create_task(supervisor.stop())` — `_stopping.set()`
3. Контрольный uvicorn сервер на supervisor.sock получает `should_exit=True`
4. Цикл в `supervisor.start()` выходит из `_stopping.wait()`
5. `_shutdown()`:
   - Контрольный task cancelled
   - Каждому worker'у: SIGTERM → wait `terminate_grace` (default 5s) → SIGKILL
   - API: то же самое
   - `supervisor.sock` unlink
6. Supervisor процесс exit 0

Дети в новой сессии (`start_new_session=True`), поэтому SIGTERM supervisor'а не каскадирует автоматически — supervisor сам их гасит.

## Устранение техдолга

- **Уникальные worker_id**: supervisor передаёт `GRACE_WORKER_ID=grace-worker-0-pid<num>` каждому worker'у. Больше не `eval-w1` у всех.
- **Unified lifecycle**: один процесс-владелец заменяет N `nohup ... &` в разных терминалах.
- **Health check**: supervisor ждёт `GET /health` прежде чем запустить workers, гарантируя что API готов принимать claim'ы.
- **Graceful restart**: `POST /api/admin/lifecycle/restart/workers` → SIGTERM → 5s wait → SIGKILL → новый subprocess.
- **Reaping orphans**: при старте supervisor форсированно убивает зарегистрированные процессы `run_api.py` и `live_worker.py`.
- **Cleanup as first-class**: `SupervisorCleanupService` — единая точка для орфанов, state и stale leases. Идемпотентно, без race conditions.
- **Lifecycle HTTP proxy**: `/api/admin/lifecycle/*` — единый source of truth. POST проксирует на unix-socket, GET читает state file. Никакой бизнес-логики в HTTP-слое.

## Troubleshooting

### "supervisor state not found"
`supervisor.json` отсутствует. Supervisor не запущен или упал. Запустить:
```bash
scripts/live_supervisor.sh --target-dir $TARGET --source-dir $SOURCE
```

### "Connection refused" на supervisor.sock
- Supervisor не успел стартовать → проверьте `$TARGET/supervisor.json` (должен быть `api` и `workers`)
- Другая копия supervisor уже слушает → `pgrep -af supervisor`

### "Connection refused" на 127.0.0.1:8042
API упал или не успел подняться. Проверьте:
```bash
tail -50 $TARGET/api.log
curl http://127.0.0.1:8042/api/admin/lifecycle/status
```

### Worker'ы не обновляются после `git pull`
- mtime watcher может не сработать на `git pull` (mtime сохраняется). Решение:
```bash
touch src/grace_control/**/*.py
# или через HTTP API
curl -X POST http://127.0.0.1:8042/api/admin/lifecycle/reload
sleep 3  # watcher re-primes
```

### Orphaned worktree'ы растут
Периодический cleanup:
```bash
# Cron (раз в сутки):
0 3 * * * curl -X POST http://127.0.0.1:8042/api/admin/lifecycle/cleanup
```

### Stale leases блокируют пакеты
```bash
# Посмотреть:
sqlite3 $TARGET/grace.db "SELECT packet_id, worker_id, expires_at FROM leases WHERE expires_at < datetime('now');"
# Почистить:
curl -X POST 'http://127.0.0.1:8042/api/admin/lifecycle/cleanup?stale_lease_minutes=1'
```
