# ТЗ 06 — Full multi-worker integration + observability

**Depends on:** TZ 01–05  
**Master:** `TZ_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md`

## Цель

Собрать все предыдущие этапы в реальный multi-worker runtime и доказать end-to-end, что independent packets выполняются параллельно, конфликтующие сериализуются, а merge остаётся безопасным.

## Сделать

1. Подключить `SafeQueueClaimService` к реальному worker/supervisor execution path.
2. Подключить `MergeCoordinatorService` и stale-base recheck к реальному merge path.
3. Один worker по-прежнему исполняет один active packet; масштабирование только количеством worker processes.
4. Сохранить default `GRACE_MAX_CONCURRENCY=1`.
5. Поддержать безопасный режим, например:
   - `GRACE_MAX_CONCURRENCY=8`;
   - 8 worker processes.
6. Settings:
   - `GRACE_PARALLEL_SCOPE_GUARD_ENABLED=true`;
   - `GRACE_MERGE_SERIALIZATION_ENABLED=true`;
   - `GRACE_INTEGRATION_RECHECK_ON_STALE_BASE=true`.
7. Unsafe multi-worker mode не должен случайно включаться при отключённой merge serialization.
8. Обновить stale cleanup:
   - packet lease recovery;
   - parallel lease release/reclaim;
   - merge lease recovery + repo sanity check;
   - не трогать worktree живого worker.
9. Добавить typed wait/failure reasons минимум:
   - `waiting_for_dependency`;
   - `waiting_for_scope_conflict`;
   - `waiting_for_conflict_key`;
   - `waiting_for_merge_slot`;
   - `waiting_for_wave_completion`;
   - `parallel_lease_lost`;
   - `merge_lease_lost`;
   - `stale_base_conflict`;
   - `integration_verification_failed`;
   - `merge_conflict`.
10. Минимальная diagnostics/API observability:
   - effective max concurrency;
   - active workers;
   - active parallel leases;
   - active merge lease holder;
   - packet base/integration SHA;
   - current wait reason;
   - integration recheck result.
11. Большой redesign admin UI не делать; badges допустимы только если дешёво.

## Обязательные end-to-end tests

На file-backed SQLite и реальных concurrent workers/tasks:

1. Wave с 4–8 independent packets -> несколько реально RUNNING одновременно.
2. Disjoint scopes + empty conflict keys -> parallel execution.
3. Same/overlapping scope -> второй ждёт, затем стартует от свежего HEAD.
4. Same `conflict_key` при разных файлах -> serialization.
5. `depends_on` consumer не стартует до merge producer.
6. Несколько ACCEPTED packets -> target repo мутируется строго одним merger одновременно.
7. Stale independent packet проходит recheck перед merge.
8. Conflict/failing combined-state test оставляет target unchanged.
9. Worker crash/expired lease recovery не создаёт двойной claim/merge.
10. `GRACE_MAX_CONCURRENCY=1` regression: старое последовательное поведение сохранено.

## Smoke / performance proof

Добавить воспроизводимый smoke test или test fixture, показывающий:

- N независимых искусственно медленных packets;
- wall-clock заметно меньше последовательной суммы;
- merge operations при этом не перекрываются.

Не фиксировать жёсткий performance threshold, зависящий от CI machine; доказать concurrency через timestamps/overlap assertions.

## Финальный отчёт

Создать `docs/work/REPORT_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md` и включить:

- base/final SHA;
- Alembic revisions и legacy upgrade path;
- schema changes;
- Architect prompt changes;
- safe claim algorithm;
- scope/conflict-key rules;
- merge serialization;
- stale-base behavior;
- tests + results;
- multi-worker smoke timings/overlap proof;
- known limitations;
- подтверждение, что новые ad-hoc SQLite migrations не добавлялись.

## DONE

Feature считается завершённой только если реальный multi-worker test доказывает parallel execution independent packets, безопасную serialization конфликтов/merge и backward compatibility при concurrency=1.
