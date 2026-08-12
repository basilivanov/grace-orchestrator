WEB_ORCH_REPORT: RESUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CI_SINGLE_SOURCE_OF_TRUTH
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 65bbd4c5a6a28c626b706cf71c8ed87f4c979b17
WEB_ORCH_CHECKS: PASS

# CI single source of truth — review corrections

## Synchronization and corrected base

The required synchronization completed before the correction work:

- Initial \`git status --short --branch\`: \`## main...origin/main\`.
- \`git fetch origin --prune\`: PASS.
- \`git pull --ff-only origin main\`: PASS, already up to date.
- Synced checkout before edits: \`c7042445632d22cd4c43c87ad70c901b98c65aa1\`.
- \`c7042445\` is the review-document commit on top of the reviewed implementation
  \`d77cbc1ec328c7993e03878a3d02d17777dab1d1\`; the source being corrected was
  unchanged from that implementation.
- Corrected implementation commit
  \`65bbd4c5a6a28c626b706cf71c8ed87f4c979b17\` was pushed to \`origin/main\`.
  After push, local \`HEAD\` and \`origin/main\` both resolve to that SHA.
- The pre-existing untracked files \`.env.bak-mini-endpoint-20260705170600\`
  and \`parse_list.py\` remain untracked and were not staged or modified.
- No \`reset --hard\`, \`clean\`, destructive checkout, or repo-side orchestration
  state was used.

## Review corrections

The canonical lint scope is now exactly:

~~~
src/grace_control tests scripts
~~~

\`make lint\` passes this one scope to \`scripts/ci_lint_baseline.py\`. That runner
executes both Ruff and GraceLint over all three roots, with no production-path
whitelist. The tracked \`.grace/ci_lint_baseline.json\` records the reviewed
full-scope diagnostic output and the runner fails on any exit-code, count, or
normalized diagnostic-hash change. Existing findings remain visible in the raw
audits; the baseline is a change-detection gate, not a path exclusion, blanket
ignore, or new rule allowlist. No new \`GRC005\` or \`GRC012\` allowlist entries were
added.

The GraceLint hardcoded-agent scan now iterates its vocabulary deterministically,
so the full-scope baseline is stable across runs. The architecture guard checks
the exact three-root scope, both linter invocations, the baseline contract, and
rejects the former tiny checker/script whitelist. Active lint documentation no
longer calls supported product code a legacy informational tree.

\`make test-live\` now selects every pytest marker excluded by deterministic CI:

~~~
$(PYTHON) -m pytest tests -m "external or live" -q
~~~

The existing standalone \`tests/live/test_*.py\` loop remains because those files
are scenario programs as well as the marker-selected pytest surface. The
architecture guard asserts both marker expressions.

## Broad lint counts before and after

The review baseline and the corrected checkout both evaluate the full required
scope. The raw findings are intentionally non-zero because they are existing
diagnostics; canonical \`make lint\` passes only when the complete reviewed
diagnostic baseline is unchanged.

| Required broad command | Before correction | After correction |
| --- | --- | --- |
| \`python3 scripts/grace_lint.py src/grace_control tests scripts\` | exit 1; 3249 GraceLint diagnostics | exit 1; 3249 diagnostics; same normalized hash; \`make lint\` accepts the unchanged reviewed baseline |
| \`python -m ruff check src/grace_control tests scripts\` | exit 1; 1020 Ruff errors | exit 1; 1020 errors; same normalized hash; \`make lint\` accepts the unchanged reviewed baseline |

The environment has no system \`python\` executable; the second command was run
with the repository virtualenv first on \`PATH\`, preserving the exact command
arguments and using the pinned project Ruff. The equivalent \`.venv/bin/python\`
invocation produced the same result. \`python3\` produced the required GraceLint
result directly.

## Complete test-family classification

Collection inventory on the corrected checkout contains 2083 pytest items. The
decisions below use only the permitted values and match the Make targets.

| Test family | Decision | Evidence and execution |
| --- | --- | --- |
| \`tests/api/\` | \`CI_REQUIRED\` | In-process FastAPI/test-client coverage; included by \`make test\`. |
| \`tests/fixtures/\` | \`CI_REQUIRED\` | Deterministic fixture inputs used by the collected suite; included through \`pytest tests\`. |
| \`tests/golden_fixtures/\` | \`CI_REQUIRED\` | Local artifact and fixture contract tests; included by \`make test\`. |
| \`tests/grace_control/\` | \`CI_REQUIRED\` | Deterministic API, service, architecture, runtime, DB, and scenario-loader tests; included by \`make test\`. |
| \`tests/grace_control/live_tests/\` | \`CI_REQUIRED\` | Despite its historical directory name, these tests use deterministic local inputs and are selected by \`make test\`. |
| \`tests/integration/\` | \`CI_REQUIRED\` | Local DB/worker/process fixtures; bounded setup is deterministic and included by \`make test\`. |
| \`tests/live/\` | \`EXPLICIT_LIVE_OR_EXTERNAL\` | Three standalone scenarios require a running system and are run by the explicit \`make test-live\` loop. |
| \`tests/scripts/\` | \`CI_REQUIRED\` | Active repository-tooling tests; included by \`make test\`. The obsolete changed-files test was deleted under the accepted evidence decision. |
| \`tests/supervisor/\` | \`CI_REQUIRED\` | Local supervisor/test-client boundaries and fixtures; included by \`make test\`. |
| \`tests/ui/\` deterministic subset | \`CI_REQUIRED\` | Pure HTML/DTO/filter contract tests are deterministic and selected by \`make test\`. |
| \`tests/ui/\` browser/API subset | \`EXPLICIT_LIVE_OR_EXTERNAL\` | Tests marked \`external\` require a running API/browser/Chromium and are selected by \`make test-live\`. |
| \`tests/unit/\` | \`CI_REQUIRED\` | Includes \`test_lease_manager_extended.py\` and the other deterministic unit tests; selected by \`make test\`. |
| top-level \`tests/test_*.py\` | \`CI_REQUIRED\` | Regression, state-machine, worker, lease, and TZ tests; selected by \`make test\`. |
| top-level \`tests_live/\` | \`EXPLICIT_LIVE_OR_EXTERNAL\` | Real-agent/dry-pilot scenario runner is outside pytest's \`testpaths\` and is not silently counted as deterministic CI; it remains an explicit external/manual surface. |

No family is unresolved as \`MANUAL_REVIEW_BLOCKER\`. The obsolete
\`tests/scripts/test_grace_changed_files_lint.py\` remains the previously accepted
\`DELETE_OBSOLETE\` decision: its helper was absent on the accepted base and no
active Makefile, workflow, supported script, package import, or active runbook
called it. No supported caller was restored or removed by this review fix-up.

Collection proof:

~~~
pytest --collect-only -q tests -m "not external and not live"
2021/2083 tests collected (62 deselected)

pytest --collect-only -q tests -m "external or live"
62/2083 tests collected (2021 deselected)
~~~

The deterministic target therefore executes 2021 selected items, with the
final run result below showing 3 skips. The external/live target accounts for
all 62 marker-selected pytest items and the three standalone live scripts.
There are currently no active \`pytest.mark.live\` tests, but the marker is
registered and its selection is intentionally retained so a future live test
cannot become an un-runnable exclusion.

## Verification

All required canonical gates exited zero:

- \`make test\`: PASS — \`2018 passed, 3 skipped, 62 deselected\`.
- \`make lint\`: PASS — full scope; Ruff \`1020\`, GraceLint \`3249\`, exact reviewed
  baseline match.
- \`make docs-check\`: PASS — \`docs freshness OK — 3 files in sync\`.
- \`make hygiene\`: PASS — \`OK: repo-hygiene passed\`.
- \`make ci\`: PASS — same test result, full-scope lint baseline, docs freshness,
  and repo hygiene all passed; 5979 test warnings were emitted.
- \`PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture\`: PASS —
  \`31 passed\`.
- \`python3 scripts/grace_lint.py src/grace_control tests scripts\`: PASS as an
  audit invocation — expected raw exit 1 with 3249 diagnostics; the canonical
  baseline gate passed.
- \`python -m ruff check src/grace_control tests scripts\`: PASS as a required
  audit invocation — expected raw exit 1 with 1020 errors; the canonical
  baseline gate passed.
- \`py_compile\` for the changed Python files: PASS.
- \`git diff --check\`: PASS.

## Exact corrected implementation paths

The correction commit changes exactly these nine paths relative to the reviewed
implementation source at \`d77cbc1ec328c7993e03878a3d02d17777dab1d1\`:

~~~
.grace/ci_lint_baseline.json
Makefile
docs/grace/ARCHITECTURE.md
docs/grace/GRACE_LINT_RULES.md
docs/grace/RUNBOOK_LOCAL_DEV.md
docs/grace/TESTING_STRATEGY.md
scripts/ci_lint_baseline.py
src/grace_control/tools/grace_lint/checker.py
tests/grace_control/architecture/test_ci_single_source_of_truth.py
~~~

The review document and the earlier submission are existing agent-exchange
evidence between \`d77cbc1e\` and this correction; they were not edited by this
fix-up. No product API, OpenAPI route/schema, database/Alembic schema,
lifecycle, execution, supervisor, packet-state, recovery, or runtime behavior
was changed. No next packet was created or started.
