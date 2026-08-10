# Submission 004

Status: DONE
Commit: 51acfe1b13a2d1f30cfe930b45ea056311a4899c

Что сделано:
- Добавлены Alembic revision `0003_serialized_merge`, ORM `MergeLease` и DB-backed `MergeCoordinatorService`.
- Реализованы canonical target-repo keys, atomic lease acquire/takeover, sanity checks, fencing перед каждым git mutation и deterministic merge order.
- Merge lifecycle подключён к API/worker; parallel lease TZ03 удерживается до `MERGED` и освобождается существующей policy.

Проверки:
- TZ04 + TZ03 + migration/schema/lease/queue regressions: `90 passed`.
- Ruff, `python3 -m py_compile`, GRACE lint новых TZ04-файлов и `git diff --check`: passed.

Замечания:
- TZ05 stale-base integration recheck не реализовывался по ограничению задания.
- Полный GRACE lint изменённых legacy-файлов продолжает показывать их существующие canon-нарушения; новые TZ04-файлы проходят lint.
