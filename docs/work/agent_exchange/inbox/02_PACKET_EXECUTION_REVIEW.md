# Review — TZ 02_PACKET_EXECUTION

Status: CHANGES REQUIRED

Implementation commit reviewed: `0f4a96b2f4cb10fd9cb9aa810ace8fe33f7b6147`.

Read and fix **only this review**. Do not start another named TZ. After fixing, create only:

`docs/work/agent_exchange/outbox/02_PACKET_EXECUTION_RESUBMISSION.md`

## What is already good

The responsibility split is directionally correct: preflight, rerun dispatch, post-execution/scope, observability, and runtime execution have dedicated owners, while `PacketExecutionAdapter.execute()` is substantially reduced and the old adapter API/helpers remain available. The hard caps are currently technically satisfied and no `GRC005`/`GRC012` suppression was added.

Do not undo that structure. Fix the blockers below without changing packet lifecycle/product behaviour.

## Blocker 1 — the refactor does not yet create the required structural headroom

The programme MASTER explicitly says refactor targets must not merely land immediately below the hard limits. Preferred headroom is <=800 lines per touched module and <=2500–3000 estimated tokens for large orchestration functions.

Current submitted state:

- `src/grace_control/adapters/packet_executor.py`: **983 physical lines** — only 17 lines below `GRC005`.
- `src/grace_control/services/packet_execution_runtime_service.py`: **906 physical lines**.
- `PacketExecutionRuntimeService._prepare_workspace()`: reported at **~3705 Grace tokens**, close to the 4000 hard limit.

That solves the immediate lint violation but not the Local Adopt goal of making normal future work safe.

Required:

1. Reduce `packet_executor.py` to **<=800 physical lines** with a coherent responsibility extraction, not formatting/compression.
2. Give the runtime side meaningful headroom as well: reduce `packet_execution_runtime_service.py` to **<=800 physical lines** and reduce `_prepare_workspace()` to **<=3000 estimated tokens**.
3. Prefer a responsibility boundary such as workspace/preflight construction vs backend/session execution, or final acceptance/persistence orchestration vs facade coordination. Do not create `part1`/`part2` style files.
4. Keep `PacketExecutionAdapter`, `ExecutionResult`, `_call_executor`, and required compatibility helper re-exports available from the old module path.
5. Keep existing dedicated services authoritative; do not duplicate acceptance, rerun, Git, scope, or persistence business rules.

## Blocker 2 — 33 failures in the required full suite are not proven to be baseline

The submission reports:

- focused execution/runtime suite: 106 passed;
- full `tests/grace_control/` suite: 1584 passed, 2 skipped, **33 failed**;
- the 33 failures are described as pre-existing/environment debt.

For a refactor-only packet, `existing behaviour remains unchanged` is an acceptance condition. A verbal classification is not enough, especially because session/profile/backend tests can import or exercise `PacketExecutionAdapter` even when their own files are untouched.

Required verification evidence:

1. Re-run the full required suite on the resubmission commit.
2. Run the same full-suite command against the pre-TZ02 parent baseline `1b6e56d66db285d0c09be4c91fa8b1d9690bbbb1` in a clean temporary worktree/environment-equivalent checkout.
3. Report the exact failing pytest node IDs (or a stable failure list) for baseline and resubmission.
4. ACCEPT requires **no new failures introduced by TZ02**. Do not fix unrelated baseline failures in this packet.
5. If an environmental failure cannot be reproduced identically on both commits, report the exact command/error and isolate it from code-regression claims rather than calling it PASS without evidence.

## Blocker 3 — remove lint-evasion string obfuscation introduced by this refactor

The submitted diff changes readable existing identifiers/keys into constructions such as:

- `"agent_runtime_use_" + "open" + "code_adapter"`;
- dynamic import path fragments using `"open" + "code"`;
- `"or" + "igin"` for the existing `origin` metadata key;
- `adapter="open" + "code"` and similarly split runtime-mode setting names.

These are semantically motivated by textual lint false positives, not by the responsibility split, and they make the refactor harder to read/maintain. Do not game a textual rule by hiding normal domain identifiers in string concatenation.

Required:

1. Restore readable literal identifiers/keys and preserve the pre-refactor import/config semantics.
2. If GraceLint produces a legitimate false positive for moved code, prefer the narrowest justified non-size exception or an existing architectural boundary. `GRC005` and `GRC012` suppressions remain forbidden.
3. Do **not** change GraceLint rule semantics as part of TZ02 merely to make this extraction pass.
4. Do not introduce broad allowlist coverage that would hide unrelated future violations; any non-size exception must be narrowly scoped and explained in the resubmission.

## Behaviour constraints remain unchanged

Preserve exactly the existing:

- selftest-before-backend safety ordering;
- context-required gate;
- rerun one-shot branch and no fall-through;
- target/worktree/base resolution;
- no-change flag semantics;
- existing-agent-commit detection;
- scope enforcement and diagnostics;
- acceptance/verifier/reviewer routing;
- persistence/result/evidence keys;
- runtime event/artifact names and payload shapes;
- cleanup and terminal status behaviour.

No DB schema, API contract, config-default, state-machine, planner, merge, or unrelated product changes.

## Required verification after fixes

Run focused execution/runtime tests first, then at minimum:

```bash
.venv/bin/python -m pytest tests/grace_control/ -q
.venv/bin/python scripts/grace_lint.py src/grace_control/adapters/packet_executor.py
.venv/bin/python scripts/grace_lint.py src/grace_control/services/packet_execution_preflight_service.py
.venv/bin/python scripts/grace_lint.py src/grace_control/services/packet_execution_rerun_service.py
.venv/bin/python scripts/grace_lint.py src/grace_control/services/packet_execution_post_service.py
.venv/bin/python scripts/grace_lint.py src/grace_control/services/packet_execution_observability_service.py
.venv/bin/python scripts/grace_lint.py src/grace_control/services/packet_execution_runtime_service.py
make lint
git diff --check
```

Also lint every additional Python module created by the review fix.

If `.venv` still lacks Ruff, report the exact `make lint` failure and the repository-supported alternate command separately. Do not claim a command itself passed when it did not.

## Resubmission must include

- final line count for `packet_executor.py` and every new/touched execution module;
- final `len(source) // 4` estimate for `execute()`, `_prepare_workspace()`, and the largest function in each touched execution module;
- responsibility -> owner mapping for any additional extraction;
- confirmation that compatibility re-exports remain;
- exact focused-test result;
- exact full-suite result;
- baseline-vs-resubmission failing-test comparison for the pre-existing failures;
- exact targeted GraceLint results;
- exact `make lint` result/blocker;
- confirmation that no behavioural assertion was weakened and no `GRC005/GRC012` suppression was added.

No next task is permitted. This remains `02_PACKET_EXECUTION`.