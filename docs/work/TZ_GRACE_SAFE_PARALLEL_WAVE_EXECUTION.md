# ТЗ: GRACE Safe Parallel Wave Execution

**Статус:** READY_FOR_WORKER  
**Приоритет:** P0  
**Дата:** 2026-08-10  
**Scope:** queue / worker concurrency / merge coordination / architect contract / DB migrations

---

## 1. Контекст и проблема

GRACE должен эффективно работать с дешёвыми, но медленными LLM-runtime/model tiers. Для этого latency отдельного coder-run не должен автоматически становиться latency всей feature: независимые packets одной wave должны выполняться максимально параллельно.

Текущая архитектура уже имеет правильную основу:

- `Feature -> Wave -> Packet`;
- packet является единицей исполнения;
- каждый packet выполняется в собственном worktree/workspace;
- `QueueService` уже понимает `depends_on`;
- `GRACE_MAX_CONCURRENCY=1` сейчас делает глобальный single-run guard;
- Supervisor уже умеет запускать несколько worker processes.

Однако простое увеличение `GRACE_MAX_CONCURRENCY` небезопасно.

Есть четыре класса проблем:

1. **Явная зависимость.** Packet B может требовать результат Packet A. Если B стартует до merge A, B работает по старому коду.
2. **Write-scope conflict.** Два формально независимых packets могут одновременно менять один файл/каталог.
3. **Semantic conflict без git conflict.** Packet A меняет API/schema/type в одном файле, Packet B в другом файле пишет код против старого API. Git merge может пройти успешно, но итоговый код будет логически несовместим.
4. **Concurrent merge race.** Несколько workers сейчас могут одновременно делать checkout/merge/push в одном target repository. Shared git index/working tree нельзя использовать как параллельный merge target.

Цель этого ТЗ — сделать параллелизм **корректным по умолчанию**, а не просто увеличить число workers.

---

## 2. Главный принцип

Сохранить модель:

```text
Feature
  -> Wave
      -> Packet A -> own worktree -> agent
      -> Packet B -> own worktree -> agent
      -> Packet C -> own worktree -> agent
```

**НЕ переходить на worktree-per-wave.**

Per-packet worktree остаётся обязательной единицей git-изоляции. Один shared worktree на wave запрещён для нескольких одновременно работающих coder agents.

Новая семантика:

> Wave — это потенциальный параллельный frontier, а scheduler запускает максимально широкое безопасное подмножество READY packets.

Packet может стартовать только если одновременно выполнены все условия:

1. все `depends_on` удовлетворены;
2. packet относится к текущей earliest claimable wave;
3. его write scope не конфликтует с уже активными packets;
4. его semantic conflict keys не конфликтуют с уже активными packets;
5. есть свободный concurrency slot.

---

## 3. Целевой execution flow

```text
Architect
   |
   v
Feature DAG + waves + depends_on + scope + conflict_keys
   |
   v
Queue / Safe Parallel Scheduler
   |
   +--> Packet A -> WT-A -> LLM ----+
   +--> Packet B -> WT-B -> LLM ----+--> ACCEPTED results
   +--> Packet C -> WT-C -> LLM ----+
                                      |
                                      v
                              Serialized Merge Coordinator
                                      |
                         current target HEAD integration check
                                      |
                              merge + push + MERGED
                                      |
                                      v
                          release parallel resource lease
                                      |
                                      v
                           unlock newly eligible packets
```

Execution — parallel.  
Merge into one target branch — serialized per target repository.

---

## 4. Dependency semantics

### 4.1 `depends_on` — hard semantic dependency

`depends_on` остаётся главным машинным контрактом зависимости.

Если Packet B использует результат Packet A — новый API, class, schema, type, migration, generated artifact, public contract и т.д. — B обязан иметь `depends_on: [A]`.

Dependency считается удовлетворённой только когда effective dependency находится в успешном terminal state, прежде всего `MERGED` (существующую backward-compatible семантику `CANCELLED` не ломать).

Это гарантирует:

```text
A executes -> A merged -> target HEAD advanced -> B claimed -> B worktree created from fresh HEAD
```

### 4.2 Wave discipline

Для новых architect plans принять более строгую норму:

