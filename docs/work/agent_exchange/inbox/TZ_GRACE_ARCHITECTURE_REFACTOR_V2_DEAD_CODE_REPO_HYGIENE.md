# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_DEAD_CODE_REPO_HYGIENE — Packet 8: proven dead code and tracked runtime-state cleanup

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_DEAD_CODE_REPO_HYGIENE`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent programme: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative implementation detail: `docs/work/WORKER_GRACE_ARCHITECTURE_REFACTOR_V2.md`, **Wave 6 only**.
- Previous named packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_TYPED_ADMIN_READ_MODELS` is ACCEPTED.
- Implement **only proven dead-code removal and repository hygiene** in this packet.
- Do **not** start Wave 7 CI single-source-of-truth, Makefile/workflow consolidation, broad documentation rewrite, API/schema changes, or unrelated refactors.

This packet is self-contained. Do not invent or start another packet. Only Architect ACCEPT authorizes the next named TZ.

## Mandatory sync before work

Before inspecting implementation files or editing anything:

```bash
cd /opt/grace-orchestrator
git switch main
git fetch origin main
git merge --ff-only origin/main
git status --short
git rev-parse HEAD
```

Record synced base SHA and initial `git status --short` in the submission.

Preserve unrelated pre-existing untracked files, including `.env.bak-mini-endpoint-20260705170600` and `parse_list.py` if still present. Do not use `git reset --hard` or `git clean`.

Do not create repo-side `state.json`, lock files, web-orch metadata, or orchestration state.

---

# Objective

Remove only artifacts that can be **proved** to be dead/generated/obsolete, and make the repository reject recurrence of tracked runtime/generated state.

This is not a cosmetic cleanup. Every deletion requires evidence. Migration/history candidates are not deleted merely because they look old.

Current repository evidence already shows tracked generated/runtime-looking paths at repository root, including at least:

```text
%2Ftmp%2Fgrace-full.db
.goldw/
.grace-live-wt/
.lw3/
```

`.gitignore` already ignores `*.db`, `%2Ftmp%2F*` and `.grace/`, but currently does not by itself prove every tracked directory above may be deleted. Audit contents/references first, then remove only proven runtime/generated state and add the minimum missing ignore rules.

The current `scripts/ci_repo_hygiene.py` checks only:

- tracked `agents/` artifacts;
- legacy public script entrypoints;
- `src/prefect_grace` build-package presence.

Extend it narrowly so tracked runtime/generated state proven in this packet fails CI with exact offending paths.

---

# Frozen invariants / scope boundaries

1. No HTTP route/OpenAPI changes.
2. No DB schema/migration changes.
3. No packet lifecycle/state-machine/executor/supervisor behavior changes.
4. No admin/lifecycle architecture refactor in this packet.
5. Do not modernize dead Prefect-era demos into new supported product code; delete if proven dead, otherwise classify/keep.
6. Do not delete Alembic migrations simply because old names or historical transitions appear in them.
7. Do not delete committed fixtures merely because they live under a suspicious directory; prove whether tests/CI consume them.
8. Do not delete `.grace/` wholesale without classification; repository-local configuration may be intentional even though runtime state under similarly named paths is not.
9. Do not touch Makefile or `.github/workflows/ci.yml` except an absolutely necessary one-line reference removal caused by deleting a proven dead path. Wave 7 owns CI consolidation.
10. No new GRC005/GRC012 allowlist entries.
11. Preserve all supported mini-swe / internal CLI-subprocess execution infrastructure. This packet must not confuse internal agent execution with the already removed operator CLI.

---

# Phase A — build a tracked-path inventory before deleting

Run and include the relevant outputs/classification in the submission:

```bash
git ls-files | sort > /tmp/grace-tracked-files.txt

git ls-files | rg '(^|/)(%2Ftmp%2F|\.goldw/|\.lw3/|\.grace-live-wt/|src/gold-test/)|\.db($|[-.])' || true
```

Also inspect root and suspicious directories with `git ls-files <path>` and file types/sizes where useful.

For every suspicious tracked path determine whether it is:

```text
DELETE_NOW
KEEP_USED
KEEP_HISTORICAL_DOC
MANUAL_REVIEW
```

Do not delete `MANUAL_REVIEW` items.

---

# Phase B — dead-code candidates

Audit at minimum these candidates from the parent programme:

```text
src/hello.py
src/hello_grace.py
tests/test_hello_grace.py
src/grace_control/core/hello.py
src/grace_control/mod.py
tests/grace_control/core/test_mod.py
demo_resources.py
scripts/test_api_integration.py
src/gold-test/
```

For each candidate search by all of:

- exact path/basename;
- import path;
- exported class/function names;
- test references;
- Makefile/CI/script/runbook references;
- active docs outside historical `docs/work/` when relevant.

Examples:

