WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_DEAD_CODE_REPO_HYGIENE
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 847fe6cc55915cd3c0d2df549b85cc64fb127f4c
WEB_ORCH_CHECKS: PASS

## Sync and preservation

- Mandatory sync completed with git status --short --branch, git fetch origin --prune, and git pull --ff-only origin main.
- Packet-level switch/fetch/fast-forward sync was also clean.
- Synced base SHA: db0db63f88289da3735625b309d7dbae50b2f43a.
- Initial status contained only the pre-existing untracked files .env.bak-mini-endpoint-20260705170600 and parse_list.py. Both remain untracked and preserved. No reset, clean, or destructive workspace operation was used.
- Implementation commit 847fe6cc55915cd3c0d2df549b85cc64fb127f4c was pushed to origin/main.

## Changed and deleted paths

Changed:
- .gitignore: added only .goldw/, .lw3/, and .grace-live-wt/.
- scripts/ci_repo_hygiene.py: added deterministic tracked runtime-artifact policy while preserving agents, legacy-entrypoint, and prefect_grace package checks.
- scripts/verify_all.sh: removed the obsolete self-test exclusion for deleted tests/test_hello_grace.py.
- tests/scripts/test_ci_repo_hygiene.py: matcher and CLI characterization.
- tests/grace_control/architecture/test_repo_hygiene_boundary.py: policy and deleted-import architecture guard.

Deleted after audit evidence:
- %2Ftmp%2Fgrace-full.db: tracked SQLite runtime database, 135168 bytes.
- .goldw/packets/pkt_I01fWWII7I/EXECUTION_PACKET.md: generated execution packet under tracked runtime state.
- .lw3/packets/pkt_QoRgSWpq7s/EXECUTION_PACKET.md: generated execution packet under tracked runtime state.
- .grace-live-wt/packets/pkt_HoJQddC0Q4/EXECUTION_PACKET.md: generated live-worktree packet state.
- src/gold-test/result.txt: generated one-line result from an old packet, not an intentional fixture consumed by current tests.
- src/hello_grace.py and tests/test_hello_grace.py: obsolete hello demo and its only self-test; no supported runtime/import caller.
- src/grace_control/core/hello.py: self-evolution hello demo with no active importer or runtime entrypoint.
- src/grace_control/mod.py and tests/grace_control/core/test_mod.py: isolated feature-handler demo and its only tests; no active source/API/package caller.
- demo_resources.py: Prefect-era resource demo importing removed prefect_grace.resources; no active caller.
- scripts/test_api_integration.py: Prefect-era API demo importing removed prefect_grace.platform paths; no active caller.

## Dead-code and artifact audit

The Phase A inventory used:
  git ls-files | sort > /tmp/grace-tracked-files.txt
  git ls-files | rg '(^|/)(%2Ftmp%2F|\.goldw/|\.lw3/|\.grace-live-wt/|src/gold-test/)|\.db($|[-.])' || true

Before deletion it reported exactly the tracked DB, one packet file under each hidden runtime directory, and src/gold-test/result.txt. Active source/tests/scripts/docs/Makefile/workflow reference scans found no consumers of those runtime paths. grace/packets/ was preserved as the intentional repository packet/spec surface.