- если B зависит от A, B **должен быть в более поздней wave**;
- `depends_on` остаётся обязательным runtime guard даже при корректном wave order;
- same-wave dependency считать planner/architect smell и валидировать предупреждением либо hard validation error для новых plans.

Таким образом wave становится настоящим DAG level / parallel frontier.

Backward compatibility: существующие features с same-wave `depends_on` не ломать; runtime всё равно должен безопасно ждать dependency.

---

## 5. Write-scope conflict detection

### 5.1 Использовать canonical `scope`

Не вводить второй `write_scope`: canonical architect contract уже определяет `packet.scope` как repository-relative paths, которые coder может изменять.

Именно `scope` является write scope для scheduler.

### 5.2 Правило конфликта

Packets A и B нельзя выполнять одновременно, если их scopes потенциально пересекаются.

Минимальные правила overlap detector:

- одинаковый file path -> conflict;
- file внутри directory scope другого packet -> conflict;
- одинаковый directory/prefix -> conflict;
- parent/child directory scopes -> conflict;
- glob/pattern overlap -> conservative conflict;
- если overlap нельзя доказать как безопасно disjoint -> считать conflict.

Для MVP лучше false-positive serialization, чем false-negative race.

### 5.3 Что происходит при конфликте

Конфликтующие packets не должны просто стартовать в двух worktrees и надеяться на git merge.

Scheduler должен:

1. выбрать первый packet детерминированно;
2. выдать ему parallel resource lease;
3. второй packet оставить READY;
4. удерживать второй packet до merge/release первого;
5. после MERGED первого заново claim второго;
6. worktree второго создаётся уже от нового target HEAD.

Это одновременно решает same-file conflict и stale-context для явно пересекающегося кода.

---

## 6. Semantic conflicts вне filesystem scope

Одного пересечения файлов недостаточно.

Пример:

```text
Packet A scope: src/service.py
  changes UserService public API

Packet B scope: src/api.py
  starts using old UserService API
```

Git scopes disjoint, но B семантически зависит от A.

### 6.1 Добавить `conflict_keys`

Расширить canonical packet schema новым полем:

```json
"conflict_keys": []
```

Тип: `list[string]`.  
Для coder packet поле обязательно в новых architect plans, но может быть `[]`.

Назначение — объявить shared semantic resources, которые нельзя независимо изменять в одной параллельной группе.

Примеры:

```json
"conflict_keys": [
  "db-schema",
  "alembic-head",
  "api:user-service",
  "contract:packet-schema",
  "config:agent-profiles"
]
```

Если два активных packets имеют пересечение `conflict_keys`, они сериализуются так же, как packets с пересекающимся `scope`.

Важно: `conflict_keys` не заменяет `depends_on`.

- `depends_on` = B должен увидеть результат A;
- `conflict_keys` = A и B не должны выполняться одновременно, но порядок может быть детерминирован scheduler-ом.

Если есть producer -> consumer relation, Architect обязан использовать `depends_on`, а не только conflict key.

### 6.2 DB/Alembic packets

Любой packet, который меняет DB schema / ORM schema / Alembic revisions, должен использовать как минимум:

```json
"conflict_keys": ["db-schema", "alembic-head"]
```

Несколько Alembic revisions не должны независимо создаваться из одного и того же head.

Migration + соответствующее ORM/schema изменение должны оставаться в одном packet, если это одна атомарная schema delta.

---

## 7. Atomic safe claim

### 7.1 Текущую двухфазность claim необходимо убрать для parallel mode

Сейчас queue selection и фактический `PacketService.claim()` логически разделены. При нескольких workers это создаёт TOCTOU window: два concurrent requests могут выбрать совместимые на момент чтения packets до фиксации resource state.

Для safe parallel mode candidate selection + conflict check + packet claim + resource lease creation должны быть **одной короткой DB transaction**.

Ввести сервис, например:

```text
SafeQueueClaimService
  claim_next_atomic(worker_id)
```

Он должен атомарно:

1. определить active feature;
2. определить earliest claimable wave;
3. очистить/игнорировать expired parallel leases;
4. получить READY candidates в deterministic order;
5. проверить `depends_on`;
6. проверить concurrency budget;
7. проверить scope overlap;
8. проверить `conflict_keys` overlap;
9. перевести выбранный packet в RUNNING / создать обычный packet lease;
10. создать parallel resource lease;
11. commit;
12. вернуть claim payload.

