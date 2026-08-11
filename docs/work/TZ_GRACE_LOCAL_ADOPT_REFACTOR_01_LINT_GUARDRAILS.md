# TZ — Grace Local Adopt refactor / 01 Lint guardrails

Status: READY FOR CODER
Parent: `TZ_GRACE_LOCAL_ADOPT_REFACTOR_MASTER.md`
Priority: P0 — execute before structural split work

## 1. Why this block exists

The current GraceLint implementation checks `GRC010/GRC011/GRC012` in one loop and immediately skips every function whose name begins with `_`.

That behaviour is correct for public FUNCTION_CONTRACT requirements (`GRC010/GRC011`) but incorrect for the size limit (`GRC012`). A private helper can therefore grow beyond 4000 estimated tokens without being reported.

This block closes that gap before the large modules are refactored.

## 2. What we change

Primary files:

- `src/grace_control/tools/grace_lint/checker.py`
- `tests/grace_control/core/test_grace_lint.py`
- `.grace/lint_allowlist.yaml`

Documentation only if required:

- `docs/grace/GRACE_LINT_RULES.md`

### Required semantic change

For every `ast.FunctionDef` and `ast.AsyncFunctionDef`:

1. Compute function source range and `est_tokens = len(source) // 4`.
2. Apply `GRC012` regardless of whether the function is public or private.
3. Continue to apply `GRC010/GRC011` only to public functions/methods.
4. Do not require FUNCTION_CONTRACT blocks for `_private` helpers as part of this task.

In other words:

- `_helper()` with 100 tokens: no `GRC010`, no `GRC011`, no `GRC012`.
- `_huge_helper()` with >4000 estimated tokens: `GRC012`.
- `public_func()` without contract: `GRC010` as today.
- `public_huge_func()` without contract and >4000 tokens: both applicable violations may be reported.

### Implementation shape

Do not solve this by duplicating two full AST walks.

Preferred shape:

- one function walk;
- size check performed for every function;
- contract check guarded by `not node.name.startswith("_")`.

Refactoring `_check_functions()` itself is allowed if it improves clarity, but do not expand scope into unrelated GraceLint rules.

## 3. GRC005 remains unchanged

Keep the existing file limit:

- violation when `len(lines) > 1000`;
- max remains 1000;
- no allowlist entry should be added for current oversized production modules.

Do not change the meaning of physical lines in this task.

## 4. Borderline warning policy

Do **not** invent new lint rule codes or a new severity model merely for this refactor programme.

The 800-line / 2500-3000-token targets in the MASTER are engineering headroom targets, not new canonical lint errors.

A separate future feature may add warnings if wanted. This packet should stay small and deterministic.

## 5. Allowlist cleanup

Inspect `.grace/lint_allowlist.yaml`.

The existing `GRC108` entry for `src/grace_control/adapters/packet_executor.py` contains stale rationale stating that the file is about 232 lines and below the 300-line threshold.

Required:

- remove that stale entry if it is no longer needed;
- or update it only if `GRC108` still legitimately needs a scoped exception after the structural refactor;
- never add `GRC005` or `GRC012` suppressions for the files in this programme.

Prefer removal over perpetuating historical metadata.

## 6. Tests — do we change them?

**Yes. Existing tests are extended, not weakened.**

Modify `tests/grace_control/core/test_grace_lint.py`.

Required cases:

### Existing public oversize test stays

Keep the existing test proving an oversized public function emits `GRC012`.

### Add private oversize test

Add a test equivalent to:

- build a `_huge_helper()` whose source estimates above 4000 tokens;
- lint it;
- assert `GRC012` is present.

### Preserve private contract exemption

Keep/add a test proving a small `_helper()` does not emit `GRC010` merely because it has no FUNCTION_CONTRACT.

### Boundary tests

Add deterministic boundary coverage around the token threshold if practical:

- <=4000 estimated tokens -> no `GRC012`;
- >4000 estimated tokens -> `GRC012`.

Do not make the test depend on an external tokenizer. It must use the same character/4 approximation as the checker.

### Async coverage

Add at least one async private/public case so `ast.AsyncFunctionDef` cannot regress independently.

## 7. What we do NOT change

Do not modify:

- API behaviour of `/api/tools/grace-lint/run` except that it now correctly reports oversized private functions;
- allowlist matching semantics;
- unrelated GRC100+ rules;
- FUNCTION_CONTRACT format;
- module contract/map rules;
- max values 1000 / 4000;
- CLI invocation shape.

## 8. Verification

Run at minimum:

```bash
.venv/bin/python -m pytest tests/grace_control/core/test_grace_lint.py -q
.venv/bin/python scripts/grace_lint.py src/grace_control/tools/grace_lint/checker.py
make lint
```

If project tooling uses another discovered Python path, use the repository-supported equivalent.

## 9. Acceptance criteria

1. `GRC012` reports oversized private functions/methods.
2. Private functions remain exempt from `GRC010/GRC011` solely because they are private.
3. Public function contract behaviour is unchanged.
4. 4000-token max is unchanged.
5. 1000-line max is unchanged.
6. No new `GRC005/GRC012` allowlist entries are added.
7. Stale `packet_executor.py` GRC108 allowlist rationale is removed/corrected.
8. GraceLint unit tests pass.
9. `make lint` passes for the code state expected by this packet; if existing oversized modules now surface additional `GRC012` findings, report them explicitly rather than suppressing them.

## 10. Coder submission

Report:

- exact checker logic changed;
- tests added/updated;
- whether new private `GRC012` violations were discovered in repository code;
- any stale allowlist entry removed;
- verification commands and results.
