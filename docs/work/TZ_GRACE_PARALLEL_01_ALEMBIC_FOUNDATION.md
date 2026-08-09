# ТЗ 01 — Alembic foundation

**Depends on:** none  
**Master:** `TZ_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md`

## Цель

Перевести production/runtime schema migration path с `Base.metadata.create_all()` + постоянных ad-hoc SQLite DDL на Alembic, сохранив безопасный one-time upgrade старых unversioned GRACE SQLite DB.

## Сделать

1. Добавить Alembic в runtime dependencies.
2. Добавить canonical layout:
   - `alembic.ini`
   - `alembic/env.py`
   - `alembic/script.py.mako`
   - `alembic/versions/0001_grace_legacy_baseline.py`
3. `env.py` использует `grace_control.db.schema.Base.metadata` и тот же DB URL resolution, что runtime (`GRACE_DB_URL` / settings).
4. `0001_grace_legacy_baseline` должен уметь создать текущую нормализованную schema на пустой DB.
5. Для existing DB без `alembic_version` реализовать one-time bridge:
   - обнаружить legacy GRACE DB;
   - применить только известные старые additive normalization deltas;
   - проверить baseline tables/columns;
   - stamp `0001_grace_legacy_baseline`;
   - затем `upgrade head`.
6. Refactor `init_db()`:
   - resolve engine/db_url;
   - legacy bootstrap only when DB реально pre-Alembic;
   - `alembic upgrade head`;
   - initialize `SessionLocal`.
7. Не добавлять новые schema changes в `_SQLITE_COLUMN_MIGRATIONS`/`_SQLITE_TABLE_CREATIONS`. Их можно оставить только как private legacy-bootstrap helper.

## Не делать

- Не добавлять `parallel_leases`, `merge_leases`, `base_sha` — это следующие этапы.
- Не менять queue/worker/merge semantics.
- Не менять architect prompt.

## Тесты

1. Empty SQLite -> `alembic upgrade head` создаёт baseline schema.
2. Current legacy DB без `alembic_version` -> normalize + stamp + upgrade succeeds.
3. Legacy fixture с отсутствующими старыми additive columns -> upgrade succeeds.
4. Repeated `init_db()` idempotent.
5. `alembic current` == head после startup.
6. Старые данные сохраняются.
7. Existing DB не получает повторный legacy bootstrap после появления `alembic_version`.

Обновить/заменить старые tests, которые проверяют `_SQLITE_TABLE_CREATIONS` как production mechanism.

## DONE

Fresh DB и legacy DB проходят через Alembic; production startup после bootstrap не делает постоянные ad-hoc DDL; migration tests зелёные.
