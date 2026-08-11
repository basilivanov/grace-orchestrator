# TZ 06_ACCEPTANCE_PIPELINE — Grace Local Adopt acceptance-pipeline headroom

Status: READY FOR CODER
Source programme: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Source block: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_06_NEAR_LIMIT_FOLLOWUP.md` Part A
Dependencies: block 01 accepted; packet-execution boundary settled in block 02; block 05 hard-limit admin work accepted

## Coder protocol

You are the Coder for this named TZ. Read and execute **only this file**. Do not open or start another inbox task/TZ unless the Architect explicitly names it after ACCEPT.

Before editing anything:

1. Work in `/opt/grace-orchestrator`.
2. Fast-forward sync with GitHub. The checkout must be clean and updated from `origin/main`; use fast-forward-only sync and do not create a merge commit.
3. If the checkout cannot fast-forward cleanly, stop and report the blocker; do not overwrite local work.

After implementation:

1. Run the required verification below.
2. Commit the implementation.
3. Push the commit to GitHub.
4. Create **only** `docs/work/agent_exchange/outbox/06_ACCEPTANCE_PIPELINE_SUBMISSION.md` for the report.
5. Do not create the next task, review file, `state.json`, lock files, orchestration metadata, or any other coordination file.

The submission must contain these exact lines with the real implementation commit SHA:

```text
WEB_ORCH_REPORT: SUBMISSION 06_ACCEPTANCE_PIPELINE
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <commit-sha>
WEB_ORCH_CHECKS: PASS
```

If the Architect later returns REVIEW, read only `docs/work/agent_exchange/inbox/06_ACCEPTANCE_PIPELINE_REVIEW.md`, fix that review, and report only to `docs/work/agent_exchange/outbox/06_ACCEPTANCE_PIPELINE_RESUBMISSION.md`.

## Goal

Create substantial structural headroom in the near-limit acceptance pipeline while preserving acceptance behavior exactly.

Primary target:

- `src/grace_control/core/acceptance_pipeline.py`

The current module contains the public acceptance entry points, T0/T1/T2 orchestration, replay routing, command/shell handling, evidence/report composition and frontend acceptance helpers. Refactor it into a bounded compatibility surface backed by coherent acceptance-specific owners/helpers rather than waiting for it to cross the 1000-line hard limit.

Required structural result:

- `acceptance_pipeline.py` must remain `<= 1000` physical lines and should target approximately `<= 650–750` lines with practical headroom;
- every touched/new function or async function must remain `<= 4000` Grace-estimated tokens (`len(source) // 4`), with large orchestration functions normally `<= 2500–3000`;
- every new Python module must be `<= 1000` lines, preferably `<= 800`;
- split by real responsibility, not arbitrary line ranges, compressed code, giant expressions, dynamic service-locator tricks or identifier-obscuring lint workarounds.

This packet implements **only Part A of block 06**. Do not start the admin near-limit work in this TZ.

## Owned write scope

Primary:

- `src/grace_control/core/acceptance_pipeline.py`

Expected new focused modules under `src/grace_control/core/` when a coherent owner is justified, for example:

- acceptance command/stage execution support;
- acceptance scope/gate preparation;
- acceptance report/evidence composition;
- frontend acceptance/replay support when that forms a clean boundary.

Directly affected acceptance tests may be changed or extended only under the test policy below.

Optional only for a genuine textual **non-size** GraceLint false positive created by moved code:

- `.grace/lint_allowlist.yaml`

Any allowlist entry must be narrow and truthful. Never add a `GRC005` or `GRC012` suppression. Do not hide identifiers with `getattr`, `__dict__`, split strings or similar constructions merely to satisfy textual lint.

### Explicitly out of scope

Do not modify/refactor the block-06 admin targets in this TZ:

- `src/grace_control/api/routers/admin_controls.py`
- `src/grace_control/services/admin_cross_project_service.py`
- `src/grace_control/services/admin_mutation_service.py`
- `src/grace_control/api/routers/admin_control_center.py`

Do not reopen block 02 packet execution, block 05 admin services, merge/planning work, UI/templates or product behavior unless a concrete and narrowly test-backed compatibility fix is unavoidable.

Frozen by default:

- `src/grace_control/db/schema.py`
- Alembic migrations
- `src/grace_control/core/contracts.py`
- `src/grace_control/config/settings.py`
- `src/grace_control/core/state_machine.py`
- public API schemas/routes

If an unavoidable compatibility reason requires a frozen file, keep it minimal, test it and explain it in the submission.

## Existing authoritative owners to inspect and reuse

Before coding, map the current acceptance responsibilities and reuse the existing boundaries rather than duplicating them:

- `CommandRunner` — command execution, cwd/output/timeout/result capture boundary;
- `ScopeGuard` and `get_changed_files` — changed-file and scope validation boundary;
- `EvidenceCollector` and `check_expected_evidence` — evidence collection/requirement boundary;
- `gate_resolver` (`resolve_default_gates`, `resolve_default_t0`, `resolve_touched_areas`) — automatic verification gate selection;
- `core.contracts` — acceptance profiles, stage/report/verdict DTOs and packet contract;
- existing frontend acceptance helpers/services currently called by `acceptance_pipeline.py`;
- packet-executor and replay services that consume the public acceptance entry points.

