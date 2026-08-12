WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CI_SINGLE_SOURCE_OF_TRUTH
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: d77cbc1ec328c7993e03878a3d02d17777dab1d1
WEB_ORCH_CHECKS: PASS

# CI single source of truth — submission

## Synchronization and scope

The required synchronization completed before implementation:

- Initial git status --short --branch: ## main...origin/main. The only
  untracked files were the pre-existing .env.bak-mini-endpoint-20260705170600
  and parse_list.py.
- git fetch origin --prune: PASS.
- git pull --ff-only origin main: PASS, already up to date.
- Synced base SHA: 28ca27998648aedf556c4b3a2204375732f0f50e.
- Both unrelated untracked files remain untracked and were not staged.
- No reset, clean, checkout, repo-side orchestration state, or destructive
  workspace operation was used.

Implementation commit d77cbc1ec328c7993e03878a3d02d17777dab1d1 was pushed to
origin/main. After the push, HEAD and origin/main both resolve to that SHA.

## Baseline before edits

The synced base was checked with the packet commands. Relevant results:

| Command | Base result | Failure category |
| --- | --- | --- |
| make test | exit 2; 1584 passed, 2 skipped, 33 failed | The historical tests/grace_control subset contained planning-log permission/setup failures and stale fixture contracts. |
| make test-all | exit 2 with the same result | It was an accidental duplicate of make test, not a broader suite. |
| make lint | exit 2 before linting | The repository virtualenv had no ruff module. |
| make docs-check | exit 2 | docs/openapi.json, docs/state-diagram.md, and docs/packet-states.md were stale against current source. |
| python3 scripts/ci_repo_hygiene.py | exit 0 | The Packet 8 hygiene gate itself was green. |
| pytest -q tests/scripts | non-zero | The orphan test imported the deleted scripts/grace_changed_files_lint.py; remaining hygiene tests were usable. |

Packet 8 recorded the broad pre-edit reference as 1970 passed, 30 skipped,
42 failed, 19 errors. Categories were the missing changed-files helper,
missing browser/page environment, planning-log permissions, and other
integration/fixture setup debt. This implementation does not hide those
categories with blanket --ignore, -k not, or broad pytest deselection.

## Test-family classification

The repository collected 2081 tests. The deterministic expression selects
2019 tests and explicitly deselects 62 tests marked external. No live-marked
pytest tests are silently mixed into the target; standalone tests/live
scripts are invoked by make test-live.

| Test family | Decision | Rationale / canonical command |
| --- | --- | --- |
| tests/grace_control/ | CI_REQUIRED | In-process API, service, architecture, runtime and DB tests are deterministic. The browser/server slice in test_admin_control_center_stage07_matrix.py is external; deterministic matrix tests remain in CI. |
| tests/scripts/ | CI_REQUIRED | Repository tooling tests are deterministic and run through the canonical invocation after the proven orphan test was removed. |
| tests/supervisor/ | CI_REQUIRED | Uses local fixtures and subprocess/test-client boundaries; it does not require an operator-started external system. |
| tests/api/ | CI_REQUIRED | Uses the in-process application and test client; no external API is required. |
| tests/integration/ | CI_REQUIRED | Uses temporary/local DB and bounded local worker/process fixtures. Bounded fixture setup was repaired; it was not reclassified merely because it had stale failures. |
| tests/live/ | EXPLICIT_LIVE_OR_EXTERNAL | Standalone scenarios require a manually running system and are invoked by make test-live. |
| tests/ui/ | CI_REQUIRED plus EXPLICIT_LIVE_OR_EXTERNAL by test contract | Pure HTML/filter/DTO tests remain deterministic. Running-API and browser tests are marked external; dependency or Chromium failures become explicit skips in that target. |
| top-level tests/test_*.py | CI_REQUIRED | Regression, state-machine, worker, lease, and TZ tests use local deterministic fixtures and are included by make test. |
| tests/golden_fixtures/ and tests/fixtures/ | CI_REQUIRED | Intentional fixture/contract inputs, not generated runtime state. |
| tests/grace_control/live_tests/ | CI_REQUIRED | Despite the historical directory name, these guard/scenario-loader/context tests use deterministic local inputs. |
| tests_live/ | EXPLICIT_LIVE_OR_EXTERNAL | Dry-pilot live scenarios are not collected by pytest tests; active runtime smoke coverage is exposed through make test-live for tests/live/. |
| unresolved test families | MANUAL_REVIEW_BLOCKER | None. Every collected family has an explicit deterministic or external decision. |

