# Submission 003

Status: DONE
Commit: 41ed11b

Что сделано:
- Добавлены Alembic revision/ORM `parallel_leases`, fenced lifecycle и heartbeat.
- Добавлены canonical `ParallelConflictService` и SQLite-safe `SafeQueueClaimService` с `BEGIN IMMEDIATE`, retry/backoff, dependency/wave/capacity/scope/key guards.
- Parallel lease подключён к claim/release/merge/failure/cancel lifecycle; `GRACE_MAX_CONCURRENCY=1` сохранён.
- Добавлен реальный file-backed SQLite concurrency test suite.

Проверки:
- TZ03/migration/schema/W01/queue/lease-manager tests: passed.
- `python3 -m py_compile`: passed.
- Ruff и `python3 scripts/grace_lint.py` для новых файлов: passed.
- `git diff --check`: passed.

Замечания:
- Full repository suite остановлен после baseline failures вне TZ03: planning-log permissions и старые W01 API-тесты без fencing tokens. TZ03 targeted suite зелёный.
