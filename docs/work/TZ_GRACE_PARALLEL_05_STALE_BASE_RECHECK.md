# ТЗ 05 — Stale-base integration recheck

**Depends on:** TZ 01–04  
**Master:** `TZ_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md`

## Цель

Не позволять packet, который кодировался и тестировался от старого target SHA, бесконтрольно вливаться в уже изменившийся target branch.

## Сделать

1. Через Alembic добавить nullable columns:
   - `packet_runs.base_sha`;
   - `packet_runs.integration_base_sha`.
2. При создании effective packet workspace сохранять target SHA как `base_sha`.
3. Перед merge под `MergeCoordinatorService` читать current target HEAD.
4. Если `base_sha == current_head` — обычный serialized merge path.
5. Если HEAD advanced — выполнить integration recheck **до target mutation**:
   - создать временный integration worktree от current target HEAD;
   - применить packet branch/commit;
   - при git conflict не менять target;
   - при clean apply прогнать как минимум packet T1 / profile-aware integration verification на combined state.
6. При conflict:
   - packet -> `BLOCKED_RECOVERABLE`;
   - class `stale_base_conflict`;
   - приложить base/current SHA и evidence.
7. При verification failure:
   - target unchanged;
   - packet -> `BLOCKED_RECOVERABLE`;
   - class `integration_verification_failed`;
   - приложить logs/evidence.
8. При success:
   - сохранить `integration_base_sha`;
   - выполнить serialized merge/push;
   - MERGED;
   - release parallel lease.
9. Писать operational metadata в `result_json.parallel_execution`:
   - base_sha;
   - integration_base_sha;
   - stale_base;
   - conflict_keys;
   - integration_recheck = skipped|passed|failed.
10. Setting: `GRACE_INTEGRATION_RECHECK_ON_STALE_BASE=true` default true.

## Не делать

- Не добавлять LLM automatic conflict resolution.
- Не делать speculative execution зависимых packets.

## Тесты

1. A и B стартуют от X; A merges -> Y; B обнаруживает stale base.
2. B clean applies to Y + tests pass -> merges.
3. Git conflict -> recoverable block, target unchanged.
4. No git conflict but combined-state test fails -> recoverable block, target unchanged.
5. `base_sha`/`integration_base_sha` persisted.
6. Recheck skipped when target HEAD не изменился.

## DONE

Ни один stale packet не меняет target branch без успешной проверки на актуальном combined state.
