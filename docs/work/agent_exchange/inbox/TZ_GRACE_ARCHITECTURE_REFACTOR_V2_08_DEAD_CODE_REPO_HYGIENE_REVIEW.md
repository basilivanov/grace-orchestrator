# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_08_DEAD_CODE_REPO_HYGIENE_REVIEW — tracked DB recurrence gap

## Review decision

Packet 08 is technically close, and the verified no-op lineage is valid, but one acceptance criterion is not actually satisfied by the current executable hygiene policy.

Do not start Packet 09. Fix only the issue below and submit the exact named resubmission.

## Blocking finding — tracked `*.db` / `*.db-shm` / `*.db-wal` are not rejected by executable hygiene policy

The Packet 08 submission states that tracked database/runtime state is absent and treats `tracked *.db` as an `ALREADY_ABSENT` confirmed runtime family. `.gitignore` also contains broad rules for:

```text
*.db
*.db-shm
*.db-wal
```

However, current `scripts/ci_repo_hygiene.py::tracked_runtime_artifacts()` does not have a matcher for those suffixes. Its executable `_TRACKED_RUNTIME_PATTERNS` currently covers only:

```text
^%2Ftmp%2F
^.goldw/
^.lw3/
^.grace-live-wt/
^src/gold-test/
```

Therefore a force-added tracked path such as:

```text
runtime.db
state/cache.db
runtime.db-shm
runtime.db-wal
```

is not rejected by `tracked_runtime_artifacts()` unless it independently matches another forbidden prefix such as `%2Ftmp%2F`.

The current focused tests do not expose the gap because their database example is `%2Ftmp%2Fsomething.db`, which is rejected by the encoded-temp prefix rather than by a DB suffix rule.

`.gitignore` is not a substitute for this CI guard: ignored files may already be tracked or may be intentionally force-added. Packet 08 requires the durable executable policy to reject recurrence of the confirmed tracked runtime/generated families.

## Required correction

Make the smallest in-scope correction.

### 1. Extend executable tracked-runtime policy

Update `scripts/ci_repo_hygiene.py` so tracked database runtime artifacts are rejected explicitly:

```text
*.db
*.db-shm
*.db-wal
```

Use a deterministic path matcher in `tracked_runtime_artifacts()` / `_TRACKED_RUNTIME_PATTERNS` or an equivalently narrow helper.

Current repository evidence shows no intentional tracked DB fixture and `.gitignore` already treats these suffixes globally as generated/runtime state, so do not invent a fixture exception without new repository evidence.

Do not broaden into unrelated filename cleanup or generic policy framework work.

### 2. Add regression cases that prove the DB rule itself

Extend `tests/scripts/test_ci_repo_hygiene.py` with representative paths that do **not** depend on another forbidden prefix, at minimum equivalents of:

```text
runtime.db
state/runtime.db-shm
state/runtime.db-wal
```

Assert they are rejected by `tracked_runtime_artifacts()`.

Keep the existing allowed source/fixture test and the exact-offending-path output test.

### 3. Strengthen architecture guard if needed

Ensure `tests/grace_control/architecture/test_repo_hygiene_boundary.py` proves the executable policy includes the DB runtime family, not merely `.gitignore` text.

A direct representative sample is sufficient. Do not duplicate the entire matcher implementation in the test.

## Frozen scope

Do not:

- delete or alter `src/hello.py` — the submitted KEEP_USED evidence is acceptable;
- delete migration helpers/documentation — their MANUAL_REVIEW/KEEP_HISTORICAL_DOC classification is acceptable;
- touch Makefile or GitHub Actions;
- start Packet 09;
- change API, DB schema, lifecycle, packet/executor/supervisor semantics;
- add lint/size allowlist exceptions;
- recreate already deleted legacy/runtime artifacts.

## Required verification

Run at minimum:

```bash
python3 scripts/ci_repo_hygiene.py
PYTHONPATH=src .venv/bin/pytest -q tests/scripts/test_ci_repo_hygiene.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_repo_hygiene_boundary.py

make lint
make docs-check
make hygiene
python3 -m py_compile scripts/ci_repo_hygiene.py tests/scripts/test_ci_repo_hygiene.py tests/grace_control/architecture/test_repo_hygiene_boundary.py
git diff --check
```

Also prove directly that representative tracked-path input containing ordinary `.db`, `.db-shm`, and `.db-wal` paths is rejected.

## Resubmission protocol

After the correction, commit and push the implementation and create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_08_DEAD_CODE_REPO_HYGIENE_RESUBMISSION.md`

It MUST begin exactly:

```text
WEB_ORCH_REPORT: RESUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_08_DEAD_CODE_REPO_HYGIENE
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-40-character-correction-sha>
WEB_ORCH_CHECKS: PASS
```

Then report:

- original reviewed base/implementation SHA `933c8e953aa03ff4887a1f3690f3f88f68acc994`;
- correction SHA;
- exact changed paths;
- exact DB suffix matcher behavior;
- focused test counts;
- canonical lint/docs/hygiene results;
- confirmation that no next packet was started.

Do not create any other review/next-task file.