| path | decision | delete_confidence_percent | affect_probability_percent | references_found | reason | action |
|---|---|---:|---:|---|---|---|
| src/hello.py | KEEP_USED | 0 | 100 | tests/test_hello.py; dev replay tests use it as changed-file data | Active supported test/import surface. | Kept. |
| src/hello_grace.py | DELETE_NOW | 99 | 1 | Only tests/test_hello_grace.py and historical grace/packets brief | Standalone demo with only self-test. | Deleted with self-test. |
| tests/test_hello_grace.py | DELETE_NOW | 99 | 1 | scripts/verify_all.sh exclusion and own import only | Self-test for deleted demo. | Deleted; exclusion removed. |
| src/grace_control/core/hello.py | DELETE_NOW | 98 | 1 | No active import/reference | Isolated hello demo. | Deleted. |
| src/grace_control/mod.py | DELETE_NOW | 98 | 1 | Only tests/grace_control/core/test_mod.py | Isolated handler demo. | Deleted with self-test. |
| tests/grace_control/core/test_mod.py | DELETE_NOW | 99 | 1 | Imports only deleted grace_control.mod | Obsolete module's only test owner. | Deleted. |
| demo_resources.py | DELETE_NOW | 99 | 1 | No active caller; imports prefect_grace.resources | Old Prefect-era demo cannot run against supported package. | Deleted. |
| scripts/test_api_integration.py | DELETE_NOW | 99 | 1 | No active caller; imports prefect_grace.platform.* | Old API demo targets removed package surface. | Deleted. |
| src/gold-test/ | DELETE_NOW | 98 | 1 | Only old packet scope/result references | Generated packet output, not a current fixture directory. | Deleted result.txt; gate rejects recurrence. |
| scripts/migrate_to_grace_package.sh | MANUAL_REVIEW | 40 | 25 | Referenced by MIGRATION_SCRIPTS.md and self-references validation/rollback | Possible external upgrade/rollback use; unclear use must remain. | Kept unchanged. |
| scripts/validate_migration.sh | MANUAL_REVIEW | 40 | 25 | Referenced by migration script and MIGRATION_SCRIPTS.md | Migration safety concern. | Kept unchanged. |
| scripts/rollback_migration.sh | MANUAL_REVIEW | 40 | 25 | Referenced by migration script and MIGRATION_SCRIPTS.md | Rollback safety concern. | Kept unchanged. |
| scripts/MIGRATION_SCRIPTS.md | KEEP_HISTORICAL_DOC | 95 | 2 | Documents the three migration scripts | Historical operational evidence. | Kept unchanged. |
| %2Ftmp%2F* | DELETE_NOW | 99 | 1 | Only tracked DB instance; family already ignored | Confirmed generated runtime state. | Removed instance; no duplicate rule. |
| .goldw/ | DELETE_NOW | 99 | 1 | One generated packet; no active consumer | Confirmed generated runtime state. | Removed and ignored. |
| .lw3/ | DELETE_NOW | 99 | 1 | One generated packet; no active consumer | Confirmed generated runtime state. | Removed and ignored. |
| .grace-live-wt/ | DELETE_NOW | 99 | 1 | One generated packet; runtime uses external temp target | Confirmed generated live-worktree state. | Removed and ignored. |
| tracked *.db | DELETE_NOW | 99 | 1 | Only %2Ftmp%2Fgrace-full.db matched | Generated SQLite state; DB families already ignored. | Removed instance. |

src/grace_control/core/golden_fixtures.py, fixtures/golden consumers, and grace/packets were intentionally kept as supported fixture/spec surfaces. They are distinct from deleted runtime output.

## Hygiene policy and scans

scripts/ci_repo_hygiene.py now exposes tracked_files() and tracked_runtime_artifacts(paths), reports every exact offending path, checks only git ls-files, performs no network access, and preserves the existing agents, legacy-entrypoint, and src/prefect_grace checks.

The post-delete structural scan:
  git ls-files | rg '(^|/)(%2Ftmp%2F|\.goldw/|\.lw3/|\.grace-live-wt/)|\.db($|[-.])' || true
returned no tracked paths.

The active-reference scan:
  rg -n 'hello_grace|grace_control\.mod|demo_resources|test_api_integration|gold-test|src/gold-test|%2Ftmp%2Fgrace-full\.db|\.goldw/|\.lw3/|\.grace-live-wt/' src tests scripts README.md AGENTS.md docs/grace docs/SUPERVISOR.md pyproject.toml Makefile .github || true
has only executable policy/negative-guard samples and runtime documentation showing /tmp/grace-live-wt as an external target. No active import or tracked runtime artifact remains. Migration references to prefect_grace, gracectl, and old scripts remain intentionally classified as manual-review/historical evidence.

## Checks

- python3 scripts/ci_repo_hygiene.py: PASS, OK: repo-hygiene passed.
- Focused hygiene/cleanup regression including tests/scripts/test_ci_repo_hygiene.py, tests/grace_control/architecture/test_repo_hygiene_boundary.py, tests/test_hello.py, dev replay/rerun tests, and no-control-CLI tests: 15 passed.
- Direct hygiene/architecture tests: 6 passed.
- python3 scripts/grace_lint.py on all changed Python files/tests: PASS.
- ruff check on all changed Python files/tests: PASS.
- python3 -m py_compile on all changed Python files: PASS.
- git diff --check: PASS.
- Full PYTHONPATH=src .venv/bin/pytest -q tests: 1970 passed, 30 skipped, 42 failed, 19 errors. These are pre-existing/environmental and unrelated: /tmp/grace_planning_logs permission and missing runtime setup, existing missing scripts/grace_changed_files_lint.py while its tests remain, missing Playwright page fixture, and other baseline integration/fixture failures. The base already had tests/scripts/test_grace_changed_files_lint.py but no scripts/grace_changed_files_lint.py, verified with git cat-file at the synced base.
- Required PYTHONPATH=src .venv/bin/pytest -q tests/scripts: 4 new hygiene tests passed; the pre-existing test_grace_changed_files_lint.py contributed 17 errors and 5 failures for the missing script/import above.

No HTTP route, OpenAPI, schema, migration, lifecycle, state-machine, executor, supervisor, Makefile, or GitHub Actions behavior was changed. No Alembic/data migration was deleted. No new lint/size allowlist entry was added. No Wave 7 work was started.