```bash
rg -n 'hello_grace|from hello_grace|import hello_grace' . --glob '!docs/work/**' || true
rg -n 'grace_control\.mod|register_handler\(|validate_feature\(' . --glob '!docs/work/**' || true
rg -n 'demo_resources|test_api_integration' . --glob '!docs/work/**' || true
rg -n 'gold-test|src/gold-test' . --glob '!docs/work/**' || true
```

If a useless module is referenced only by its own obsolete test, delete module + test together.

If an exported name is still used by supported runtime/test code, keep it and document `KEEP_USED`; do not refactor it merely to make deletion possible.

---

# Phase C — old Prefect/demo integration candidates

Audit:

```text
demo_resources.py
scripts/test_api_integration.py
```

Specifically inspect for `prefect_grace`, removed operator CLI names, stale package/import paths, and supported runbook references.

Decision rule:

- no supported caller + obsolete package surface => `DELETE_NOW`;
- supported current workflow => `KEEP_USED` and explain;
- unclear external/manual use => `MANUAL_REVIEW`, no deletion.

Do not rewrite these files to Grace-v2 equivalents in this packet.

---

# Phase D — migration-script candidates, conservative

Audit:

```text
scripts/migrate_to_grace_package.sh
scripts/validate_migration.sh
scripts/rollback_migration.sh
scripts/MIGRATION_SCRIPTS.md
```

Search active references in:

```text
README.md
AGENTS.md
docs/grace/
docs/SUPERVISOR.md
scripts/
.github/
Makefile
pyproject.toml
```

Historical references in `docs/work/` are evidence/history, not an active caller.

Delete a migration script/doc only if all are true:

1. it targets obsolete `prefect_grace` / removed operator-CLI migration paths;
2. no active CI/runbook/deployment/operator workflow references it;
3. current supported deployments no longer need the migration;
4. deleting it does not remove an Alembic/data migration required for supported upgrades.

Otherwise classify `MANUAL_REVIEW` or `KEEP_HISTORICAL_DOC` and leave it untouched.

---

# Phase E — tracked runtime/generated artifacts

Audit tracked paths matching at least:

```text
%2Ftmp%2F*
.goldw/
.lw3/
.grace-live-wt/
src/gold-test/
*.db
*.db-shm
*.db-wal
```

Known root example currently tracked:

```text
%2Ftmp%2Fgrace-full.db
```

For each hit:

1. inspect references in `src`, `tests`, `scripts`, active docs, Makefile and workflows;
2. distinguish generated runtime state from intentional fixture/golden data;
3. delete proven generated state from the repository;
4. keep intentional fixtures and document why;
5. update `.gitignore` only with the minimum patterns needed to prevent proven generated paths from returning.

Expected likely ignore additions if the audit confirms those directories are generated:

```gitignore
.goldw/
.lw3/
.grace-live-wt/
```

Do not add an overbroad rule that hides legitimate test fixtures or source directories.

`*.db` and `%2Ftmp%2F*` are already ignored; if tracked instances are proven generated, remove the tracked files but do not duplicate ignore rules.

---

# Phase F — strengthen `scripts/ci_repo_hygiene.py`

Modify:

`src` — no broad changes expected.

Primary file:

`scripts/ci_repo_hygiene.py`

Keep the existing checks and add a narrow tracked-path check based on `git ls-files`.

Requirements:

1. Detect exact proven-bad tracked runtime/generated patterns from this audit.
2. Report every offending tracked path, not just a count.
3. Keep intentional committed fixtures out of the forbidden matcher.
4. Do not recursively scan untracked developer state; this gate is about what entered Git.
5. Preserve existing legacy-entrypoint/package checks.
6. Keep the script deterministic and runnable from repository root.
7. No network access.

Preferred structure:

```python
def tracked_files() -> tuple[str, ...]: ...
def tracked_runtime_artifacts(paths: Sequence[str]) -> tuple[str, ...]: ...
```

Exact factoring may vary. Do not build a generic policy framework.

Add focused tests for the hygiene matcher/script. Preferred path:

```text
tests/scripts/test_ci_repo_hygiene.py
```

If a current hygiene test file already exists, extend it instead of duplicating test ownership.

Tests should prove at minimum:

- `%2Ftmp%2Fsomething.db` is rejected;
- `.goldw/...`, `.lw3/...`, `.grace-live-wt/...` are rejected only if those paths are confirmed generated in this audit;
- an allowed source/test fixture is not falsely rejected;
- error output contains offending paths;
- existing legacy-entrypoint checks remain effective or are covered by existing tests.

---

# Required dead-code audit table

The submission must contain a table with one row per candidate/suspicious group and exactly these columns:

```text
path
decision
delete_confidence_percent
affect_probability_percent
references_found
reason
action
```

Interpretation:

- `delete_confidence_percent`: confidence that deletion is correct.
- `affect_probability_percent`: probability deletion affects a supported runtime/operator/test workflow.

Only physically delete when evidence is strong. A suggested threshold is `delete_confidence_percent >= 95` and `affect_probability_percent <= 5`, but repository evidence overrides arithmetic; uncertain items remain.