Не держать DB transaction во время LLM execution.

### 7.2 SQLite concurrency

Текущий основной runtime использует SQLite/WAL, поэтому atomic claim должен быть реально SQLite-safe.

Допустимый MVP:

- короткая `BEGIN IMMEDIATE` transaction для queue selection + lease acquisition;
- retry/backoff на `database is locked`;
- transaction не должна включать network, agent, git, tests.

Для PostgreSQL-compatible реализации использовать row-level locking (`FOR UPDATE` / equivalent) без изменения публичного контракта.

---

## 8. Parallel resource lease

Добавить отдельную сущность для runtime parallel-safety. Не смешивать её с существующим packet `Lease`, который решает ownership/fencing одного packet.

Предлагаемая таблица:

### `parallel_leases`

| column | type | notes |
|---|---|---|
| `id` | string/uuid PK | lease token |
| `packet_id` | string UNIQUE NOT NULL | holder packet |
| `feature_id` | string NOT NULL | indexed |
| `wave_id` | string NOT NULL | indexed |
| `worker_id` | string NOT NULL | indexed |
| `claimed_attempt` | int NOT NULL | fencing |
| `scope_json` | JSON NOT NULL | normalized canonical scope snapshot |
| `conflict_keys_json` | JSON NOT NULL | semantic resource snapshot |
| `base_sha` | string nullable | target HEAD visible at claim/workspace creation |
| `acquired_at` | datetime NOT NULL | |
| `expires_at` | datetime NOT NULL | indexed |
| `heartbeat_at` | datetime NOT NULL | |

Indexes:

- `packet_id` unique;
- `(feature_id, wave_id)`;
- `expires_at`;
- `worker_id`.

Lease snapshot должен хранить scope/conflict keys именно на момент claim, чтобы последующее изменение spec не меняло уже взятую блокировку.

### Lifecycle

Parallel lease создаётся при claim и удерживается:

```text
RUNNING -> ACCEPTED -> MERGING -> MERGED
```

Освобождать lease при:

- `MERGED`;
- `REJECTED`;
- `FAILED`;
- `BLOCKED_RECOVERABLE` / `BLOCKED_FINAL`;
- `CANCELLED`;
- stale worker cleanup / expiry.

**Не освобождать на `ACCEPTED`**, потому что до merge другой конфликтующий packet ещё не должен создавать worktree от старого target HEAD.

Lease heartbeat можно синхронизировать с существующим worker/packet lease renewal.

---

## 9. Serialized Merge Coordinator

### 9.1 Merge нельзя делать параллельно в shared target repository

Ввести `MergeCoordinatorService`.

Требование:

> Для одного logical target repository одновременно разрешён только один mutation merge/push operation.

LLM execution при этом продолжает идти параллельно.

### 9.2 DB-backed merge lease

Добавить таблицу:

### `merge_leases`

| column | type | notes |
|---|---|---|
| `target_repo_key` | string PK | normalized path or stable hash |
| `lease_token` | string NOT NULL | fencing token |
| `packet_id` | string NOT NULL | current merger |
| `worker_id` | string nullable | owner |
| `acquired_at` | datetime NOT NULL | |
| `expires_at` | datetime NOT NULL | indexed |
| `heartbeat_at` | datetime NOT NULL | |

Acquire должен быть atomic. Expired lease может быть reclaimed только с новым fencing token.

Не использовать только process-local `asyncio.Lock`: workers являются отдельными processes и в будущем могут находиться на разных hosts.

### 9.3 Merge order

Для accepted packets одного target repo merge order должен быть deterministic, например:

1. `Wave.order ASC`;
2. `Packet.created_at ASC`;
3. `Packet.id ASC`.

Не требуется ждать завершения всех agents wave перед первым merge. Как только безопасный independent packet ACCEPTED и merge slot свободен, его можно интегрировать.

---

## 10. Stale-base integration check

Даже у independent packets target HEAD может измениться, пока agent работает.

Пример:

```text
A and B start from SHA X
A merges -> target is SHA Y
B finishes from old SHA X
```

Обычный git merge B в Y может пройти без text conflict, но B тестировался против X.

Поэтому перед merge B:

