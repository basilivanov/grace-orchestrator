# Resubmission 004

Status: DONE
Commit: 82b138f22ca3d51b07648d01a383b059439c92d8

Что исправлено:
- Merge-slot/order contention теперь возвращается API как `202 waiting`; worker выполняет bounded exponential retry и не создаёт `merge_failed_action_required` для ожидаемого WAIT.
- `worktree remove`, `worktree prune` и `branch -D` перенесены под текущий merge lease, с отдельным fencing перед каждым shared-repo mutation.
- Добавлены API/worker и concurrent regression-тесты: второй packet ждёт, автоматически повторяет merge после release, а shared target mutations не пересекаются.

Проверки:
- TZ04 + TZ03 + migration/schema/lease/queue + worker regressions: `110 passed`.
- Финальный TZ04 набор: `10 passed`.
- `python3 -m py_compile`, применимый Ruff, GRACE lint нового TZ04-теста и `git diff --check`: passed.

Замечания:
- TZ05 stale-base integration recheck не затрагивался.
- Полный GRACE lint legacy router/worker файлов сохраняет их существующие canon-нарушения; новые TZ04-тесты проходят lint.