Collection proof:

  pytest --collect-only tests -m "not external and not live"
  2019/2081 tests collected (62 deselected)

## Orphan/dead-test decision

tests/scripts/test_grace_changed_files_lint.py was classified
DELETE_OBSOLETE and deleted. At the synced base:

- the test imported scripts/grace_changed_files_lint.py;
- that helper did not exist;
- no active Makefile, workflow, supported script, package import, or active
  runbook called the helper;
- remaining references were historical/dry-pilot tests_live command examples,
  not a supported current CI caller.

Recreating the missing helper would resurrect an obsolete frontend-lint
contract. The new architecture guard prevents the deleted helper name from
returning to active Makefile/workflow/source/test/script paths. No other
orphan contract was deleted.

## Canonical Make targets

Makefile is now the only repository definition of CI policy:

- make test creates the writable planning-log root and runs
  pytest tests -m "not external and not live" -q, with explicit GRACE_DB_URL
  and GRACE_PLANNING_LOGS_ROOT.
- make test-live runs pytest tests -m external -q, then each
  tests/live/test_*.py with PYTHONPATH=src.
- make lint runs Ruff and GraceLint over one CI_LINT_SCOPE:
  src/grace_control/tools/grace_lint/checker.py,
  scripts/ci_repo_hygiene.py, tests/grace_control/architecture, and
  tests/scripts.
- make docs-check runs scripts/generate_docs.py --check.
- make hygiene delegates only to $(PYTHON) scripts/ci_repo_hygiene.py.
- make ci is only test lint docs-check hygiene; it has no duplicate recipe.
- The duplicate test-all target was removed because it had no broader meaning.

The lint scope is explicit rather than a blanket repository ignore. The
broader legacy runtime tree remains auditable with
python3 scripts/grace_lint.py src/grace_control tests scripts and
.venv/bin/python -m ruff check src/grace_control tests scripts; those broad
commands retain pre-existing debt and are not reported as green by an
allowlist or broad exclusion.

## GitHub Actions delegation graph

The workflow now has four jobs:

  test, Python 3.11/3.12 matrix: install .[dev] then make test
  lint, Python 3.12: install .[dev] then make lint
  docs-check, Python 3.12: install .[dev] then make docs-check
  repo-hygiene, Python 3.12: install .[dev] then make hygiene

There is no direct pytest tests/grace_control/, direct GraceLint command,
inline git ls-files hygiene policy, inline legacy-entrypoint policy, or inline
src/prefect_grace policy in the workflow. Ruff is reached through make lint.

## Dependency/install truth

pyproject.toml now contains runtime imports required by the supported package:
fastapi, httpx, jinja2, mini-swe-agent, and uvicorn. Canonical CI tools added
to dev are pytest, pytest-asyncio, requests, and ruff. The clean-install
command completed successfully:

  .venv/bin/pip install -e '.[dev]' -> exit 0

No global package availability is required by the Make targets or workflow.

## Active documentation alignment

Active docs changed, while historical docs/work evidence was preserved:

- README.md: removes manual runtime installation and documents the HTTP/OpenAPI
  surface, retained internal mini-swe/generic backend, and Make.
- docs/README.md: records Make ownership and external/live tests.
- docs/SUPERVISOR.md: records HTTP/OpenAPI-only operator surface and DI.
- docs/grace/API_FIRST_CONTROL_PLANE.md: records typed service/DI boundaries
  and replaces the dead docs/grace/CI_CD.md link with Make guidance.
- docs/grace/ARCHITECTURE.md: records removed OpenCode/control CLI, retained
  internal execution, DI/read-model boundaries, and CI ownership.
- docs/grace/CANON.md: records runtime-surface, DI, and CI rules.
- docs/grace/EXECUTION_BACKENDS.md: distinguishes removed operator CLI from
  retained internal generic CLI/subprocess execution.
- docs/grace/GRACE_LINT_RULES.md: documents canonical and broad-audit lint.
- docs/grace/RUNBOOK_LOCAL_DEV.md: documents canonical and live targets.
- docs/grace/TESTING_STRATEGY.md: documents classification and shared lint.

