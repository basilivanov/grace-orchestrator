# ТЗ 03 — Safe atomic claim + parallel leases

**Depends on:** TZ 01, TZ 02  
**Master:** `TZ_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md`

## Цель

Разрешить нескольким workers одновременно claim-ить только действительно совместимые packets одной текущей wave.

## Сделать

1. Добавить новой Alembic revision таблицу `parallel_leases` и ORM model:
   - id PK/token;
   - packet_id UNIQUE;
   - feature_id, wave_id, worker_id;
   - claimed_attempt;
   - scope_json;
   - conflict_keys_json;
   - base_sha nullable;
   - acquired_at, expires_at, heartbeat_at;
   - indexes по feature/wave, worker, expires_at.
2. Реализовать `ParallelConflictService`:
   - normalize scopes;
   - same file conflict;
   - file vs parent dir conflict;
   - parent/child dir conflict;
   - conservative glob/pattern overlap;
   - disjoint paths safe;
   - `conflict_keys` intersection conflict.
3. Реализовать `ParallelLeaseService`: acquire/renew/release/expire/fencing.
4. Реализовать `SafeQueueClaimService.claim_next_atomic(worker_id)`.
5. Candidate selection + dependency/wave/capacity/conflict checks + packet claim + packet lease + parallel lease должны быть одной короткой DB transaction.
6. Для SQLite file DB использовать реально safe serialization (`BEGIN IMMEDIATE` либо эквивалент) + bounded retry/backoff на lock contention.
7. Transaction не должна включать git/network/LLM/tests.
8. Parallel lease держать до merge/failure/cancel/recovery; **не release на ACCEPTED**.
9. `GRACE_MAX_CONCURRENCY=1` сохраняет старое поведение.

## Claim policy

Packet claimable только если:

- dependency policy satisfied;
- earliest claimable wave;
- capacity available;
- no active scope conflict;
- no active `conflict_keys` conflict.

Scope/key conflict = WAIT, packet остаётся READY; это не failure.

## Не делать

- Не реализовывать merge serialization.
- Не делать stale-base integration recheck.

## Тесты

При `GRACE_MAX_CONCURRENCY=4`:

1. 4 disjoint packets одной wave могут быть claimed одновременно.
2. 5-й ждёт capacity.
3. dependent B не claim до A MERGED.
4. overlapping scope serializes.
5. same conflict key serializes при disjoint files.
6. после release конфликтующий packet claimable.
7. real concurrent claim requests к SQLite не могут одновременно захватить конфликтующие packets.
8. expired lease reclaim использует fencing.
9. legacy concurrency=1 regression green.

## DONE

Несколько workers безопасно получают independent packets параллельно, а race между concurrent claims доказан интеграционным SQLite test.
