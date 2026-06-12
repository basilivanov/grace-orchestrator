# Worker handoff: Solar Sage dead-code / legacy delete audit

**Status:** READY_FOR_WORKER
**Date:** 2026-06-12

## Goal

Audit Solar Sage for files that are legacy, obsolete, unrelated to the current product, unused, duplicated, temporary, experimental, or stale.

The output must be a deletion audit with per-file decisions and risk estimates.

This packet may physically delete only high-confidence dead code. Medium/low-confidence candidates must remain in the repo and be listed for manual decision.

## Target repo

- Repository: `basilivanov/solarsage-astro`
- Suggested branch: `audit/dead-code-delete`

## Scope

Audit all project areas:

- frontend source
- backend source
- sidecar/calculation source
- contracts
- tests
- helper scripts
- shell scripts
- CI/workflows
- docs/configs that are executable or referenced by tooling
- old GRACE/orchestrator adapter files
- temporary/debug/demo files
- legacy folders and archived work products

## Do not delete automatically

Do not delete without explicit proof:

- DB migrations
- generated contracts used by build
- public API schemas
- current GRACE source-of-truth docs
- package/build/test config
- CI workflow files
- files imported dynamically
- files referenced only from scripts but still used by gates
- fixtures used by tests

These may be listed as candidates, but deletion confidence must be lower unless proven safe.

## Required audit method

For every candidate file, collect evidence:

1. Direct imports/references via ripgrep.
2. Package/config references.
3. Test references.
4. CI/workflow references.
5. Dynamic references by filename/path/string.
6. Git history clue: old legacy/demo/temp name, stale archive path, or superseded by newer file.
7. Whether current gates pass before deletion.
8. Whether gates pass after deletion if deleted.

Use commands such as:

```bash
git status --short
git rev-parse --short HEAD
find . -type f | sort > /tmp/solarsage_files_before.txt
rg -n "legacy|deprecated|old|backup|tmp|temp|demo|mock|unused|archive|TODO remove|delete me" .
rg -n "<candidate basename>|<candidate import path>|<candidate exported symbol>" .
```

## Decision categories

Each candidate must be assigned one decision:

- `DELETE_NOW` — physically delete in this packet.
- `KEEP_USED` — keep because it is referenced or part of current runtime/gates.
- `KEEP_CONFIG_ROOT` — keep because it is config/tooling source of truth.
- `CANDIDATE_MANUAL_REVIEW` — likely dead, but not enough proof for safe deletion.
- `KEEP_GENERATED_OR_VENDOR` — do not touch.
- `KEEP_HISTORICAL_REPORT` — keep unless product owner wants cleanup of historical docs.

## Deletion confidence / impact probability

For every candidate, report:

- `delete_confidence_percent`: probability that the file is safe to delete.
- `affect_probability_percent`: probability deletion affects runtime, tests, CI, build, or GRACE workflow.

Use this rough scale:

- 95-100% safe: no refs, not config, not generated, obvious obsolete/temp/legacy file.
- 85-94% safe: no refs, but name/location suggests possible manual use.
- 60-84% safe: likely obsolete but dynamic refs/manual tooling possible.
- <60% safe: do not delete automatically.

Only `DELETE_NOW` when safe confidence is at least 90% and affect probability is at most 10%.

## Physical deletion rule

If deleting files:

1. Delete only `DELETE_NOW` files.
2. Do not delete entire folders unless every file inside independently qualifies.
3. After deletion, run relevant gates.
4. If gates fail and failure is not proven pre-existing, revert deletion.

## Required report

Create in Solar Sage:

`docs/work/REPORT_SOLARSAGE_DEAD_CODE_DELETE_AUDIT.md`

The report must include:

1. Base SHA and final SHA.
2. Summary counts:
   - files audited
   - candidates found
   - files deleted
   - files kept
   - manual-review candidates
3. Per-file table with columns:
   - path
   - decision
   - delete_confidence_percent
   - affect_probability_percent
   - evidence refs found / not found
   - what to do
   - why safe or unsafe
4. Deleted files list.
5. Manual-review candidates list.
6. Gates before/after.
7. Confirmation that no runtime logic changed except physical deletion of approved dead files.

## Required gates

Before deletion:

```bash
pnpm test:run
python3 scripts/grace/coverage_audit.py --check
```

After deletion:

```bash
pnpm test:run
python3 scripts/grace/coverage_audit.py --check
```

If practical also run:

```bash
pnpm typecheck
pnpm guardrails:docs
pnpm guardrails:orchestrator
pnpm guardrails:frontend
```

## Acceptance criteria

PASS only if:

1. Report exists with per-file decisions and risk percentages.
2. Every deleted file has evidence of no live references.
3. No medium/low confidence file is deleted.
4. Gates pass after deletion or failures are proven pre-existing.
5. No runtime logic is edited.
6. Manual-review candidates are clearly separated from deleted files.

## Suggested commit message

`chore: remove high-confidence dead code after deletion audit`
