# Resubmission 004

Status: DONE
Commit: d60119b5c2cfed7c54053d289697d8495d3a2c6d

Что исправлено:
- Проверка DB-порядка и занятого merge lease теперь выполняется до Git sanity-checks: активный holder с временным `dirty`/`MERGE_HEAD` оставляет следующий packet в `WAIT`, а не переводит worker в manual failure.
- Каждая guarded target mutation получает heartbeat lease до завершения callback; branch cleanup и worktree cleanup остаются отдельными fenced шагами. Expired takeover по-прежнему проходит sanity-check до замены lease.
- Добавлены deterministic regression-тесты для активного merge с `dirty + MERGE_HEAD` и короткого TTL: takeover невозможен при живом heartbeat, после его остановки получается новый fencing token; worker после WAIT автоматически повторяет merge.

Проверки:
- TZ04 + TZ03 + migration/schema/lease/queue + worker regressions: `112 passed`.
- Финальный TZ04 набор: `12 passed`.
- `python3 -m py_compile` изменённых Python-файлов: passed.
- Ruff и GRACE lint для нового coordinator и TZ04-теста: passed.
- `git diff --check`: passed.

Замечания:
- TZ05 stale-base integration recheck не затрагивался.
- Полный GRACE lint/Ruff для legacy router/worker/merge-service файлов сохраняет существующие canon-нарушения; review scope их не расширял.