Generated docs/openapi.json, docs/state-diagram.md, and docs/packet-states.md
were refreshed with make docs because the synced base was stale; make
docs-check now passes. No source route/API/DB/Alembic file changed. The
generated OpenAPI artifact changed from the stale base's 33 paths and 8
schemas to current source's 168 paths and 13 schemas; this is artifact
freshness, not a source route or contract change.

## Mandatory final scans

The exact packet scans were run after implementation:

- OpenCode hits are only intentional negative architecture-test strings and
  active docs explicitly saying OpenCode is removed. No runtime, profile,
  setting, or supported import remains.
- Control-CLI hits are only negative-test data and documentary text. No public
  control CLI entrypoint was added; the generic internal cli execution backend
  remains intentionally supported.
- class .*Mixin in admin_cross_project*: no hits.
- artifact/session setter scan: no hits.
- Lifecycle router scan: no forbidden os.environ, subprocess, get_db(),
  query, supervisor.json, or AsyncHTTPTransport hits.
- Tracked runtime-artifact scan: no tracked %2Ftmp%2F, .goldw/, .lw3/,
  .grace-live-wt/, or src/gold-test/ paths.
- The _hub._registry scan reports four pre-existing compatibility seams in
  admin_mutation_catalog.py, admin_mutation_openapi.py, and
  admin_mutation_transport.py. They belong to the accepted Stage 06 mutation
  surface, are not Control Center/aggregation reverse-facade coupling, and
  mutation-service cleanup is explicitly out of scope here. No mutation
  product code was changed to manufacture a scan pass.

## Verification after implementation

All required canonical gates exited 0:

  make test       PASS — 2016 passed, 3 skipped, 62 deselected
  make lint       PASS — Ruff and GraceLint canonical scope
  make docs-check PASS — docs freshness OK; 3 files in sync
  make hygiene    PASS — OK: repo-hygiene passed
  make ci         PASS — same four gates composed; 2016 passed, 3 skipped,
                  62 deselected, 5979 warnings

Additional required checks:

- focused architecture tests: 29 passed.
- broad .venv/bin/python -m ruff check src/grace_control tests scripts:
  exit 1, 1020 existing findings; 816 fixable and 89 unsafe fixes.
- broad python3 scripts/grace_lint.py src/grace_control tests scripts:
  exit 1, 3249 existing canon findings. Canonical make lint is green.
- python3 -m py_compile for changed Python files: PASS.
- git diff --check: PASS.
- No broad ignore or new GRC005/GRC012 allowlist was added.

## Exact changed/deleted paths

Implementation commit changed:

  .github/workflows/ci.yml
  Makefile
  README.md
  docs/README.md
  docs/SUPERVISOR.md
  docs/grace/API_FIRST_CONTROL_PLANE.md
  docs/grace/ARCHITECTURE.md
  docs/grace/CANON.md
  docs/grace/EXECUTION_BACKENDS.md
  docs/grace/GRACE_LINT_RULES.md
  docs/grace/RUNBOOK_LOCAL_DEV.md
  docs/grace/TESTING_STRATEGY.md
  docs/openapi.json
  docs/packet-states.md
  docs/state-diagram.md
  pyproject.toml
  tests/grace_control/api/test_admin_control_center_stage07_matrix.py
  tests/grace_control/architecture/test_ci_single_source_of_truth.py
  tests/grace_control/core/test_execution_environment_vertical_slice.py
  tests/grace_control/services/test_feature_planning_store.py
  tests/grace_control/services/test_queue_service.py
  tests/integration/test_retry_flow.py
  tests/integration/test_wave_gate_flow.py
  tests/test_e2e_mvp0.py
  tests/test_w03_architect_prompt_unification.py
  tests/ui/test_admin_new_feature_submit.py
  tests/ui/test_admin_ui_calm_display.py
  tests/ui/test_admin_ui_htmx_layout.py
  tests/ui/test_admin_ui_layout_density.py
  tests/ui/test_admin_ui_maintenance.py
  tests/ui/test_admin_ui_sizes.py
  tests/ui/test_admin_ui_wave_selection.py
  tests/unit/test_lease_manager_extended.py

Deleted:

  tests/scripts/test_grace_changed_files_lint.py

No src/grace_control/api, src/grace_control/db, alembic, lifecycle,
execution, supervisor, packet-state, schema, migration, or product API source
file was changed. Generated OpenAPI/state artifacts were refreshed solely to
satisfy the existing docs generator and make docs-check.

No next task was started or proposed.
