WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 46a004f4c6a7d2ac80e17bcbc53e079dc64e1abc
WEB_ORCH_CHECKS: PASS

Synced base: `95bfc1f0118622d07b9ff0dc84aa47a381e258f8`; pre-existing untracked
files `.env.bak-mini-endpoint-20260705170600` and `parse_list.py` were preserved.

Implementation commit: `46a004f4c6a7d2ac80e17bcbc53e079dc64e1abc`.

Implemented only Packet 1 (OpenCode legacy removal):

- deleted the seven `src/grace_control/runtime/opencode_*.py` runtime files;
- removed OpenCode-only packet selection, settings, project mapping, profile
  entries, environment/session compatibility, and stale active documentation;
- removed six OpenCode-only runtime tests and added the durable architecture
  guard `tests/grace_control/architecture/test_no_opencode_legacy.py`;
- preserved mini-swe profiles, `UniversalCliAgentBackend`, generic session
  resume, and the unrelated `agy` execution path.

Verification:

- active OpenCode scan: only deliberate negative assertions in the new guard;
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/runtime tests/grace_control/agent` — 122 passed;
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_no_opencode_legacy.py` — 1 passed;
- packet executor acceptance/observability tests — 58 passed;
- profile/config/backend tests — 49 passed;
- session/recovery/context/planning tests — 134 passed;
- additional runtime/profile tests — 53 passed;
- `python3 scripts/grace_lint.py tests/grace_control/architecture/test_no_opencode_legacy.py` — passed;
- `py_compile` for changed Python files — passed;
- `git diff --check` — passed.

The repository-wide GRACE lint and Ruff commands retain pre-existing baseline
violations outside this packet; they were not broadened into unrelated cleanup.
The four unrelated visual-baseline tests also retain their pre-existing
database-initialization failure; the stage-0 tests passed.

The remaining `opencode` text is limited to negative architecture-guard
assertions. Historical `docs/work/` evidence was not rewritten.