1. прочитать `packet_run.base_sha`;
2. прочитать current target branch HEAD;
3. если SHA одинаковы — обычный merge path;
4. если target HEAD advanced — выполнить integration recheck на актуальной базе до изменения target branch.

### 10.1 Integration recheck

Создать временный integration worktree от current target HEAD и попытаться применить packet branch/commit туда.

Если git conflict:

- target branch не менять;
- packet -> `BLOCKED_RECOVERABLE`;
- failure class: `stale_base_conflict`;
- recovery/rework должен стартовать от свежего HEAD.

Если git применился:

- прогнать acceptance/integration verification на combined state;
- как минимум T1 текущего packet; предпочтительно использовать существующий AcceptancePipeline с profile-aware tier selection;
- при failure не менять target branch;
- packet -> `BLOCKED_RECOVERABLE`;
- failure class: `integration_verification_failed`;
- приложить logs/diff/current_head/base_sha в evidence.

Если recheck passed:

- выполнить serialized merge в target branch;
- push;
- transition -> `MERGED`;
- release parallel lease;
- следующий конфликтующий packet теперь может быть claimed и увидит свежий HEAD.

Config:

```text
GRACE_INTEGRATION_RECHECK_ON_STALE_BASE=true   # default true
```

Опционально позже:

```text
GRACE_INTEGRATION_RECHECK_ALWAYS=true
```

но это не требуется для MVP.

---

## 11. PacketRun observability

Добавить в ORM/Alembic nullable columns:

### `packet_runs.base_sha`

SHA target repository, от которого был создан effective packet workspace.

### `packet_runs.integration_base_sha`

SHA current target branch, против которого был выполнен финальный integration recheck/merge.

Оставить подробный workspace evidence в `result_json`; columns нужны для дешёвого operational query/admin/debug.

В result/evidence также писать:

```json
{
  "parallel_execution": {
    "base_sha": "...",
    "integration_base_sha": "...",
    "scope_conflicts_checked": true,
    "conflict_keys": [],
    "stale_base": false,
    "integration_recheck": "skipped|passed|failed"
  }
}
```

---

## 12. Alembic: сделать canonical migration mechanism

### 12.1 Текущее состояние

Сейчас runtime использует:

- `Base.metadata.create_all(engine)`;
- `_SQLITE_COLUMN_MIGRATIONS`;
- `_SQLITE_TABLE_CREATIONS`;
- ручные `ALTER TABLE` / `CREATE TABLE IF NOT EXISTS` при startup.

Это необходимо заменить на Alembic.

### 12.2 Добавить dependency и layout

Добавить Alembic в runtime dependencies.

Создать canonical layout:

```text
alembic.ini
alembic/
  env.py
  script.py.mako
  versions/
    0001_grace_legacy_baseline.py
    0002_safe_parallel_execution.py
```

`alembic/env.py` должен использовать `grace_control.db.schema.Base.metadata`.

DB URL брать из того же canonical settings resolution, что и runtime (`GRACE_DB_URL` / `settings.database_url`), без второго самостоятельного config source.

### 12.3 Revision 0001 — legacy baseline

`0001_grace_legacy_baseline` описывает schema, соответствующую текущему нормализованному состоянию БД до этой feature.

Нужна безопасная стратегия для двух случаев.

#### Fresh DB

Для новой пустой БД:

```text
alembic upgrade head
```

должен создать всю schema с нуля.

Runtime production path не должен зависеть от `Base.metadata.create_all()`.

#### Existing unversioned GRACE SQLite DB

Старые installations не имеют `alembic_version` и могли быть созданы разными поколениями `_SQLITE_COLUMN_MIGRATIONS`.

Нельзя просто выполнить baseline `CREATE TABLE`, иначе existing DB упадёт.

Нужен one-time bridge:

1. определить: GRACE tables существуют, `alembic_version` отсутствует;
2. выполнить legacy normalization только для известных старых additive deltas;
3. проверить обязательные baseline tables/columns;
4. `alembic stamp 0001_grace_legacy_baseline`;
5. `alembic upgrade head`;
6. после успешного stamp ручные startup migrations больше никогда не исполнять.

Существующие `_SQLITE_COLUMN_MIGRATIONS` / `_SQLITE_TABLE_CREATIONS` временно можно сохранить только как private legacy bootstrap helper для **unversioned pre-Alembic DB**.

Запрещено продолжать добавлять туда новые schema changes.