Do not create a second implementation of these rules merely to reduce file size.

## Compatibility surface that must remain stable

Preserve the existing import path and callable contracts for at least:

- `grace_control.core.acceptance_pipeline.run_acceptance_pipeline`
- `grace_control.core.acceptance_pipeline.run_acceptance_stage_replay`
- `grace_control.core.acceptance_pipeline.AcceptancePipeline`
- `AcceptancePipeline.__init__(...)`
- `AcceptancePipeline.run(...)`

Before moving internals, search current code/tests for direct imports, calls or monkeypatches of module-level/private helpers and preserve any demonstrated seam via a wrapper/re-export or equally compatible target.

Do not force changes in packet executor or replay callers just because internals moved.

## Required responsibility decomposition

Use the current code and tests as the contract. The exact module names are flexible, but the extraction must be coherent.

### 1. Stable acceptance coordinator

The public pipeline surface should coordinate acceptance stages rather than own every implementation detail.

Preserve the current stage sequence and early-return semantics:

- T0 scope/lint;
- T1 targeted verification;
- T2 full checks;
- frontend T2 browser / T3 visual routing where enabled;
- expected-evidence verification;
- final report/verdict composition.

Do not change when a later stage is or is not executed after an earlier failure.

### 2. Changed-base and environment preparation

Preserve exactly the current changed-file/base precedence and side effects used by public entry points:

- `base_sha` before `base_ref` before `GRACE_BASE_REF` before the current fallback;
- changed-file lookup against the supplied worktree;
- failure to obtain changed files retains the current fallback behavior;
- `GRACE_BASE_SHA` propagation when `base_sha` is supplied;
- worktree/cwd/run-directory handling.

Do not introduce ambient project selection or change process/environment semantics in this refactor.

### 3. T0 scope/contract/lint behavior

Preserve:

- packet-contract validation;
- `ScopeGuard` validation and exact profile-dependent blocking behavior;
- STRICT vs FAST/NORMAL handling of scope violations;
- no-change/empty-diff behavior;
- explicit `verification.t0` semantics, including an explicit empty list;
- default T0 resolution through `gate_resolver` and existing fallback behavior;
- command origins;
- command order and early failure mapping;
- StageResult name/status/summary/blocking issues/scope violation representation.

### 4. T1/T2 command semantics

Preserve all existing observable behavior, including:

- explicit verification commands vs automatic resolver defaults;
- explicit empty T1/profile behavior;
- current command filtering rules;
- command order and origins;
- shell-string preservation vs argv-list handling;
- shell-operator and leading environment-assignment detection;
- cwd/worktree, output directory, timeout and stdout/stderr capture semantics;
- FAST/NORMAL/STRICT behavior;
- failure summary/reason/verdict mapping.

Do not normalize/requote shell strings in a way that changes command execution.

### 5. Frontend acceptance and replay

Preserve current `run_acceptance_stage_replay` behavior for:

- `full_acceptance`;
- `t0`;
- `t1`;
- `t2`;
- `t2_browser`;
- `t3_visual`;
- unsupported replay stage `ValueError` behavior.

Preserve frontend stage routing, run IDs, skipped-stage semantics, browser/visual failure behavior, stage order and evidence collection.

If frontend helper code is extracted, keep any currently consumed import/patch seams compatible.

### 6. Evidence and final report semantics

Preserve:

- evidence collected from the same stages at the same points;
- `check_expected_evidence` inputs and timing;
- STRICT missing-evidence result (`BLOCKED`) versus non-STRICT rework result;
- `scope_violations`, `evidence_issues`, stage ordering and summaries;
- `legacy_result` / `legacy_ok` / `legacy_domain_status` current informational semantics after deterministic gates pass;
- exact `AcceptanceProfile`, `FinalVerdict`, `StageName` and `StageStatus` values;
- report DTO keys/serialization behavior.

This is not a policy redesign. Do not reinterpret legacy results, evidence requirements or profile behavior.

## Behaviour that must not drift

This is refactor-only. Preserve, where applicable:

- accepted flow;
- T0/T1/T2 failure and short-circuit flow;
- scope/frozen-scope rejection;
- no-change behavior;
- command failure and timeout mapping;
- command stdout/stderr/cwd/output artifacts;
- acceptance profile semantics;
- changed-file/base SHA behavior;
- evidence/report output;
- frontend browser/visual stage behavior;
- replay behavior;
- packet-executor integration;
- public imports and signatures.

Do not turn existing exceptions into reports or reports into exceptions except where the current contract already does so.

## Regression protection / tests

Existing behavioural tests are the contract and must not be weakened.

Before coding, discover the actual current tests/callers. At minimum inspect and run the relevant existing coverage around:

- `tests/grace_control/core/test_acceptance_pipeline.py`;
- `tests/grace_control/adapters/test_packet_executor_acceptance.py`;
- `tests/grace_control/api/test_dev_replay_acceptance.py`;
- any current frontend acceptance / gate-resolver / acceptance replay tests that import or exercise moved seams.

