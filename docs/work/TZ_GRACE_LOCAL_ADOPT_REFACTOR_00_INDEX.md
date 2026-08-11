# TZ — Grace Local Adopt refactor / 00 INDEX

Status: READY FOR CODER
Parent: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`

## Purpose

This file is the execution index for the structural refactor programme. Use it to split work into bounded coder packets and avoid overlapping write scopes.

## Documents

| Block | Document | Primary ownership | Dependency |
|---|---|---|---|
| 01 | `TZ_GRACE_LOCAL_ADOPT_REFACTOR_01_LINT_GUARDRAILS.md` | GraceLint size enforcement | none |
| 02 | `TZ_GRACE_LOCAL_ADOPT_REFACTOR_02_PACKET_EXECUTION.md` | packet execution adapter/pipeline | 01 |
| 03 | `TZ_GRACE_LOCAL_ADOPT_REFACTOR_03_PLANNING_COMPILER.md` | plan compiler + feature planning | 01 |
| 04 | `TZ_GRACE_LOCAL_ADOPT_REFACTOR_04_MERGE_PIPELINE.md` | merge service | 01 |
| 05 | `TZ_GRACE_LOCAL_ADOPT_REFACTOR_05_ADMIN_CONTROL_PLANE.md` | hard-limit admin services | 01 |
| 06 | `TZ_GRACE_LOCAL_ADOPT_REFACTOR_06_NEAR_LIMIT_FOLLOWUP.md` | near-limit modules | 02/05 as applicable |

## Recommended packetisation

Do not assign the full document set to one coder packet.

Recommended minimum split:

### Packet A — lint guardrails

Write scope:

- `src/grace_control/tools/grace_lint/checker.py`
- `tests/grace_control/core/test_grace_lint.py`
- `.grace/lint_allowlist.yaml`
- `docs/grace/GRACE_LINT_RULES.md` only if current documentation becomes false after the code change

Implements block 01.

### Packet B — packet execution facade

Write scope:

- `src/grace_control/adapters/packet_executor.py`
- new execution-focused modules under `src/grace_control/services/` or `src/grace_control/adapters/`
- directly affected packet-execution tests

Implements block 02.

### Packet C — plan compiler

Write scope:

- `src/grace_control/core/plan_compiler.py`
- new validator package/modules under `src/grace_control/core/`
- `tests/grace_control/core/test_plan_compiler.py`
- directly related compiler tests

Implements block 03A.

### Packet D — feature planning service

Write scope:

- `src/grace_control/services/feature_planning_service.py`
- new planning service modules
- directly affected feature-planning tests

Depends on Packet C only if it imports newly extracted compiler internals. Prefer keeping the existing public `PlanCompiler` / `compile_plan` facade so C and D can remain independent.

Implements block 03B.

### Packet E — merge service

Write scope:

- `src/grace_control/services/merge_service.py`
- new merge-focused modules
- directly affected merge tests

Implements block 04.

### Packet F — admin aggregation read side

Write scope:

- `src/grace_control/services/admin_aggregation_service.py`
- new admin read-side modules
- directly affected admin API/service tests

Implements block 05A.

### Packet G — admin control center hard-limit service

Write scope:

- `src/grace_control/services/admin_control_center.py`
- new admin control-center service modules
- directly affected admin service/API tests

Implements block 05B.

### Packet H — acceptance pipeline near-limit

Write scope:

- `src/grace_control/core/acceptance_pipeline.py`
- new acceptance helper modules
- acceptance pipeline tests

Implements block 06A.

### Packet I — admin near-limit follow-up

Write scope:

- `src/grace_control/api/routers/admin_controls.py`
- `src/grace_control/services/admin_cross_project_service.py`
- `src/grace_control/services/admin_mutation_service.py`
- `src/grace_control/api/routers/admin_control_center.py`
- newly extracted admin modules
- directly affected admin tests

Implements block 06B.

This packet may be split further if scope becomes broad. Prefer one responsibility group per packet over one giant admin rewrite.

## Parallelism

After Packet A lands, the following are normally safe to execute in parallel:

- B — packet execution;
- C — plan compiler;
- D — feature planning, if it uses only the preserved public compiler facade;
- E — merge;
- F — admin aggregation;
- G — admin control-center service.

Do not parallelise packets that both edit the same module or the same tests.

H can run in parallel with admin work once B has settled if B extracted/reused acceptance helpers.

I should follow F/G because it may delegate router/service responsibilities to modules introduced there.

## Frozen-by-default files

Unless a packet has a concrete, test-backed reason, do not modify:

- `src/grace_control/db/schema.py`
- Alembic migrations
- `src/grace_control/core/contracts.py`
- `src/grace_control/config/settings.py`
- `src/grace_control/core/state_machine.py`
- public API schemas solely to accommodate internal refactor

If a supposedly refactor-only packet needs any of these, explain why in the coder submission before treating it as normal scope.

## Definition of done per packet

A packet is done when:

1. its owned oversized/near-limit module is structurally reduced;
2. no new source module exceeds 1000 lines;
3. no touched function exceeds 4000 Grace-estimated tokens;
4. public entry points remain compatible;
5. existing behaviour tests pass;
6. focused new tests cover extracted logic when useful;
7. targeted lint passes;
8. the submission reports before/after size metrics.

## Final integration gate

After all packets:

```bash
make lint
make test
make docs-check
make ci
```

Also run a repository-wide size audit using the same semantics as GraceLint and report any remaining `GRC005` / `GRC012` violation, including private functions.
