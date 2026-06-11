# Review: Solar Sage GRACE slice coverage audit

**Review status:** NEEDS_REWORK
**Date:** 2026-06-11

## Reviewed refs

- Solar Sage: `66ce0e8`
- Review base: `06b2431`

## Scope reviewed

Solar Sage diff from `06b2431` to `66ce0e8` includes:

- `scripts/grace/coverage_audit.py` added
- `docs/work/REPORT_SOLARSAGE_GRACE_SLICE_COVERAGE_AUDIT.md` added
- `docs/work/solarsage_grace_slice_coverage.json` added
- small docs cleanup in `docs/10_GRACE_Project_Agent_Guide.md`
- tiny `grace/development-plan.xml` update

No runtime product source was changed.

## Positive findings

- Audit script exists and is easy to run: `python3 scripts/grace/coverage_audit.py`.
- JSON inventory exists and includes file-level rows.
- Report includes a useful first coverage picture:
  - 496 audited files
  - 60 full marker files
  - 32 partial marker files
  - 404 no-marker files
  - 109 unmapped files
- The report correctly highlights the main issue: product frontend slices have near-zero GRACE marker coverage.
- Recommended adoption waves are directionally useful.

## Blocking findings

### 1. JSON is not deterministic although the report claims it is

The report states the script is deterministic and repeated runs produce identical JSON.

However the script writes a fresh timestamp into JSON on every run:

```py
"generated_at": datetime.now().isoformat()
```

This means two runs cannot produce byte-identical JSON unless the timestamp is removed, frozen, or excluded from the determinism check.

Required fix:

- remove `generated_at`, or
- set it from an explicit env var / CLI arg, or
- place generated timestamp only in the markdown report, not in the machine inventory.

### 2. Slice classifier has path-order bugs

The classifier uses first-match prefix rules. Some broad prefixes appear before more specific ones.

Examples:

- `app/(grace)/` and `components/today/` are classified as `SLICE-TODAY-CALENDAR` before `components/today/tab-bar.tsx` can be classified as `SLICE-SHELL-NAVIGATION`.
- `apps/api/app/` is classified as `SLICE-BACKEND-API-ROUTERS` before backend subareas such as services/core/db can be separated.
- backend service patterns use paths like `apps/api/services/`, but the actual repo uses `apps/api/app/services/`.

This makes the slice-level coverage numbers unreliable.

Required fix:

- classify more-specific prefixes before broad prefixes;
- use actual repo paths, e.g. `apps/api/app/services/`, `apps/api/app/core/`, `apps/api/app/db/`, `apps/api/app/api/`, `apps/api/app/schemas/`;
- add assertions for sentinel files:
  - `components/today/tab-bar.tsx` -> shell/navigation or explicitly justify Today ownership;
  - `apps/api/app/services/today_service.py` -> backend services;
  - `apps/api/app/api/day.py` -> backend API routers;
  - `apps/api/app/db/models.py` -> DB/models;
  - `lib/grace/log.ts` -> logging spine.

### 3. Required per-file fields are incomplete

The worker handoff required per-file inventory to include module id, marker pairing status, adoption priority, logging declaration status, and notes.

Current JSON contains useful basics but misses several required fields:

- no `module_id`
- no true marker-pairing status from existing linters
- no `adoption_priority`
- no `notes`
- no field distinguishing “logging present but not declared in module contract” at per-file level

Required fix:

- add these fields, even if values are `null`, `unknown`, or `not_applicable`, so follow-up tools can rely on a stable schema.

### 4. Report summary and JSON disagree

The markdown report says `SLICE-BACKEND-API-ROUTERS` has 26 files and 92.3% coverage.

The JSON generated in the committed inventory says the same slice has 79 files and 45.6% coverage.

This is a serious review blocker: the human report and machine inventory must agree.

Required fix:

- regenerate report from JSON or generate both from the same data object in one script;
- do not hand-edit coverage tables separately.

### 5. Baseline SHA is confusing

The user requested audit around current Solar Sage state after GRACE docs normalization. The final commit is `66ce0e8`, while the JSON/report baseline says `fa2b7db`.

This may be technically the SHA at generation time, but the report should clearly distinguish:

- audit input SHA
- report commit SHA
- current main SHA after commit

Required fix:

- add `audit_input_sha`, `audit_commit_sha`, and `report_commit_sha` or equivalent.

## Final decision

**NEEDS_REWORK.**

The audit direction is correct and useful, but the current inventory is not reliable enough to drive adoption waves because:

1. JSON determinism claim is false.
2. slice classification has path-order/path-prefix bugs.
3. markdown report and JSON disagree.
4. required schema fields are missing.

## Minimal rework

1. Fix classifier path order and actual repo prefixes.
2. Add sentinel classification checks.
3. Make JSON deterministic.
4. Generate markdown summary from the JSON data.
5. Add missing schema fields with stable keys.
6. Re-run and commit regenerated JSON/report.

After this rework, the audit can become the basis for the first adoption packets.
