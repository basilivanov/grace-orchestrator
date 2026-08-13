WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_08_DEAD_CODE_REPO_HYGIENE
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 933c8e953aa03ff4887a1f3690f3f88f68acc994
WEB_ORCH_CHECKS: PASS

# Packet 08 submission

## Sync and implementation

- Synced base: `933c8e953aa03ff4887a1f3690f3f88f68acc994`.
- Initial status: `## main...origin/main`; the tracked tree was clean.
- Pre-existing unrelated untracked files were preserved, including `.env.bak-mini-endpoint-20260705170600`, `parse_list.py`, and the accepted agent-exchange marker files.
- Implementation result: **verified no-op**. The synced `HEAD` already contains the accepted dead-code cleanup and durable repository-hygiene policy. No source, test, migration, or `.gitignore` path was changed for this packet.
- Implementation SHA: `933c8e953aa03ff4887a1f3690f3f88f68acc994` (synced `HEAD`).

## Current-state audit

| path | decision | delete_confidence_percent | affect_probability_percent | references_found | reason | action |
|---|---|---:|---:|---|---|---|
| `src/hello.py` | KEEP_USED | 10 | 90 | `tests/grace_control/api/test_dev_replay_acceptance.py:63,77`; `tests/grace_control/api/test_dev_rerun_verifier_reviewer.py:64,92,146,188` use it as a changed-file/scope fixture | The file is a supported scope fixture even though it has no active import caller. | keep |
| `src/hello_grace.py` | ALREADY_ABSENT | 100 | 0 | none outside the intentional negative hygiene guard | The proven legacy demo path is absent; the boundary test asserts absence and forbids its import. | none |
| `tests/test_hello_grace.py` | ALREADY_ABSENT | 100 | 0 | none outside the intentional negative hygiene guard | The matching legacy test is absent and has no active caller. | none |
| `src/grace_control/core/hello.py` | ALREADY_ABSENT | 100 | 0 | none outside the intentional negative hygiene guard | The legacy core demo module is absent; active AST checks forbid reintroduction. | none |
| `src/grace_control/mod.py` | ALREADY_ABSENT | 100 | 0 | none outside the intentional negative hygiene guard | The legacy module is absent and has no active import/export reference. | none |
| `tests/grace_control/core/test_mod.py` | ALREADY_ABSENT | 100 | 0 | none | The test for the removed module is absent with no active caller. | none |
| `demo_resources.py` | ALREADY_ABSENT | 100 | 0 | none outside the intentional negative hygiene guard | The unreferenced demo resource module is absent. | none |
| `scripts/test_api_integration.py` | ALREADY_ABSENT | 100 | 0 | none outside the intentional negative hygiene guard | The obsolete integration script is absent and not an active entry point. | none |
| `src/gold-test/` | ALREADY_ABSENT | 100 | 0 | none outside the intentional negative hygiene guard | The generated/runtime path is absent from the working tree and Git index. | none |
| `scripts/migrate_to_grace_package.sh` | MANUAL_REVIEW | 60 | 70 | self-calls `validate_migration.sh`; documented by `scripts/MIGRATION_SCRIPTS.md`; no deployment/CI caller found outside the helper/docs | It targets a migration/bootstrap path, but current evidence does not prove that every supported upgrade path is obsolete. | keep; do not delete |
| `scripts/validate_migration.sh` | MANUAL_REVIEW | 55 | 70 | called by `scripts/migrate_to_grace_package.sh`; documented by `scripts/MIGRATION_SCRIPTS.md`; no deployment/CI caller found | It remains a companion migration validator; deletion requires stronger operator/support evidence. | keep; do not delete |
| `scripts/rollback_migration.sh` | MANUAL_REVIEW | 55 | 75 | documented by `scripts/MIGRATION_SCRIPTS.md`; no deployment/CI caller found | Rollback tooling is potentially part of a supported recovery path and is not proven dead. | keep; do not delete |
| `scripts/MIGRATION_SCRIPTS.md` | KEEP_HISTORICAL_DOC | 80 | 45 | documents the three tracked migration helpers and their workflow | It is the companion migration/runbook evidence and is preserved under the conservative migration rule. | keep |
| `%2Ftmp%2F*` | ALREADY_ABSENT | 100 | 0 | `git ls-files` returned no matching path | The confirmed encoded temporary-runtime family is absent from tracked Git paths and has a narrow ignore rule. | none |
| `.goldw/` | ALREADY_ABSENT | 100 | 0 | `git ls-files` returned no matching path | The generated worktree family is absent from tracked Git paths and is explicitly matched by the hygiene policy. | none |
| `.lw3/` | ALREADY_ABSENT | 100 | 0 | `git ls-files` returned no matching path | The generated worktree family is absent from tracked Git paths and is explicitly matched by the hygiene policy. | none |
| `.grace-live-wt/` | ALREADY_ABSENT | 100 | 0 | `git ls-files` returned no matching path | The generated live-worktree family is absent from tracked Git paths and is explicitly matched by the hygiene policy. | none |
| `tracked *.db` | ALREADY_ABSENT | 100 | 0 | `git ls-files` returned no matching path for `*.db`, `*.db-shm`, or `*.db-wal` | No tracked database/runtime state remains; the hygiene gate evaluates the Git index rather than untracked developer state. | none |