Include rows for at least:

```text
src/hello.py
src/hello_grace.py
tests/test_hello_grace.py
src/grace_control/core/hello.py
src/grace_control/mod.py
tests/grace_control/core/test_mod.py
demo_resources.py
scripts/test_api_integration.py
src/gold-test/
scripts/migrate_to_grace_package.sh
scripts/validate_migration.sh
scripts/rollback_migration.sh
scripts/MIGRATION_SCRIPTS.md
%2Ftmp%2F*
.goldw/
.lw3/
.grace-live-wt/
tracked *.db
```

---

# Architecture/hygiene guard

Add or extend focused tests so the repository fails when proven generated state is tracked again.

Preferred test path:

```text
tests/grace_control/architecture/test_repo_hygiene_boundary.py
```

or extend an existing `tests/scripts/test_ci_repo_hygiene.py` if that gives clearer ownership.

At minimum guard:

- `scripts/ci_repo_hygiene.py` still exists;
- the known proven runtime path patterns are represented in executable policy, not comments only;
- no active source import references files physically deleted in this packet;
- deleted legacy demo/module paths do not reappear as package/entrypoint references.

Avoid brittle checks against historical `docs/work/` evidence.

---

# Required verification

First run focused tests for every deleted/changed area discovered during the audit.

Then run at minimum:

```bash
python3 scripts/ci_repo_hygiene.py

PYTHONPATH=src .venv/bin/pytest -q tests/scripts
```

If there is no broad `tests/scripts` suite or unrelated tests there are known-broken, run the exact relevant hygiene tests and document the set.

Run regression suites for any deleted modules that had adjacent active tests/importers. If only obsolete self-tests were deleted, prove no surviving import/reference remains.

Run structural scans:

```bash
git ls-files | rg '(^|/)(%2Ftmp%2F|\.goldw/|\.lw3/|\.grace-live-wt/)|\.db($|[-.])' || true

rg -n 'hello_grace|grace_control\.mod|demo_resources|test_api_integration' \
  src tests scripts README.md AGENTS.md docs/grace docs/SUPERVISOR.md pyproject.toml Makefile .github || true
```

Interpret every remaining hit. Test data that intentionally names a deleted path is allowed only when it is a negative guard and clearly so.

Also run:

```bash
python3 scripts/grace_lint.py <all-changed-python-files-and-tests>
ruff check <all-changed-python-files-and-tests>
python3 -m py_compile <all-changed-python-files>
git diff --check
```

Run an appropriate broad regression set after deletions. Do **not** start Wave 7 by rewriting canonical Make targets/workflows to make this packet pass.

If `make ci` currently succeeds without Wave 7 changes, running it is useful evidence; if it fails from known pre-existing CI truth debt, record exact baseline evidence and do not rewrite CI in this packet.

---

# Acceptance criteria

PASS only if all are true:

1. Every deleted code/script/artifact path has explicit reference evidence supporting deletion.
2. No candidate marked uncertain is deleted.
3. Proven tracked runtime/generated state is removed from Git.
4. Intentional fixtures/golden data are preserved even if their path initially looked suspicious.
5. `.gitignore` gains only necessary rules for confirmed generated paths and does not hide legitimate source/fixtures.
6. `scripts/ci_repo_hygiene.py` rejects recurrence of the confirmed tracked runtime/generated patterns and prints exact offending paths.
7. Existing repo-hygiene checks for legacy entrypoints/package remain intact.
8. No supported runtime/API/schema/state-machine behavior is changed.
9. No Alembic migration required for supported upgrades is deleted.
10. Old Prefect/demo code is deleted only if proven unused; it is not modernized into new product code.
11. Submission includes the complete dead-code audit table with decisions/confidence/impact/reference evidence.
12. Relevant focused + regression tests pass; any pre-existing failure is distinguished with before-state evidence.
13. No Wave 7 Makefile/GitHub Actions consolidation is included.
14. No new lint/size allowlist exception is added.

---

# Required submission

After implementation/audit, commit and push the implementation to `origin/main`.

Create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_DEAD_CODE_REPO_HYGIENE_SUBMISSION.md`

It must begin with exactly:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_DEAD_CODE_REPO_HYGIENE
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-40-character-implementation-commit-sha>
WEB_ORCH_CHECKS: PASS
```

`WEB_ORCH_COMMIT` must identify the actual implementation/deletion commit, not the submission-document commit or current `main` HEAD.

Submission body must include:

- synced base SHA;
- initial status/untracked preservation;
- exact changed/deleted files;
- complete dead-code audit table;
- exact tracked runtime/generated paths removed;
- intentional suspicious paths kept and why;
- `.gitignore` changes and rationale;
- `ci_repo_hygiene.py` policy added;
- exact reference scans and remaining interpreted hits;
- exact tests/lint/check counts;
- any pre-existing failure with before-state evidence.

Do not create the next packet. Do not start Wave 7.
