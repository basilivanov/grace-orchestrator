# GRACE Safe Parallel Execution — implementation index

**Master spec:** `docs/work/TZ_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md`

Не выполнять master spec одним большим change-set. Реализовывать этапы ниже по порядку.

## Порядок

1. `TZ_GRACE_PARALLEL_01_ALEMBIC_FOUNDATION.md`
2. `TZ_GRACE_PARALLEL_02_PACKET_CONTRACT_AND_ARCHITECT.md`
3. `TZ_GRACE_PARALLEL_03_SAFE_ATOMIC_CLAIM.md`
4. `TZ_GRACE_PARALLEL_04_SERIALIZED_MERGE.md`
5. `TZ_GRACE_PARALLEL_05_STALE_BASE_RECHECK.md`
6. `TZ_GRACE_PARALLEL_06_MULTIWORKER_INTEGRATION.md`

## Общие правила

- Per-packet worktree остаётся базовой git-изоляцией.
- Shared worktree per wave не вводить.
- `GRACE_MAX_CONCURRENCY=1` должен сохранять последовательное backward-compatible поведение.
- Следующий этап начинать только после зелёных targeted/regression tests предыдущего.
- Не смешивать соседние этапы в один change-set без объективной необходимости.
- Если краткое ТЗ допускает две трактовки, master spec является источником истины.

## Финальный отчёт

После этапа 6 создать:

`docs/work/REPORT_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md`
