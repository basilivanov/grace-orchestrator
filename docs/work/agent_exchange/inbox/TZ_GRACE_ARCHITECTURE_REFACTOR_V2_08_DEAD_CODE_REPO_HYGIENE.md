# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_08_DEAD_CODE_REPO_HYGIENE — Packet 08: proven dead code and repository hygiene

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_08_DEAD_CODE_REPO_HYGIENE`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent source: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative detail: Architecture Refactor V2 Wave 6 — dead code / repository hygiene only.
- Previous new-cycle packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_07_TYPED_ADMIN_READ_MODELS` is ACCEPTED.
- Historical agent-exchange packets from earlier cycles are evidence only. Do not edit/reuse their submission/review files.

Implement only this named packet. Do not start CI single-source-of-truth, Makefile/workflow consolidation, mutation refactoring, API/schema work, or any later wave.

## Mandatory fast-forward sync

Before inspecting implementation files or editing anything:

```bash
cd /opt/grace-orchestrator
git switch main
git fetch origin --prune
git pull --ff-only origin main
git status --short --branch
git rev-parse HEAD
```

Record synced base SHA and initial status. Preserve unrelated untracked files. Do not use `git reset --hard`, `git clean`, destructive checkout, repo-side `state.json`, lock files, or orchestration metadata.

## Current-state rule

This new cycle verifies/refines a repository that may already contain the earlier accepted Wave 6 cleanup.

1. Current synced `main` is authoritative.
2. Audit actual tracked files/current source first; do not recreate deleted legacy/demo/runtime artifacts merely because historical TZs list them as old candidates.
3. If every acceptance criterion is already satisfied, run the full audit/checks and submit a **verified no-op** using synced `HEAD` as `WEB_ORCH_COMMIT`.
4. Do not manufacture deletions or source edits merely to produce an implementation commit.
5. If a real gap exists, make only the smallest in-scope correction, commit/push it, and report the actual implementation SHA.
6. Uncertain files are kept. This packet deletes only artifacts whose dead/generated status is proven from the current repository.

## Objective

Keep the repository free of proven dead code and tracked runtime/generated state, while preserving legitimate fixtures, migrations, historical docs, and supported runtime infrastructure.

This is not a cosmetic cleanup campaign. Every deletion requires current evidence. The target also includes a durable executable hygiene policy so known runtime/generated paths cannot silently re-enter Git.

## Frozen invariants / scope boundaries

Preserve:

- HTTP/OpenAPI contracts;
- DB schema/Alembic migrations required for supported upgrades;
- packet lifecycle/state-machine/executor/supervisor behavior;
- Admin/lifecycle architecture accepted in Packets 03–07;
- mini-swe/Agy/internal CLI-subprocess agent execution;
- current deployment/bootstrap behavior;
- historical `docs/work/` evidence unless the packet itself creates its named submission.

Do not:

- rewrite dead demos into new supported product code;
- delete migrations just because names look old;
- delete committed fixtures/golden data without proof;
- modify Makefile or `.github/workflows/ci.yml` for CI consolidation — Packet 09 owns that;
- add GRC005/GRC012 allowlist entries;
- add broad ignore rules that hide legitimate source/tests.

## Audit before edits

### 1. Tracked runtime/generated inventory

Run:

```bash
git ls-files | sort > /tmp/grace-tracked-files.txt

git ls-files | rg '(^|/)(%2Ftmp%2F|\.goldw/|\.lw3/|\.grace-live-wt/|src/gold-test/)|\.db($|[-.])' || true
```

Classify every hit as one of:

```text
DELETE_NOW
KEEP_USED
KEEP_FIXTURE
KEEP_HISTORICAL_DOC
MANUAL_REVIEW
```

Do not delete `MANUAL_REVIEW`.

Expected historical bad-path families to verify remain absent or guarded:

```text
%2Ftmp%2F*
.goldw/
.lw3/
.grace-live-wt/
src/gold-test/
tracked *.db / *.db-shm / *.db-wal
```

If current Git has none of these, record zero hits; do not recreate them.

### 2. Dead-code candidate audit

Verify current existence/references for at least:

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

For every candidate that exists, search by path/basename/import/exported names in active source/tests/scripts/docs/runbooks/CI. Historical `docs/work/` hits are evidence, not active callers.

Suggested scans:

```bash
rg -n 'hello_grace|from hello_grace|import hello_grace' \
  src tests scripts README.md AGENTS.md docs/grace docs/SUPERVISOR.md pyproject.toml Makefile .github || true

rg -n 'grace_control\.mod|demo_resources|test_api_integration|gold-test|src/gold-test' \
  src tests scripts README.md AGENTS.md docs/grace docs/SUPERVISOR.md pyproject.toml Makefile .github || true
```

If the files are already absent, verify surviving active references are also absent except explicit negative guards/tests.

### 3. Migration helpers — conservative

Audit current status of:

```text
scripts/migrate_to_grace_package.sh
scripts/validate_migration.sh
scripts/rollback_migration.sh
scripts/MIGRATION_SCRIPTS.md
```

Do not delete them just because they are old. A current file may remain if it is still a supported migration/bootstrap aid. Delete only if current evidence proves all of:

