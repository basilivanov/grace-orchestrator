# ТЗ 02 — Packet contract + Architect parallel planning

**Depends on:** TZ 01  
**Master:** `TZ_GRACE_SAFE_PARALLEL_WAVE_EXECUTION.md`

## Цель

Добавить metadata для безопасного параллелизма и научить Architect строить wave как parallel frontier, не смешивая producer/consumer packets.

## Сделать

1. Расширить canonical coder packet schema полем `conflict_keys: list[str]`.
2. Для новых architect outputs поле обязательно, допускается `[]`.
3. Legacy output без поля -> canonicalize to `[]` без поломки старых features.
4. Normalize keys: trim, reject empty, reject duplicates after normalization.
5. Обновить parser/materializer/contract models.
6. Усилить dependency validation:
   - `depends_on` references existing packet titles;
   - graph acyclic;
   - для новых plans dependency должен быть в более ранней wave;
   - legacy same-wave dependency остаётся runtime-safe/backward compatible.
7. Изменить canonical `src/grace_control/core/prompts/architect_prompt.md`:
   - same wave = parallel candidates;
   - producer/consumer -> `depends_on` + later wave;
   - overlapping `scope` нельзя считать safe parallel;
   - cross-file shared contract -> dependency или общий `conflict_key`;
   - DB/ORM/Alembic delta -> `db-schema`, `alembic-head`;
   - migration + соответствующий ORM delta держать атомарно;
   - correctness first, затем maximize wave width;
   - добавить pre-emit validation checklist.
8. Если есть versioned architect artifact schema — bump её; иначе не вводить отдельный global versioning только ради поля.

## Не делать

- Не реализовывать scheduler/leases/merge coordination.
- Не менять worktree semantics.

## Тесты

- `conflict_keys` materialized.
- Missing legacy field -> `[]`.
- Invalid type/empty/duplicate rejected.
- Missing dependency detected.
- Dependency cycle detected.
- Invalid wave ordering detected для new plan.
- Architect prompt содержит parallel-safety rules и `conflict_keys` в schema/example.

## DONE

Architect выдаёт graph, пригодный для safe wide-wave execution, а runtime contract читает и новые, и legacy packets.
