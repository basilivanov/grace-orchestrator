WEB_ORCH_REPORT: RESUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_08_DEAD_CODE_REPO_HYGIENE
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: 93b247a0cf4411c268f00feaa4d714948152f349
WEB_ORCH_CHECKS: PASS

# Packet 08 resubmission

## Correction lineage

- Original reviewed base/implementation SHA: `933c8e953aa03ff4887a1f3690f3f88f68acc994`.
- Review commit observed during sync: `85eb263e2838ac7226937ae69592e8245ef291b5`.
- Correction SHA: `93b247a0cf4411c268f00feaa4d714948152f349`.
- The correction was pushed to `origin/main`.
- Only the review-required source and guard tests were changed; pre-existing unrelated untracked files were preserved.

## Exact correction

Changed paths:

- `scripts/ci_repo_hygiene.py`
- `tests/scripts/test_ci_repo_hygiene.py`
- `tests/grace_control/architecture/test_repo_hygiene_boundary.py`

The executable tracked-path policy now includes the narrow deterministic matcher:

```text
^(?:[^/]+/)*[^/]+\.db(?:-(?:shm|wal))?$
```

It rejects repository-relative tracked paths ending in exactly `.db`, `.db-shm`, or `.db-wal`, including nested paths. It does not scan untracked developer state, access the network, or broaden unrelated filename policy. Existing runtime-family matchers and legacy-entrypoint/package checks remain unchanged.

Direct representative proof:

```text
runtime.db          -> rejected
state/runtime.db-shm -> rejected
state/runtime.db-wal -> rejected
```

The exact-path CLI diagnostic behavior remains covered by the existing test and reports each offending path.

## Verification

- `python3 scripts/ci_repo_hygiene.py` — PASS (`OK: repo-hygiene passed`).
- `PYTHONPATH=src .venv/bin/pytest -q tests/scripts/test_ci_repo_hygiene.py` — PASS, 4 passed.
- `PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_repo_hygiene_boundary.py` — PASS, 2 passed.
- Combined targeted run — PASS, 6 passed.
- Direct DB suffix matcher assertion — PASS for `runtime.db`, `state/runtime.db-shm`, and `state/runtime.db-wal`.
- `make lint` — PASS; baseline-aware gate matched reviewed baseline (`ruff=1020`, `gracelint=3249`).
- `make docs-check` — PASS (`docs freshness OK — 3 files in sync`).
- `make hygiene` — PASS (`OK: repo-hygiene passed`).
- `python3 -m py_compile scripts/ci_repo_hygiene.py tests/scripts/test_ci_repo_hygiene.py tests/grace_control/architecture/test_repo_hygiene_boundary.py` — PASS.
- `git diff --check` — PASS.

No next packet was started.
