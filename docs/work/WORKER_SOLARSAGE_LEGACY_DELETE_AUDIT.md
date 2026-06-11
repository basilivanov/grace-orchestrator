# Worker handoff: Solar Sage legacy delete audit

**Status:** READY_FOR_WORKER
**Date:** 2026-06-11

## Goal

Verify that `legacy/` in `basilivanov/solarsage-astro` is no longer used, then physically remove it if the audit is clean.

This task must prove that deleting `legacy/` does not break runtime, build, lint, typecheck, tests, or GRACE guardrails.

## Target repo

- Repository: `basilivanov/solarsage-astro`
- Worktree example: `/opt/solarsage-astro`
- Branch name suggestion: `chore/remove-legacy-snapshot`

## Background

`legacy/README.md` describes `legacy/` as a frozen old SolarSage frontend snapshot used as a migration source.

Current known signals:

- `legacy/` is outside `grace/frontend.paths`.
- ESLint ignores `legacy/**`.
- `tsconfig.json` excludes `legacy`.
- `legacy/` is outside Next.js `app/` routing.
- The user says migration is believed to be complete.

Do not assume this is enough. Perform a local audit before deletion.

## Required audit steps

Run from repo root:

```bash
set -euo pipefail

cd /opt/solarsage-astro

echo "== current ref =="
git status --short
git rev-parse HEAD

echo "== legacy files =="
find legacy -type f | sort > /tmp/solarsage-legacy-files.txt
wc -l /tmp/solarsage-legacy-files.txt
sed -n '1,120p' /tmp/solarsage-legacy-files.txt

echo "== references to legacy outside legacy/ =="
rg -n --hidden --glob '!legacy/**' --glob '!.git/**' \
  'legacy/|legacy\\b|from .*/legacy|@/legacy|../legacy|legacy/frontend' . \
  > /tmp/solarsage-legacy-refs.txt || true
cat /tmp/solarsage-legacy-refs.txt

echo "== imports that point into legacy =="
rg -n --hidden --glob '!legacy/**' --glob '!.git/**' \
  'from ["'"''][^"'"'']*legacy|import\([^)]*legacy|@/legacy|../legacy|../../legacy' . \
  > /tmp/solarsage-legacy-imports.txt || true
cat /tmp/solarsage-legacy-imports.txt
```

## Deletion step

Only continue if no live code references/imports depend on `legacy/`.

Allowed references after audit:

- docs or reports describing deletion
- old README references that disappear with the deletion
- generated audit files outside repo root are OK

Then run:

```bash
git checkout -b chore/remove-legacy-snapshot || git checkout chore/remove-legacy-snapshot
git rm -r legacy
```

## Required gates after deletion

Run:

```bash
pnpm lint
pnpm typecheck
pnpm test:run
pnpm guardrails:frontend
```

If available and not too slow, also run:

```bash
pnpm guardrails:full
```

If a gate fails because of pre-existing unrelated work, stop and report clearly. Do not paper over failures.

## Required report

Create in `grace-orchestrator`:

`docs/work/REPORT_SOLARSAGE_LEGACY_DELETE_AUDIT.md`

The report must include:

- PASS/FAIL verdict
- base Solar Sage SHA
- final Solar Sage SHA if deletion is committed
- count of files deleted from `legacy/`
- summary of `rg` references outside `legacy/`
- whether any live import/path reference existed
- exact changed files after deletion
- gate outputs for:
  - `pnpm lint`
  - `pnpm typecheck`
  - `pnpm test:run`
  - `pnpm guardrails:frontend`
  - `pnpm guardrails:full` if run
- final decision: safe to delete / not safe to delete

## Acceptance criteria

PASS only if all are true:

1. `legacy/` exists before deletion.
2. Local audit lists files in `legacy/`.
3. No live code/import/config reference outside `legacy/` depends on it.
4. `git rm -r legacy` is the only product deletion/change, except report/metadata if needed.
5. Gates pass after deletion.
6. Report is written to `docs/work/REPORT_SOLARSAGE_LEGACY_DELETE_AUDIT.md`.
7. Final verdict explicitly says `legacy/` is safe to remove physically.

## Safety rules

- Do not modify package manager files.
- Do not modify env files.
- Do not modify auth/payment/subscription code.
- Do not modify backend/API/schema/migrations.
- Do not modify deployment config.
- Do not rewrite migrated source files during this task.
- If any live dependency on `legacy/` is found, do not delete it; report the blockers.

## Commit message suggestion

For Solar Sage, if deletion is clean:

`chore: remove migrated legacy frontend snapshot`

For GRACE report:

`docs: add Solar Sage legacy delete audit report`
