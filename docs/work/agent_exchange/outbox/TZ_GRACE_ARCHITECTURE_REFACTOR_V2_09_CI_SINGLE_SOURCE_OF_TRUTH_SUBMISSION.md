WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_09_CI_SINGLE_SOURCE_OF_TRUTH
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 8b6787f1d13aa6da44734b6de084e42ffce2c995
WEB_ORCH_CHECKS: PASS

# Packet 09 submission

## Sync and implementation

- Synced base SHA: `8b6787f1d13aa6da44734b6de084e42ffce2c995`.
- Initial status: `## main...origin/main`; the tracked tree was clean.
- Pre-existing unrelated untracked files were preserved, including `.env.bak-mini-endpoint-20260705170600`, `parse_list.py`, and accepted agent-exchange marker files.
- Implementation result: **verified no-op**. The synced `HEAD` already satisfies the Packet 09 CI single-source-of-truth and final programme verification requirements.
- Implementation SHA: `8b6787f1d13aa6da44734b6de084e42ffce2c995` (synced `HEAD`).
- Changed paths for this packet: `none`.

## Canonical CI semantics

The root `Makefile` is the single repository implementation of CI policy:

- `make test` creates the planning-log directory and runs the full `tests` tree with `-m "not external and not live"`; no `tests/grace_control/` subset is used.
- `make test-live` runs `-m "external or live"` and the standalone `tests/live/test_*.py` scenarios.
- `make lint` invokes `scripts/ci_lint_baseline.py` with `CI_LINT_SCOPE := src/grace_control tests scripts` and `.grace/ci_lint_baseline.json`.
- `make docs-check` invokes `scripts/generate_docs.py --check`.
- `make hygiene` invokes only `scripts/ci_repo_hygiene.py`.
- `make ci` composes `test lint docs-check hygiene` and contains no duplicate gate recipe.

The registered excluded pytest markers are exactly `external` and `live`. Deterministic CI excludes only those markers, while the explicit live target selects their union. The live marker surface collected 62 tests; full live execution remains dependent on an externally started API/worker/browser environment and was not required for this local verification.

## Lint and hygiene ownership

- The accepted lint scope is the complete `src/grace_control`, `tests`, and `scripts` scope.
- The baseline-aware runner executes both Ruff and GraceLint and accounts for the reviewed current debt rather than acting as a file allowlist.
- Packet 08 hygiene remains owned by `scripts/ci_repo_hygiene.py`; `.github/workflows/ci.yml` and `Makefile` do not duplicate its implementation.
- The corrected tracked runtime policy still rejects `%2Ftmp%2F*`, `.goldw/`, `.lw3/`, `.grace-live-wt/`, `src/gold-test/`, and repository-relative `*.db`, `*.db-shm`, and `*.db-wal` paths.

## Workflow delegation

`.github/workflows/ci.yml` installs `.[dev]` on the supported Python matrix/single quality-gate version and delegates directly to:

- test job: `make test`;
- lint job: `make lint`;
- docs freshness job: `make docs-check`;
- repository hygiene job: `make hygiene`.

The workflow contains no direct `pytest tests/grace_control/` policy, no separate Ruff/GraceLint scope, no inline hygiene implementation, and no direct `scripts/grace_lint.py` invocation.

## Architecture Refactor V2 guard matrix

All current architecture guards for completed waves passed in one focused run: **36 passed**.

| wave / boundary | guard | result |
|---|---|---|
| Wave 1 | `tests/grace_control/architecture/test_no_opencode_legacy.py` | PASS |
| Wave 2 | `tests/grace_control/api/test_no_control_cli_surface.py` | PASS |
| Wave 3 | `tests/grace_control/architecture/test_admin_cross_project_composition.py` | PASS |
| Wave 4 | `tests/grace_control/architecture/test_admin_control_center_dependency_inversion.py` | PASS |
| Wave 5 | `tests/grace_control/architecture/test_admin_aggregation_dependency_graph.py` | PASS |
| Wave 6 | `tests/grace_control/architecture/test_lifecycle_router_boundary.py` | PASS |
| Wave 7 | `tests/grace_control/architecture/test_admin_read_models_boundary.py` | PASS |
| Packet 08 | `tests/grace_control/architecture/test_repo_hygiene_boundary.py` | PASS |
| Packet 09 | `tests/grace_control/architecture/test_ci_single_source_of_truth.py` | PASS, 7 passed |

The full deterministic `make test` run also exercised these guards and the accepted product/runtime suite.

## Required verification

- `make test` — PASS: `2018 passed, 3 skipped, 62 deselected`.
- `make lint` — PASS: baseline-aware full scope, `ruff=1020`, `gracelint=3249`.
- `make docs-check` — PASS: `docs freshness OK — 3 files in sync`.
- `make hygiene` — PASS: `OK: repo-hygiene passed`.
- `make ci` — PASS: `2018 passed, 3 skipped, 62 deselected`, followed by lint, docs-check, and hygiene PASS.
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_ci_single_source_of_truth.py` — PASS, 7 passed.
- Live/external collection: `PYTHONPATH=src .venv/bin/pytest --collect-only -q tests -m "external or live"` — PASS, 62 tests selected.
- Combined Architecture Refactor V2 guard run — PASS, 36 passed.
- Workflow duplicate-policy scan — PASS: no `pytest tests/grace_control/`, direct `scripts/ci_repo_hygiene.py`, or direct `python scripts/grace_lint.py` hit in `.github/workflows/ci.yml`.
- Obsolete changed-files helper scan — PASS: no active helper reference; the only remaining textual occurrence is the intentional dynamically assembled negative guard in `test_ci_single_source_of_truth.py`.
- Tracked runtime/generated scan — PASS: no tracked `%2Ftmp%2F`, `.goldw/`, `.lw3/`, `.grace-live-wt/`, `src/gold-test/`, `.db`, `.db-shm`, or `.db-wal` paths.
- `git diff --check` — PASS.
- Python compilation of changed Python files — not applicable; no Python files changed for this verified no-op.

## Active documentation and scope

- Active CI documentation is already aligned with the canonical Makefile/workflow model; active-doc changes: `none`.
- Historical `docs/work/` packets, reviews, and submissions were not edited.
- No API, DB/Alembic, lifecycle, packet, executor, supervisor, runtime, or product semantics were changed.
- No lint/size allowlist, blanket ignore, or deterministic-test deselection was added.
- No next packet was started.
