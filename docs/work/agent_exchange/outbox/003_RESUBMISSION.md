# Resubmission 003

Status: DONE
Commit: e592d25e517a09e40d18d125e4c02b07ffc67c6d

Что исправлено:
- Просроченные `parallel_leases` остаются conflict-active, пока связанный packet находится в `RUNNING` или `ACCEPTED`.
- После обычного lease recovery состояние `RUNNING` сбрасывается, reservation удаляется, и конфликтующий packet снова claimable.
- Добавлены regression-тесты для expired `ACCEPTED` и expired `RUNNING` сценариев, включая fenced accept и merge lifecycle.

Проверки:
- TZ03 + migration/schema/lease-manager/queue regressions: 62 passed.
- Ruff: passed.
- `python3 scripts/grace_lint.py` на изменённых файлах: passed.
- `python3 -m py_compile`: passed.
- `git diff --check`: passed.

Следующее задание не начиналось.