### 12.4 Revision 0002 — safe parallel execution

Создать Alembic revision, которая:

- создаёт `parallel_leases`;
- создаёт required indexes/unique constraint;
- создаёт `merge_leases`;
- добавляет `packet_runs.base_sha`;
- добавляет `packet_runs.integration_base_sha`.

`downgrade()` должен удалять новые indexes/tables/columns в обратном порядке настолько, насколько dialect позволяет штатным Alembic batch operations.

SQLite column operations делать через Alembic `batch_alter_table` при необходимости.

### 12.5 Runtime startup

Refactor `init_db()`:

```text
resolve engine/db_url
  -> pre-Alembic legacy detection/bootstrap if needed
  -> alembic upgrade head
  -> initialize SessionLocal
```

Не выполнять постоянные ad-hoc DDL после Alembic bootstrap.

Для isolated unit tests допускается отдельный explicit helper, создающий schema быстро, но production/live startup должен проверяться именно через Alembic.

---

## 13. Architect prompt — ОБЯЗАТЕЛЬНО изменить

Да, prompt архитектора нужно менять.

Текущий prompt уже умеет `scope` и `depends_on`, но для safe wide-wave execution этого недостаточно: Architect должен проектировать packets с учётом свежести контекста и semantic parallel safety.

Изменить canonical source:

```text
src/grace_control/core/prompts/architect_prompt.md
```

### 13.1 Добавить `conflict_keys` в Canonical Packet Schema

Новый required field для coder packets:

```json
"conflict_keys": []
```

Для legacy architect outputs parser должен default-ить отсутствующее поле в `[]` с backward-compatible warning/debug event, а не ломать существующие packets.

### 13.2 Добавить Parallel Planning Rules

Architect обязан перед emit каждого feature plan проверить:

1. **Producer/consumer:** если B требует output A, поставить `depends_on` и расположить B в более поздней wave.
2. **Write overlap:** не считать packets безопасно parallel, если их `scope` пересекается.
3. **Semantic overlap:** если packets затрагивают общий logical contract/resource, добавить одинаковый `conflict_key` или явный dependency.
4. **DB migrations:** schema/migration packets получают `db-schema` + `alembic-head` conflict keys; migration + соответствующий ORM delta атомарны.
5. **Correctness before width:** сначала корректная dependency graph, затем максимизация ширины wave.
6. **No hidden stale-context dependency:** разные файлы не означают независимость.
7. **Same wave = parallel candidate:** Architect не должен помещать producer и consumer в одну wave только ради меньшего числа waves.

### 13.3 Добавить pre-emit validation checklist

Перед `FINAL_ARCHITECT_ARTIFACT_PLAN_JSON` Architect проверяет:

- все `depends_on` указывают на существующие packet titles;
- dependency graph acyclic;
- dependency packet находится в более ранней wave для новых plans;
- `scope` repository-relative и bounded;
- same-wave packets с очевидным overlapping scope repacked/serialized;
- cross-file shared contract помечен dependency/conflict key;
- Alembic heads не создаются параллельно;
- migration и ORM model не разведены в независимые parallel packets.

### 13.4 Пример правильного plan

```json
{
  "waves": [
    {
      "title": "Core contract",
      "packets": [
        {
          "title": "Add UserService contract",
          "scope": ["src/app/user_service.py"],
          "depends_on": [],
          "conflict_keys": ["api:user-service"]
        }
      ]
    },
    {
      "title": "Consumers",
      "packets": [
        {
          "title": "Wire HTTP API",
          "scope": ["src/app/api.py"],
          "depends_on": ["Add UserService contract"],
          "conflict_keys": ["api:user-service"]
        },
        {
          "title": "Update unrelated docs",
          "scope": ["docs/user-guide.md"],
          "depends_on": [],
          "conflict_keys": []
        }
      ]
    }
  ]
}
```

Runtime scheduler всё равно является final safety authority. Architect metadata помогает scheduler-у, но scheduler не должен слепо доверять тому, что wave безопасна.

---

## 14. Feature plan / contract validation

Обновить parser/contract models, которые materialize architect JSON:

- canonicalize missing `conflict_keys` -> `[]` for legacy;
- validate `list[str]`;
- normalize key strings (`strip`, lower-case where policy permits, reject empty values);
- reject duplicate keys after normalization;
- validate dependency titles;
- detect dependency cycles;
- для новых architect artifact version валидировать wave-order consistency.

