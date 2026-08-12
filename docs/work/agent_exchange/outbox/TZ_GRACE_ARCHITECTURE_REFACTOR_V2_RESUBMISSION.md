WEB_ORCH_REPORT: RESUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 43be63babb8bbeaacf64770497e5c98fba960a48
WEB_ORCH_CHECKS: PASS

Correction commit: `43be63ba` (`fix: complete OpenCode legacy removal review`),
pushed to `origin/main` on top of the accepted implementation.

Review fixes:

- kept session resume only for the proven remaining non-OpenCode consumer,
  `coder_agy`;
- removed the generic `cli` `ses_*` extraction fallback and JSON/session-shape
  compatibility that had no supported owner;
- made `SessionStore` provider-neutral for external IDs, so healthy
  `conv_*` IDs are accepted while failed, timed-out, or unauthorized runs are
  still rejected;
- marked `coder_agy` explicitly `resume_safe: true` and added an end-to-end
  test covering Agy stdout extraction → DB persistence → `find_latest()` →
  `--conversation conv_*` injection;
- removed the unused `inject_dir` field, YAML entries, serializer, runtime
  mutation branch, documentation, and added a guard against its reintroduction.

Checks:

- required session/profile/architecture suite — `69 passed`;
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/runtime tests/grace_control/agent` — `122 passed`;
- mini-swe profile/backend regression — `30 passed`;
- packet executor acceptance/observability regression — `58 passed`;
- active OpenCode scan — only deliberate negative assertions in the
  architecture guard; no active implementation/profile/runtime hit;
- `python3 scripts/grace_lint.py tests/grace_control/architecture/test_no_opencode_legacy.py` — passed;
- changed-file `py_compile` — passed;
- `git diff --check` — passed.

The repository-wide GRACE lint still reports the pre-existing baseline canon
violations, and `ruff check src/grace_control tests scripts` still reports the
pre-existing 1047 baseline errors. The requested `python -m ruff` form cannot
run because this environment has no `python` executable; no unrelated lint
cleanup was added.

User untracked files `.env.bak-mini-endpoint-20260705170600` and `parse_list.py`
were preserved. No later packet or wave was started.