- obsolete target/package/control surface;
- no active deployment/runbook/CI/operator caller;
- no supported upgrade path requires it.

Otherwise classify `KEEP_USED`, `KEEP_HISTORICAL_DOC`, or `MANUAL_REVIEW`.

### 4. Hygiene implementation

Inspect:

```text
scripts/ci_repo_hygiene.py
tests/scripts/test_ci_repo_hygiene.py
tests/grace_control/architecture/test_repo_hygiene_boundary.py
.gitignore
```

Verify the executable policy rejects recurrence of the proven runtime/generated tracked paths while preserving intentional fixtures.

Required properties:

- policy is based on tracked Git paths, not recursive untracked developer-state scanning;
- every violation reports the exact offending path;
- existing legacy entrypoint/package checks remain intact;
- no network access;
- deterministic output;
- `.gitignore` contains only the minimum confirmed generated-path rules.

If current implementation already satisfies this, do not duplicate guards or rewrite the script.

## Required current-state table

Submission must include an audit table with columns exactly:

```text
path
decision
delete_confidence_percent
affect_probability_percent
references_found
reason
action
```

Include at minimum rows/groups for:

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

For already absent paths, use a decision such as `ALREADY_ABSENT` in the `decision` column and explain the negative-reference evidence. Do not re-add a file just to classify/delete it again.

## Required architecture / hygiene guard

A durable current guard must prove directly or equivalently:

1. `scripts/ci_repo_hygiene.py` exists and executes repository hygiene policy.
2. Proven generated runtime path families cannot be tracked without failure.
3. Offending paths are surfaced explicitly.
4. Intentional source/test fixtures are not rejected merely because names look runtime-like.
5. Deleted legacy demo/module paths do not reappear as active package/entrypoint imports.
6. Existing removed control CLI/OpenCode boundaries are not weakened by hygiene changes.

Preferred existing paths:

```text
tests/scripts/test_ci_repo_hygiene.py
tests/grace_control/architecture/test_repo_hygiene_boundary.py
```

If these guards already exist and are strong, run them; do not create duplicate ownership.

## Required verification

Run at minimum:

```bash
python3 scripts/ci_repo_hygiene.py

PYTHONPATH=src .venv/bin/pytest -q tests/scripts/test_ci_repo_hygiene.py
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_repo_hygiene_boundary.py
```

Run final structural scans:

```bash
git ls-files | rg '(^|/)(%2Ftmp%2F|\.goldw/|\.lw3/|\.grace-live-wt/)|\.db($|[-.])' || true

rg -n 'hello_grace|grace_control\.mod|demo_resources|test_api_integration' \
  src tests scripts README.md AGENTS.md docs/grace docs/SUPERVISOR.md pyproject.toml Makefile .github || true
```

Interpret every remaining hit. Negative guard fixtures/tests are allowed when clearly intentional.

Also run:

```bash
make lint
make docs-check
make hygiene
python3 -m py_compile <changed-python-files-if-any>
git diff --check
```

If source files are actually deleted/changed, run focused adjacent regressions and an appropriate broad regression set. Do not start Packet 09 CI consolidation to fix unrelated baseline CI debt.

For baseline-aware lint, report canonical `make lint` success separately from raw Ruff/GraceLint debt.

## Submission protocol

If corrections are required, commit/push them and use the full 40-character implementation SHA. If current `main` already satisfies the packet, use synced `HEAD` and explicitly state `verified no-op`.

Create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_08_DEAD_CODE_REPO_HYGIENE_SUBMISSION.md`

It MUST begin exactly:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_08_DEAD_CODE_REPO_HYGIENE
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-40-character-implementation-sha>
WEB_ORCH_CHECKS: PASS
```

Then include:

- synced base SHA and initial status;
- implementation SHA or verified-no-op statement;
- complete current-state audit table;
- tracked runtime/generated inventory and interpreted zero/non-zero hits;
- exact deleted/changed paths, or `none` for no-op;
- migration-helper classification;
- `.gitignore`/hygiene policy evidence;
- exact targeted test/check results;
- remaining active-reference scan hits and interpretation.

Do not create/start the next packet. Wait for Architect ACCEPT/REVIEW.

## Acceptance criteria

Architect ACCEPT requires all of:

1. Every deletion, if any, has current reference evidence supporting it.
2. No uncertain candidate is deleted.
3. Proven tracked runtime/generated state is absent from Git.
4. Intentional fixtures/historical docs/migrations are preserved when not proven dead.
5. `.gitignore` and executable hygiene policy are narrow and sufficient.
6. `scripts/ci_repo_hygiene.py` rejects recurrence of confirmed bad tracked paths and reports exact offenders.
7. Existing repo-hygiene/legacy-entrypoint checks remain effective.
8. Dead historical demo/module paths remain absent or have a documented current reason to exist.
9. No runtime/API/schema/lifecycle/packet semantics are changed.
10. No Packet 09 CI consolidation or lint allowlist expansion is mixed in.
11. Audit table and regression/check evidence are complete and truthful.
12. Submission follows the exact named-file protocol with a full SHA.