Если в репозитории есть versioned architect schema/manifest — bump schema version. Если нет — не вводить глобальный versioning только ради этого поля; использовать backward-compatible optional parse + required prompt output.

---

## 15. QueueService refactor

Текущий `QueueService` сохранить как policy source, но вынести parallel-specific code в маленькие компоненты, чтобы не превратить файл в монолит.

Рекомендуемые services:

```text
services/parallel_conflict_service.py
services/parallel_lease_service.py
services/safe_queue_claim_service.py
services/merge_coordinator_service.py
services/integration_recheck_service.py
```

Возможное распределение:

### `ParallelConflictService`

- normalize scopes;
- `scopes_overlap(a, b)`;
- `conflict_keys_overlap(a, b)`;
- `can_run_together(candidate, active_leases)`.

### `ParallelLeaseService`

- acquire;
- renew;
- release;
- expire stale;
- return active leases for feature/wave/repo.

### `SafeQueueClaimService`

- deterministic selection;
- dependency guard;
- wave guard;
- capacity guard;
- atomic conflict check + packet claim + parallel lease.

### `MergeCoordinatorService`

- acquire/release merge lease;
- deterministic merge;
- stale-base check;
- invoke integration recheck;
- transition + cleanup.

---

## 16. Concurrency configuration

Сохранить существующий:

```text
GRACE_MAX_CONCURRENCY=1
```

как safe backward-compatible default.

После реализации можно запускать, например:

```text
GRACE_MAX_CONCURRENCY=8
supervisor --workers 8
```

Effective parallelism ограничивается минимумом:

```text
available workers
GRACE_MAX_CONCURRENCY
number of safe claimable packets in current wave
provider/runtime rate limits
```

Не делать один worker многозадачным в этом ТЗ. Один worker = один active packet. Масштабирование достигается количеством worker processes.

Дополнительные settings:

```text
GRACE_PARALLEL_SCOPE_GUARD_ENABLED=true
GRACE_MERGE_SERIALIZATION_ENABLED=true
GRACE_INTEGRATION_RECHECK_ON_STALE_BASE=true
```

Первые два для production должны default-ить в `true`, когда `GRACE_MAX_CONCURRENCY > 1`.

Запрещено разрешать unsafe multi-worker mode через случайное выставление concurrency > 1 без merge serialization.

---

## 17. Failure semantics

Добавить typed failure classes минимум:

```text
parallel_scope_conflict          # normally means WAIT, not packet failure
parallel_conflict_key_wait       # WAIT
parallel_lease_lost              # fencing/recovery
merge_lease_lost                 # merge aborted before mutation if possible
stale_base_conflict              # BLOCKED_RECOVERABLE
integration_verification_failed  # BLOCKED_RECOVERABLE
merge_conflict                   # BLOCKED_RECOVERABLE
```

Scope/key conflict при claim — **не ошибка packet**. Candidate просто остаётся READY и ждёт release conflicting lease.

Если parallel/merge lease потерян по fencing token, stale worker не имеет права продолжать state mutation/merge.

---

## 18. Cleanup / crash recovery

Обновить stale scanners/cleanup:

- expired packet lease -> существующая recovery policy;
- одновременно release/reclaim связанный `parallel_lease`;
- expired merge lease -> разрешить takeover только после проверки target repo state;
- если процесс умер во время git merge, новый coordinator обязан выполнить repo sanity check (`merge in progress`, dirty index, MERGE_HEAD) перед следующим merge;
- cleanup не должен удалять worktree другого живого worker-а.

После crash во время target mutation не делать blind `git reset --hard` без подтверждения, что mutation принадлежит expired merge lease и target repo root совпадает с expected repo.

---

## 19. Admin / observability

Минимально добавить в diagnostics/API данные:

- effective `GRACE_MAX_CONCURRENCY`;
- active workers count;
- active parallel leases;
- packet `base_sha`;
- packet `integration_base_sha`;
- reason packet ждёт:
  - `waiting_for_dependency`;
  - `waiting_for_scope_conflict`;
  - `waiting_for_conflict_key`;
  - `waiting_for_merge_slot`;
  - `waiting_for_wave_completion`;
