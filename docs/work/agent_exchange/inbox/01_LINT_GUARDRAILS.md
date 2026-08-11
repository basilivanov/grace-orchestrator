# TZ 01_LINT_GUARDRAILS — Grace Local Adopt lint guardrails

Status: READY FOR CODER
Source programme: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Source block: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_01_LINT_GUARDRAILS.md`
Execution order: first packet; no later Local Adopt packet may start before Architect ACCEPT.

## Coder protocol

You are the Coder for this named TZ. Read and execute **only this file**. Do not open or start any other inbox task/TZ unless the Architect explicitly names it after ACCEPT.

Before editing anything:

1. Work in `/opt/grace-orchestrator`.
2. Fast-forward sync with GitHub. The checkout must be clean and updated from `origin/main`; use a fast-forward-only sync and do not create a merge commit.
3. If the checkout cannot fast-forward cleanly, stop and report the blocker; do not overwrite local work.

After implementation:

1. Run the required verification below.
2. Commit the implementation.
3. Push the commit to GitHub.
4. Create **only** `docs/work/agent_exchange/outbox/01_LINT_GUARDRAILS_SUBMISSION.md` for the report.
5. Do not create the next task, review file, `state.json`, lock files, orchestration metadata, or any other coordination file.

The submission must contain these exact lines with the real commit SHA:

```text
WEB_ORCH_REPORT: SUBMISSION 01_LINT_GUARDRAILS
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <commit-sha>
WEB_ORCH_CHECKS: PASS
```

If the Architect later returns REVIEW, read only `docs/work/agent_exchange/inbox/01_LINT_GUARDRAILS_REVIEW.md`, fix that review, and report only to `docs/work/agent_exchange/outbox/01_LINT_GUARDRAILS_RESUBMISSION.md`.

## Goal

Fix GraceLint so the hard function-size limit `GRC012` applies to **all** Python functions and async functions, including names beginning with `_`, while private functions remain exempt from the public FUNCTION_CONTRACT rules `GRC010/GRC011`.

This packet is guardrail correctness only. Do not start structural splitting of the large production modules yet.

## Hard limits that must remain unchanged

- Python source file: violation only when physical line count is `> 1000` (`GRC005`).
- Function / async function: violation only when `len(source) // 4 > 4000` (`GRC012`).
- Do not lower or raise either hard limit.
- Do not introduce new warning codes or severity models for the preferred 800-line / 2500–3000-token engineering headroom targets.
- Do not add `GRC005` or `GRC012` allowlist suppressions.

## Owned write scope

Primary files:

- `src/grace_control/tools/grace_lint/checker.py`
- `tests/grace_control/core/test_grace_lint.py`
- `.grace/lint_allowlist.yaml`

Documentation may be changed **only if the code change makes current lint documentation false**:

- `docs/grace/GRACE_LINT_RULES.md`

Everything else is out of scope unless a directly exposed test-backed necessity is unavoidable. If that happens, keep the change minimal and explain it in the submission.

Frozen by default for this refactor programme:

- `src/grace_control/db/schema.py`
- Alembic migrations
- `src/grace_control/core/contracts.py`
- `src/grace_control/config/settings.py`
- `src/grace_control/core/state_machine.py`
- public API schemas

Do not touch these in this packet.

## Required checker semantics

For every `ast.FunctionDef` and `ast.AsyncFunctionDef`:

1. Compute the function source range using the existing checker semantics.
2. Compute the same existing estimate: `est_tokens = len(source) // 4`.
3. Apply `GRC012` to every function, public or private.
4. Apply `GRC010/GRC011` only when `not node.name.startswith("_")`.
5. Do **not** require FUNCTION_CONTRACT blocks for `_private` helpers.

Expected behaviour:

- `_helper()` around 100 estimated tokens: no `GRC010`, no `GRC011`, no `GRC012`.
- `_huge_helper()` above 4000 estimated tokens: `GRC012`.
- public function without contract: `GRC010` as before.
- public oversized function without contract: all independently applicable violations may be reported.

Implementation shape:

- keep one function/AST walk;
- perform the size check for every function;
- guard only contract checks behind the public/private condition;
- do not duplicate two full AST walks;
- refactoring `_check_functions()` for clarity is allowed, but unrelated GraceLint rules are out of scope.

## GRC005 semantics must not drift

Keep the existing file-size rule exactly as-is:

- threshold remains 1000 physical lines;
- violation is when `len(lines) > 1000`;
- do not redefine physical lines;
- do not compress production code to game the limit;
- do not add a current oversized production module to a `GRC005` allowlist.

## Allowlist cleanup

Inspect `.grace/lint_allowlist.yaml`.

There is stale historical rationale for a `GRC108` entry on `src/grace_control/adapters/packet_executor.py` claiming the file is roughly 232 lines and below the 300-line threshold.

Required:

- remove the stale entry if it is no longer needed;
- update it only if `GRC108` still legitimately requires a narrowly scoped exception in the current code;
- prefer removal over carrying stale metadata;
- never add `GRC005` or `GRC012` suppressions for this programme.

## Tests

Modify `tests/grace_control/core/test_grace_lint.py`. Existing behavioural assertions must not be weakened.

Required coverage:

1. Keep the existing public oversized-function test proving `GRC012`.
2. Add a private oversized helper test: `_huge_helper()` above 4000 estimated tokens must emit `GRC012`.
3. Preserve/add a small private helper test showing a private function without FUNCTION_CONTRACT does **not** emit `GRC010` merely because it is private.
4. Add deterministic boundary coverage if practical:
   - `<= 4000` estimated tokens => no `GRC012`;
   - `> 4000` estimated tokens => `GRC012`.
5. Use the checker’s `len(source) // 4` approximation; do not use an external tokenizer.
6. Include at least one async function case so `ast.AsyncFunctionDef` cannot regress independently.

Do not delete or weaken tests to make the refactor pass. Do not add broad skips/xfails.

## Explicit non-goals

Do not change:

- `/api/tools/grace-lint/run` behaviour except that oversized private functions are now correctly reported;
- allowlist matching semantics;
- unrelated `GRC100+` rules;
- FUNCTION_CONTRACT format;
- module contract/map rules;
- CLI invocation shape;
- public HTTP routes/methods/response shapes;
- DB schema or migrations;
- packet/planner/merge/admin business behaviour.

Do not begin Local Adopt blocks 02–06.

## Required verification

Run at minimum:

```bash
.venv/bin/python -m pytest tests/grace_control/core/test_grace_lint.py -q
.venv/bin/python scripts/grace_lint.py src/grace_control/tools/grace_lint/checker.py
make lint
```

If the repository-supported Python path differs, use the supported equivalent and report the exact command.

Also run `git diff --check` before commit.

If the corrected private-function size check exposes existing production `GRC012` violations outside this packet, **do not suppress or refactor those modules here**. Report the exact files/functions/findings in the submission so the Architect can route them into the later structural packets. Do not claim a command passed if it failed; distinguish focused packet checks from newly exposed repository debt explicitly.

## Acceptance criteria

The Architect will review the actual commit and diff. This TZ is acceptable only when all of the following hold:

1. `GRC012` reports oversized private functions/methods.
2. Private functions remain exempt from `GRC010/GRC011` solely because they are private.
3. Public function contract behaviour remains unchanged.
4. The 4000 estimated-token hard max is unchanged.
5. The 1000 physical-line hard max is unchanged.
6. No new `GRC005/GRC012` allowlist entry exists.
7. The stale `packet_executor.py` `GRC108` allowlist rationale is removed or accurately justified if still required.
8. GraceLint unit tests pass.
9. The checker itself passes targeted GraceLint.
10. Existing behavioural tests are not weakened.
11. The diff contains no unrelated structural refactor or product behaviour change.

## Submission content

Keep `01_LINT_GUARDRAILS_SUBMISSION.md` concise but include:

- exact checker logic changed;
- tests added/updated;
- whether the corrected rule discovered any private `GRC012` violations in repository code;
- allowlist entry removed/changed;
- exact verification commands and outcomes;
- any known follow-up debt, without starting the next packet.
