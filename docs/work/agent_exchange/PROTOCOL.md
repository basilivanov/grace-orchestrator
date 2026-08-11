# Minimal Agent Exchange Protocol

Новые работы используют имя файла ТЗ как идентификатор. Generic
`NNN_TASK.md` разрешён только для старой числовой истории.

## Named TZ

Для `01_LINT_GUARDRAILS` файловый цикл выглядит так:

```text
inbox/01_LINT_GUARDRAILS.md
inbox/01_LINT_GUARDRAILS_REVIEW.md       # только при REVIEW
outbox/01_LINT_GUARDRAILS_SUBMISSION.md
outbox/01_LINT_GUARDRAILS_RESUBMISSION.md
```

Coder читает только путь, который ему передал orchestrator. После работы
создаёт отчёт с точными строками:

```text
WEB_ORCH_REPORT: SUBMISSION 01_LINT_GUARDRAILS
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <commit-sha>
WEB_ORCH_CHECKS: PASS
```

После `REVIEW` используется `RESUBMISSION` с тем же именем TZ. Architect
завершает review отдельной последней строкой:

```text
WEB_ORCH_DECISION: ACCEPT 01_LINT_GUARDRAILS
```

или:

```text
WEB_ORCH_DECISION: REVIEW 01_LINT_GUARDRAILS
```

Только `ACCEPT` разрешает переход. Следующий packet Architect называет
полным путём:

```text
WEB_ORCH_NEXT_TASK: docs/work/agent_exchange/inbox/02_PACKET_EXECUTION.md
```

Если продолжения нет:

```text
WEB_ORCH_NEXT_TASK: STOP
```

Никаких state-файлов, manifests, lock-файлов и самовольного следующего TZ.