Keep coverage for:

1. T0 clean pass and STRICT scope/frozen-scope/invalid-contract failure;
2. explicit empty T0 semantics;
3. FAST/NORMAL/STRICT T1/T2 behavior, including explicit empty T1;
4. command failure and shell/env-prefix execution behavior;
5. worktree cwd and base-SHA/changed-file behavior;
6. evidence requirements and strict/non-strict verdict mapping;
7. report stage ordering/summary/serialization and legacy informational fields;
8. stage replay for T0/T1/T2/frontend/full acceptance;
9. packet-executor acceptance integration;
10. frontend T2-browser/T3-visual routing where current tests cover it.

Allowed test edits:

- add focused tests for newly extracted owners with branching logic;
- minimally retarget a private monkeypatch when ownership genuinely moves;
- add compatibility-import/delegation tests.

Forbidden:

- deleting or weakening behavioral assertions;
- changing expected verdict/profile/stage/result merely to match refactored code;
- broad skip/xfail additions;
- replacing integration coverage with mocks only;
- lowering structural limits.

## Lint / structural guardrails

Accepted block-01 semantics are authoritative:

- `GRC005`: violation only when a Python file has `> 1000` physical lines;
- `GRC012`: violation only when `len(function_source) // 4 > 4000`;
- `GRC012` applies to public/private sync/async functions;
- no `GRC005/GRC012` allowlist suppressions.

MASTER preferred headroom remains an architectural target. Do not park the original file or a new owner at 999 lines, or move a large acceptance method unchanged into a replacement near 4000 tokens when a coherent extraction is available.

## Required verification

First identify and run the smallest directly affected current acceptance test modules from actual imports/calls.

At minimum also run:

```bash
make test
make lint
git diff --check
```

And run:

- `.venv/bin/python -m py_compile` on `acceptance_pipeline.py` and every touched/new acceptance Python module;
- `python3 scripts/grace_lint.py` targeted at `acceptance_pipeline.py` and every touched/new acceptance Python module;
- Ruff targeted at the touched/new modules when available;
- direct acceptance/replay/packet-executor tests that cover the moved responsibilities.

The repository currently has known baseline/environment debt outside this packet. Do not assume a non-zero result is baseline from history. For **every** required command that is non-zero, compare the exact failure-node/output set against a clean parent checkout using the same environment and exact command arguments. Report whether the sets are identical. Any new failure attributable to this packet is a blocker.

`make lint` may currently be blocked by the repository `.venv` lacking Ruff; re-attempt it and report the exact result. Do not claim PASS if it stops before GraceLint.

This acceptance-only packet is not expected to alter OpenAPI. Do not modify generated API docs or public routes.

## Acceptance criteria

Architect ACCEPT requires all of the following:

1. `acceptance_pipeline.py <= 1000` lines with substantial practical headroom, target approximately `<= 650–750` when coherent.
2. No touched/new function exceeds 4000 estimated tokens; large orchestration functions have practical headroom.
3. No new source module exceeds 1000 lines; avoid near-limit parking.
4. Extraction is by real responsibility, not arbitrary slicing/compression.
5. Public acceptance imports, constructor and call signatures remain compatible.
6. T0/T1/T2/frontend stage order, short-circuit and profile behavior remain unchanged.
7. Scope/base-SHA/changed-file/worktree/cwd/environment semantics remain unchanged.
8. Command strings/argv, shell detection, origins, execution and result capture remain unchanged.
9. Evidence, report, verdict, stage and legacy-result semantics remain unchanged.
10. Replay behavior remains unchanged.
11. Existing authoritative `CommandRunner`, `ScopeGuard`, evidence and gate-resolver boundaries are reused rather than duplicated.
12. Existing acceptance/integration tests are not weakened.
13. Directly affected tests pass, or any non-zero set is proven identical to a clean parent baseline.
14. Targeted GraceLint and py_compile pass for every touched/new source file.
15. No `GRC005/GRC012` suppression or new lint-evasion construction is introduced.
16. Diff contains no block-06 admin work or unrelated API/UI/DB/config/state-machine/product changes.
17. Any broad-suite non-zero result is proven against the clean parent rather than merely labelled pre-existing.

## Submission content

Keep `06_ACCEPTANCE_PIPELINE_SUBMISSION.md` concise but include:

- exact implementation commit SHA;
- files created/modified;
- before/after physical line count for `acceptance_pipeline.py`;
- responsibility extraction map and why each new owner is coherent;
- largest function(s) in every touched/new module using `len(source) // 4`;
- public/private compatibility wrappers or re-exports retained and why;
- tests changed/added and confirmation no behavioral assertion was weakened;
- exact targeted test results;
- exact targeted GraceLint/Ruff/py_compile/diff-check results;
- exact `make test` / `make lint` results;
- clean-parent comparisons for every non-zero required command;
- confirmation that acceptance profiles, stage order, command behavior, evidence/report/verdict/replay/base-SHA semantics are unchanged;
- allowlist changes and rationale, if any;
- follow-up debt only; do not start the admin Part B packet.