- active merge lease holder;
- integration recheck result.

Не требуется большой redesign admin UI. Достаточно API + существующих packet/runtime diagnostics; UI badges можно добавить, если дёшево.

---

## 20. Required tests

### 20.1 Architect / contract

1. `conflict_keys` accepted and materialized.
2. Missing legacy `conflict_keys` -> `[]`.
3. Invalid key type rejected.
4. Dependency on missing packet rejected/warned per compatibility policy.
5. Dependency cycle rejected.
6. New plan with dependency in same/later-invalid wave rejected or emits deterministic validation error.
7. Architect prompt contains explicit parallel-safety rules.

### 20.2 Scope conflict unit tests

Cover:

```text
same file
file vs parent directory
directory vs child directory
disjoint files
disjoint directories
conservative glob overlap
conflict_keys intersection
empty conflict_keys
```

### 20.3 Queue concurrency

With `GRACE_MAX_CONCURRENCY=4`:

1. 4 independent READY packets in same wave -> up to 4 claims succeed.
2. 5th claim waits when capacity exhausted.
3. dependent B is not claimed before A MERGED.
4. same-scope B is not claimed while A parallel lease active.
5. after A MERGED/released, B is claimable and gets new base SHA.
6. disjoint scope packets are claimable concurrently.
7. same conflict key serializes even with disjoint files.
8. concurrent claim requests cannot both acquire conflicting packets.
9. stale parallel lease can be reclaimed with fencing.

The concurrent claim test must use real concurrent tasks/processes against SQLite file DB, not only sequential mocks.

### 20.4 Merge concurrency

1. Two accepted packets targeting same repo -> only one merge lease holder.
2. Second waits, does not mutate target repo.
3. Different target repos may merge concurrently.
4. stale merge lease takeover obeys fencing.
5. target repo never observes concurrent checkout/index mutation.

### 20.5 Stale base

1. A and B start from SHA X.
2. A merges -> Y.
3. B merge sees `base_sha != current_head`.
4. clean integration + passing tests -> B merges.
5. git conflict -> B blocked recoverable, target unchanged.
6. no git conflict but integration test failure -> B blocked recoverable, target unchanged.

### 20.6 Alembic

Create/replace migration tests to cover:

1. empty SQLite DB -> `alembic upgrade head` creates full schema;
2. current legacy DB without `alembic_version` -> bootstrap + stamp + upgrade succeeds;
3. old legacy fixture missing prior additive columns -> normalization + stamp + upgrade succeeds;
4. repeated `init_db()` is idempotent;
5. `alembic current` == head after startup;
6. `parallel_leases` exists with indexes;
7. `merge_leases` exists;
8. `packet_runs.base_sha` exists;
9. `packet_runs.integration_base_sha` exists;
10. 0002 downgrade/upgrade roundtrip works on disposable DB.

Old tests that assert `_SQLITE_TABLE_CREATIONS` directly should be replaced with Alembic behavior tests. Legacy bootstrap helper may have narrow dedicated tests only.

---

## 21. Files likely involved

At minimum inspect/change:

```text
pyproject.toml
alembic.ini
alembic/env.py
alembic/script.py.mako
alembic/versions/0001_grace_legacy_baseline.py
alembic/versions/0002_safe_parallel_execution.py

src/grace_control/db/__init__.py
src/grace_control/db/schema.py
src/grace_control/core/prompts/architect_prompt.md
src/grace_control/services/feature_planning_service.py
src/grace_control/services/queue_service.py
src/grace_control/services/packet_service.py
src/grace_control/services/merge_service.py
src/grace_control/services/parallel_conflict_service.py
src/grace_control/services/parallel_lease_service.py
src/grace_control/services/safe_queue_claim_service.py
src/grace_control/services/merge_coordinator_service.py
src/grace_control/services/integration_recheck_service.py
src/grace_control/worker/worker.py
src/grace_control/api/routers/packets.py
src/grace_control/core/stuck_scanner.py
src/grace_control/config/settings.py

# exact contract/parser files discovered during implementation
# architect FeatureSpec / packet contract models

 tests/grace_control/db/test_migrations.py
 tests/grace_control/services/test_queue_service.py
 tests/grace_control/services/test_parallel_conflict_service.py
 tests/grace_control/services/test_safe_parallel_claim.py
 tests/grace_control/services/test_merge_coordinator.py
 tests/integration/test_parallel_wave_execution.py
 tests/integration/test_stale_base_integration.py
```

