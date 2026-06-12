# Review: Solar Sage meaningful GRACE contracts rework R2

**Review status:** NEEDS_REWORK
**Date:** 2026-06-12

## Reviewed refs

- Target repo: `basilivanov/solarsage-astro`
- Previous reviewed head: `336350d`
- Reviewed head: `ae363c9`

## Summary

R2 fixed some runtime-breaking issues, but it still does not meet the meaningful-contract acceptance criteria.

The shell scripts no longer use raw `//` comments, so bash syntax is likely safe again. However, the shell GRACE markers are still malformed and the shell contracts are still boilerplate/wrong. The final report evidence is also still stale for the meaningful-contract packet.

## Positive findings

- The R2 diff is narrow: report/coverage files, `lib/date.ts`, `lib/env/production-guard.mjs`, and shell scripts.
- `lib/env/production-guard.mjs` now has a meaningful contract instead of `varies` placeholders.
- `lib/date.ts` now has function contracts for core exported date helpers.
- `//` comments in shell files were changed to `#`, so the previous direct bash runtime break is addressed.

## Blocking findings

### 1. Shell markers are still malformed

Search still finds shell files containing:

```text
# #########################################// START_MODULE_CONTRACT
```

Example: `scripts/alert.sh` still has this malformed joined marker. It is now a shell comment, but it is not a valid standalone GRACE marker.

Required fix:

- replace all `# #########################################// START_MODULE_CONTRACT` with a normal banner close and standalone `# START_MODULE_CONTRACT`;
- do the same for any other joined marker variants;
- rerun the grep/search and prove zero remaining instances.

### 2. Shell contracts are still boilerplate and factually wrong

Example: `scripts/alert.sh` says:

- `ROLE: Tooling script`
- `purpose: Tool: alert`
- `inputs: Function args`
- `outputs: Return values`
- `side_effects: n/a (pure)`
- `emitted_logs: n/a (pure)`
- `invariants: n/a`

But the script reads environment variables, accepts a message argument, calls Telegram via `curl`, writes stdout/stderr, and exits non-zero on validation/send failure. This is not pure and not meaningful.

Required fix:

- make shell contracts file-specific;
- document env vars, positional args, curl/network side effect, stdout/stderr output, and exit behavior.

### 3. Meaningful-contract final report is still stale

`docs/work/REPORT_SOLARSAGE_GRACE_MEANINGFUL_CONTRACTS_REWORK.md` still reports final SHA `9049638` and test result `725 passed, 2 failed, 1 skipped`.

R2 updated the slice coverage audit report, not the required meaningful-contract report.

Required fix:

- update `REPORT_SOLARSAGE_GRACE_MEANINGFUL_CONTRACTS_REWORK.md` with head `ae363c9` or the new rework SHA;
- include the actual gate evidence: `grace_lint`, backend tests, frontend tests, coverage audit, and `bash -n`;
- include remaining placeholder/malformed-marker counts.

### 4. Function contracts are still incomplete for `lib/date.ts`

R2 added contracts for several helpers, but `startOfWeek` and `formatWeekRange` are still exported and still lack `START_FUNCTION_CONTRACT` blocks.

Required fix:

- add function contracts for every exported function in `lib/date.ts`, or document explicit skip reasons in the final report.

## Required rework

1. Fix all malformed shell joined markers.
2. Rewrite shell contracts so they are meaningful and not generic boilerplate.
3. Add missing function contracts for exported date helpers or document skip reasons.
4. Update the correct final report: `REPORT_SOLARSAGE_GRACE_MEANINGFUL_CONTRACTS_REWORK.md`.
5. Prove gates with exact outputs and grep/search results.

## Final decision

**NEEDS_REWORK.**

Runtime shell safety improved, but GRACE canon quality is still not PASS because malformed markers and boilerplate contracts remain in shell scripts, the required report is stale, and exported helper function contracts are incomplete.