## Runtime/generated inventory

The required tracked-path inventory command returned **zero hits** for `%2Ftmp%2F*`, `.goldw/`, `.lw3/`, `.grace-live-wt/`, `src/gold-test/`, and tracked `*.db`/`*.db-shm`/`*.db-wal`. No `DELETE_NOW` or uncertain tracked runtime artifact was found. No runtime state was recreated or deleted in this packet.

The executable policy in `scripts/ci_repo_hygiene.py` reads `git ls-files -z`, sorts the paths deterministically, applies only the confirmed runtime families, and reports each offending path as `tracked runtime/generated artifact: <exact-path>`. It does not scan untracked developer state or access the network. Existing checks for `agents/`, legacy entry points, and the removed `src/prefect_grace` package surface remain intact.

The relevant `.gitignore` entries are the existing runtime/generated rules for database files, `%2Ftmp%2F*`, `.goldw/`, `.lw3/`, and `.grace-live-wt/`. No broad allowlist or new ignore rule was added. Tracked-path enforcement remains authoritative even when a developer-local generated path is ignored.

## Dead-code and migration result

- Exact deleted/changed paths for this packet: `none` (verified no-op).
- The proven legacy demo/module paths are already absent from the current tree and have no active imports. The remaining references are only explicit negative assertions in `tests/grace_control/architecture/test_repo_hygiene_boundary.py`.
- The migration helpers and their companion document are preserved as `MANUAL_REVIEW`/`KEEP_HISTORICAL_DOC`; the packet's required evidence for safe deletion is not complete, so none was removed.
- No HTTP/OpenAPI, DB/Alembic, lifecycle, packet, executor, supervisor, CLI-boundary, or CI-consolidation behavior was changed.

## Verification

- `python3 scripts/ci_repo_hygiene.py` — PASS (`OK: repo-hygiene passed`).
- `PYTHONPATH=src .venv/bin/pytest -q tests/scripts/test_ci_repo_hygiene.py` — PASS, 4 passed.
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_repo_hygiene_boundary.py` — PASS, 2 passed.
- Required tracked runtime/generated scan — PASS, zero hits.
- Required legacy-reference scan — PASS: only the intentional negative guard references listed above remained.
- `make lint` — PASS; baseline-aware gate matched reviewed baseline (`ruff=1020`, `gracelint=3249`).
- `make docs-check` — PASS (`docs freshness OK — 3 files in sync`).
- `make hygiene` — PASS (`OK: repo-hygiene passed`).
- `python3 -m py_compile scripts/ci_repo_hygiene.py tests/scripts/test_ci_repo_hygiene.py tests/grace_control/architecture/test_repo_hygiene_boundary.py` — PASS.
- `git diff --check` — PASS.

No next packet was started.
