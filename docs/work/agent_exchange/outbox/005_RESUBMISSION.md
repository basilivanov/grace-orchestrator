# TZ05 Resubmission

WEB_ORCH_REPORT: RESUBMISSION 005
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 5596b0cf3af477b2ed3b234d4a04697243d7b66c
WEB_ORCH_CHECKS: PASS

Исправления по review:

- При включённом `GRACE_INTEGRATION_RECHECK_ON_STALE_BASE` отсутствующий или пустой `PacketRun.base_sha` теперь fail-closed блокирует packet как `BLOCKED_RECOVERABLE` с классом `integration_verification_failed` и evidence `reason=missing_base_sha`; target checkout/merge/push не выполняются.
- При явном `GRACE_INTEGRATION_RECHECK_ON_STALE_BASE=false` legacy path сохранён и явно отмечается в `result_json.parallel_execution`.
- Добавлены оба regression-теста; TZ03/TZ04 fixtures обновлены доверенным base snapshot для нового safety-контракта.

Проверки:

- TZ05: 8 passed.
- TZ03/TZ04, migration/schema/API/workspace: 69 passed.
- Merge audit regressions: 19 passed.
- Ruff, `python3 -m py_compile`, applicable `grace_lint.py` и `git diff --check`: passed.

Submission commit создаётся после этого файла. Следующее задание не начиналось.
