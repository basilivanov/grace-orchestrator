# ТЗ 04 — Serialized merge coordinator

**Depends on:** TZ 01, TZ 02, TZ 03  
**Master:** `TZ_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md`

## Цель

Оставить coder execution параллельным, но запретить concurrent mutation одного target repository при merge/push.

## Сделать

1. Через Alembic добавить `merge_leases` и ORM model:
   - `target_repo_key` PK;
   - `lease_token` fencing token;
   - packet_id;
   - worker_id;
   - acquired_at, expires_at, heartbeat_at;
   - index expires_at.
2. Реализовать DB-backed `MergeCoordinatorService`.
3. На один logical target repo одновременно только один merge lease.
4. Не использовать process-local lock как единственную защиту.
5. Expired lease reclaim только с новым fencing token.
6. Stale holder после fencing loss не имеет права продолжать target mutation.
7. Deterministic merge order для accepted packets одного repo:
   - Wave.order;
   - Packet.created_at;
   - Packet.id.
8. Не ждать завершения всей wave: accepted independent packet может войти в merge queue сразу.
9. После успешного merge/push -> MERGED -> release parallel lease.
10. При terminal failure/cancel/recovery release parallel lease по существующей policy.
11. Crash recovery перед takeover проверяет target repo sanity: dirty state, `MERGE_HEAD`/merge in progress, expected repo root. Не делать blind reset чужого живого состояния.

## Не делать

- Не реализовывать stale-base combined-state verification — это TZ 05.
- Не менять Architect.

## Тесты

1. Two accepted packets, same repo -> one merge holder.
2. Second waits and does not mutate target.
3. Different repos may merge concurrently.
4. Fencing prevents stale holder mutation.
5. Expired lease takeover works after repo sanity check.
6. Target repo never observes concurrent checkout/index mutation in test.
7. Parallel lease освобождается после MERGED, не раньше.

## DONE

Execution остаётся parallel, merge/push одного target repo полностью serialized и crash/fencing-safe.
