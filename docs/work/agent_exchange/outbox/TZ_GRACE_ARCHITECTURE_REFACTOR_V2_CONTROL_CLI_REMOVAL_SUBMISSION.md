WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CONTROL_CLI_REMOVAL
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: cf593a5d7c6e1ef686bdd94b09f04558343ec7a3
WEB_ORCH_CHECKS: PASS

Synced base SHA: `a05e5443936ba01edf02c1fb18ac6734c73fd5fb`.
Initial status was `## main...origin/main` with the pre-existing untracked
files `.env.bak-mini-endpoint-20260705170600` and `parse_list.py`; both were
preserved. The required sync status/fetch/fast-forward checks completed before
implementation, and `origin/main` was up to date.

Implementation commit: `cf593a5d7c6e1ef686bdd94b09f04558343ec7a3`, pushed to
`origin/main`.

Implemented only control CLI removal / API-only control-surface cleanup:

- physically deleted `src/grace_control/cli.py`;
- removed the obsolete CLI-presence test and added
  `tests/grace_control/api/test_no_control_cli_surface.py`, guarding module
  absence, package entry points, active references, OpenAPI construction, and
  direct supervisor bootstrap;
- changed `scripts/live_supervisor.sh` to execute the existing supported
  `python -m grace_control.supervisor` entry point with its existing arguments;
- updated lifecycle bootstrap/error messages to recommend the bootstrap script
  and HTTP API, without changing routes or lifecycle behavior;
- removed `typer` from project and Docker dependencies because no live import
  remains; retained `click` and `rich` as independently used dependencies;
- updated active supervisor/API-first docs and internal supervisor comments;
  historical `docs/work/` evidence was not rewritten;
- retained `supervisor_client.py` as an internal UDS transport for lifecycle
  integration/tests, and retained mini-swe, `UniversalCliAgentBackend`,
  `agent_run_service`, and runtime behavior.

Reference and dependency evidence:

- the required active-reference scan found zero hits outside deliberate
  negative assertions in `test_no_control_cli_surface.py`;
- the Typer import scan over `src scripts tests` returned zero hits;
- the direct supervisor module help/argument check passed, including
  `--target-dir`, `--source-dir`, `--workers`, `--api-url`, and `--no-watch`;
- `click` remains in Docker requirements because it is not proven to be
  control-CLI-only (Prefect ecosystem dependency).

Checks:

- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/api` — 145 passed,
  1 skipped;
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/runtime tests/grace_control/agent`
  — 122 passed;
- focused removal guard + supervisor unit/integration tests — 22 passed;
- `python3 scripts/grace_lint.py tests/grace_control/api/test_no_control_cli_surface.py`
  — passed;
- focused Ruff on the new architecture guard — passed; the touched legacy
  supervisor files retain their pre-existing Ruff findings;
- changed-file `py_compile`, `bash -n scripts/live_supervisor.sh`, and
  `git diff --check` — passed;
- repository-wide GraceLint remains non-zero from baseline debt: current
  violation lines 3320 vs 3339 on the synced base, both non-zero; no new
  packet violation was introduced;
- repository-wide Ruff remains non-zero from baseline debt: current output
  reports 1028 errors; the command is an environment/system Ruff invocation
  because `.venv/bin/ruff` is not installed. No unrelated lint cleanup was
  added.

The only remaining active matches for the forbidden CLI scan are the guard's
intentional negative assertions. No later packet or architecture wave was
started.
