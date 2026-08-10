# Minimal Agent Exchange Protocol

Работа идёт строго по одному заданию за раз.

## Каталоги

- `inbox/NNN_TASK.md` — новое задание агенту.
- `inbox/NNN_REVIEW.md` — замечания reviewer, если submission не принят.
- `outbox/NNN_SUBMISSION.md` — отчёт агента после выполнения TASK.
- `outbox/NNN_RESUBMISSION.md` — отчёт агента после исправления REVIEW.

## Цикл

1. Агент читает только указанный `NNN_TASK.md` или `NNN_REVIEW.md`.
2. Выполняет работу, запускает проверки, делает commit и push.
3. Пишет короткий `outbox/NNN_SUBMISSION.md` или `NNN_RESUBMISSION.md`.
4. Reviewer читает отчёт и проверяет фактический diff/код.
5. Reviewer выдаёт один из двух результатов:
   - `ACCEPT NNN` — разрешён следующий TASK;
   - `REVIEW NNN` — reviewer создаёт `inbox/NNN_REVIEW.md`, следующий TASK не начинается.
6. Агент никогда не начинает следующий номер самостоятельно.

## Формат submission

```md
# Submission NNN

Status: DONE
Commit: <sha>

Что сделано:
- ...

Проверки:
- ...

Замечания:
- none
```

Не писать длинный отчёт: commit, изменения, проверки, важные оговорки.