Не создавать большие новые abstractions, если существующий service естественно расширяется; но queue/merge conflict logic не складывать обратно в один монолитный `packet_executor.py`.

---

## 22. Backward compatibility

Обязательные условия:

- `GRACE_MAX_CONCURRENCY=1` сохраняет текущее последовательное поведение;
- legacy packet без `conflict_keys` работает как `conflict_keys=[]`;
- legacy same-wave `depends_on` остаётся runtime-safe;
- существующий packet claim response shape не ломать без необходимости;
- старые SQLite DB автоматически и один раз переходят на Alembic baseline;
- после перехода на Alembic schema mutation больше не добавляется через `_SQLITE_COLUMN_MIGRATIONS`;
- per-packet worktree semantics не менять.

---

## 23. Non-goals

Не входит в этот packet/feature:

- один worker исполняет несколько coder packets одновременно;
- shared worktree для wave;
- distributed filesystem orchestration;
- speculative execution зависимых packets;
- LLM-based automatic merge conflict resolution до deterministic integration failure;
- сложный priority scheduler между несколькими active features;
- переход с SQLite на PostgreSQL;
- полный redesign admin UI.

---

## 24. Implementation order

Рекомендуемый порядок:

### W1 — Alembic foundation

- dependency/config/env;
- baseline migration;
- legacy DB bootstrap/stamp;
- Alembic migration tests.

### W2 — Parallel metadata + architect contract

- `conflict_keys` contract/parser;
- architect prompt rules;
- plan validation;
- ORM models for new runtime lease tables.

### W3 — Safe atomic claim

- parallel lease service;
- scope/key conflict detector;
- atomic queue claim;
- SQLite concurrency tests.

### W4 — Serialized merge

- merge lease;
- coordinator;
- worker integration;
- crash/fencing behavior.

### W5 — Stale-base integration recheck

- base SHA persistence;
- current-HEAD integration workspace;
- acceptance rerun;
- recovery states/evidence.

### W6 — Full multi-worker integration

- real Supervisor with N workers;
- 4-8 packets in one wave;
- independent parallel case;
- scope conflict case;
- semantic conflict-key case;
- dependency case;
- merge serialization proof.

---

## 25. Acceptance criteria

PASS only if all conditions below hold.

1. Per-packet worktrees remain the execution isolation model.
2. With `GRACE_MAX_CONCURRENCY > 1`, independent same-wave packets actually execute concurrently on multiple workers.
3. `depends_on` packet cannot start until dependency is merged/successfully terminal by existing policy.
4. Conflicting `scope` packets cannot hold active parallel leases simultaneously.
5. Matching `conflict_keys` serialize packets even when filesystem scopes are disjoint.
6. Claim selection + packet lease + parallel lease are atomic under concurrent SQLite requests.
7. Only one merge mutates a given target repository at a time.
8. Accepted packet built on stale base receives an integration recheck before target mutation.
9. Text conflict or integration verification failure leaves target branch unchanged and creates recoverable failure evidence.
10. Architect prompt explicitly optimizes for safe wave width and emits `conflict_keys`.
11. New DB changes are delivered through Alembic, not new ad-hoc startup ALTERs.
12. Fresh DB can be created entirely through `alembic upgrade head`.
13. Existing unversioned GRACE SQLite DB upgrades without data loss and receives `alembic_version`.
14. `GRACE_MAX_CONCURRENCY=1` remains backward compatible.
15. Integration tests prove real parallel execution plus serialized merge.

---

## 26. Required implementation report

Create after implementation:

```text
docs/work/REPORT_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md
```

Report must include:

- base SHA / final SHA;
- Alembic revisions and upgrade strategy;
- schema changes;
- architect prompt changes;
- safe claim algorithm;
- conflict detection rules;
- merge serialization implementation;
- stale-base behavior;
- tests run and results;
- real multi-worker smoke timings;
- known limitations;
- confirmation that old DB was tested through upgrade path;
- confirmation that no new ad-hoc SQLite migration was added.

---

## 27. Suggested commit message

```text
feat: add safe parallel wave execution and alembic migrations
```
