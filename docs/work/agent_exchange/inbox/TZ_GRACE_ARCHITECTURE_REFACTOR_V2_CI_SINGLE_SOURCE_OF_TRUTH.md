# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CI_SINGLE_SOURCE_OF_TRUTH — Packet 9: canonical CI truth and final architecture verification

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CI_SINGLE_SOURCE_OF_TRUTH`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent programme: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative implementation detail: `docs/work/WORKER_GRACE_ARCHITECTURE_REFACTOR_V2.md`, **Wave 7 + final verification only**.
- Previous named packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_DEAD_CODE_REPO_HYGIENE` is ACCEPTED.
- Implement **only CI single-source-of-truth, supported-test classification needed to make that CI truthful, focused active-doc alignment, and final programme verification**.
- Do not start unrelated product refactors, mutation-service cleanup, API/schema changes, dependency-architecture rewrites, or new runtime capabilities.

This packet is self-contained. Do not invent a next packet. Only Architect ACCEPT closes/continues the programme.

---

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

Record synced base SHA and initial status in the submission.

Preserve unrelated pre-existing untracked files, including `.env.bak-mini-endpoint-20260705170600` and `parse_list.py` if still present. Do not use `git reset --hard` or `git clean`.

Do not create repo-side `state.json`, lock files, orchestration metadata, or web-orch state.

---

# Current verified baseline facts

At packet creation, the repository has these concrete CI-truth problems.

## Makefile drift

Current `Makefile`:

```make
 test:
 	GRACE_DB_URL=$(GRACE_DB_URL) $(PYTHON) -m pytest tests/grace_control/ -q

 test-all:
 	GRACE_DB_URL=$(GRACE_DB_URL) $(PYTHON) -m pytest tests/grace_control/ -q

 lint:
 	$(PYTHON) -m ruff check src/grace_control/
 	$(PYTHON) scripts/grace_lint.py src/

 ci: test lint docs-check
 	@$(PYTHON) scripts/ci_repo_hygiene.py
```

`test` and `test-all` are currently identical and both ignore large parts of `pytest`'s configured `tests/` tree, including `tests/scripts`, `tests/supervisor`, top-level tests and other suites.

## GitHub Actions drift

Current `.github/workflows/ci.yml` duplicates the policy instead of delegating to canonical repository commands:

- unit-tests directly runs `pytest tests/grace_control/`;
- GraceLint directly runs `python scripts/grace_lint.py src/grace_control tests scripts`;
- no equivalent Ruff step exists there;
- docs directly uses `make docs-check`;
- repo-hygiene reimplements old inline Python checks for `agents/`, legacy entrypoints, and `src/prefect_grace` instead of invoking `scripts/ci_repo_hygiene.py`;
- therefore GitHub's inline hygiene does not automatically inherit Packet 8's new tracked-runtime policy.

## Pytest tree is broader than CI

`pyproject.toml` declares:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```

The current `tests/` tree includes at least:

```text
tests/api/
tests/grace_control/
tests/integration/
tests/live/
tests/scripts/
tests/supervisor/
tests/ui/
top-level tests/test_*.py
```

Do not continue the accidental `tests/grace_control/` subset merely because it is green.

## Known orphan-test debt to classify

`tests/scripts/test_grace_changed_files_lint.py` exists and imports/executes:

```text
scripts/grace_changed_files_lint.py
```

but that script is absent on the accepted pre-Packet-8 base and remains absent now. Packet 8's `tests/scripts` run therefore had existing failures/errors from this orphaned contract.

Do **not** blindly recreate the script just to make tests green. First inspect:

- active `.github/` workflows;
- Makefile/scripts;
- `tests_live/` scenarios;
- active docs/runbooks outside `docs/work/`;
- package/runtime imports.

Then classify the missing-script contract:

```text
KEEP_SUPPORTED_FIX_NOW
DELETE_OBSOLETE_TEST
MANUAL_REVIEW_BLOCKER
```

If there is a current supported caller requiring changed-files frontend lint, implement/restore the smallest correct script and keep its tests. If only historical/dry-pilot evidence references it and no supported workflow calls it, delete the orphan test rather than resurrecting dead infrastructure. Explain evidence in submission.

## Known broad-test baseline

Packet 8 recorded:

```text
PYTHONPATH=src .venv/bin/pytest -q tests
1970 passed, 30 skipped, 42 failed, 19 errors
```

Reported categories included `/tmp/grace_planning_logs` permission/runtime setup, missing `grace_changed_files_lint.py`, missing Playwright page fixture, and other integration/fixture debt.

This packet owns making CI truth explicit. It does **not** mean fixing every live/manual test by forcing it into deterministic GitHub CI. It does mean every test under canonical CI must be intentional and green, and every excluded environment/live suite must be explicit, named, justified and separately runnable — never hidden by an accidental directory subset.

---

# Objective

Make repository-local commands the only implementation of CI policy and make GitHub Actions delegate to those commands.

Target model:

```text
Makefile / canonical scripts
    make test        -> deterministic supported CI test suite
    make test-all    -> broader explicitly classified test suite, if a distinction remains useful
    make lint        -> Ruff + GraceLint using canonical scopes
    make docs-check  -> generated docs/OpenAPI drift
    make hygiene     -> scripts/ci_repo_hygiene.py
    make ci          -> canonical CI aggregate

GitHub Actions
    install supported dependencies
    call canonical Make targets
    do not reimplement test/lint/hygiene policy inline
```

The final accepted state must answer one simple question: **what does CI mean?** The answer must live in repository commands, not partly in YAML, partly in Make, and partly in ad-hoc shell/Python snippets.

---

# Frozen product/architecture invariants

1. No HTTP route or OpenAPI contract changes.
2. No DB schema/Alembic/data migration changes.
3. No packet lifecycle, execution, supervisor, acceptance, reviewer/verifier, merge or recovery behavior changes.
4. OpenCode runtime remains removed.
5. User/control CLI remains removed.
6. `UniversalCliAgentBackend`, internal subprocess execution and mini-swe remain supported internal execution infrastructure; do not confuse them with the removed operator CLI.
7. FastAPI/OpenAPI remains the only public runtime/operator control surface after bootstrap.
8. `scripts/live_supervisor.sh` remains bootstrap; do not add a replacement operator CLI.
9. Packet 8 repo-hygiene logic remains canonical and must not be copied back into workflow YAML.
10. No new GRC005/GRC012 allowlist entries.
11. Do not weaken tests/lint merely to get green CI.
12. Do not add blanket `--ignore`, `-k not ...`, or broad deselection rules without per-suite classification and explicit rationale.
13. Do not rewrite historical `docs/work/` evidence to make scans green.

---

# Phase A — establish a reproducible baseline before edits

Run and save exact outputs on the synced base:

```bash
make test || true
make test-all || true
make lint || true
make docs-check || true
python3 scripts/ci_repo_hygiene.py || true
make ci || true

PYTHONPATH=src .venv/bin/pytest -q tests || true
PYTHONPATH=src .venv/bin/pytest -q tests/scripts || true

python3 scripts/grace_lint.py src/grace_control tests scripts || true
python -m ruff check src/grace_control tests scripts || true
```

Also inventory collection rather than guessing:

```bash
PYTHONPATH=src .venv/bin/pytest --collect-only -q tests > /tmp/grace-pytest-collection.txt
```

Record command exit codes and concise failure categories before edits.

Do not call something pre-existing later unless it is present in this baseline or directly provable from the synced commit.

---

# Phase B — classify the supported test surface

Create a short classification in the submission for every top-level test family that exists, including at least:

```text
tests/grace_control
tests/scripts
tests/supervisor
tests/api
tests/integration
tests/live
tests/ui
top-level tests/test_*.py
```

Use only these decisions:

```text
CI_REQUIRED
EXPLICIT_LIVE_OR_EXTERNAL
DELETE_OBSOLETE
MANUAL_REVIEW_BLOCKER
```

Rules:

- `CI_REQUIRED`: deterministic on a clean CI runner after normal dev install; must be included in canonical `make test` and must pass.
- `EXPLICIT_LIVE_OR_EXTERNAL`: genuinely requires a running external service/browser/system dependency/real machine state that should not be silently simulated; must have an explicit documented command/target and must not be accidentally collected by canonical CI.
- `DELETE_OBSOLETE`: tests target a deleted/non-supported surface and have no supported caller; delete them with evidence.
- `MANUAL_REVIEW_BLOCKER`: uncertainty remains; do not hide it — report blocker rather than inventing an exclusion.

Do not classify a deterministic integration test as live merely because it currently fails. Fix supported deterministic fixture/setup debt when bounded and necessary for truthful CI.

Do not move tests between directories solely to game collection.

## Environment/live tests

If genuine live/external suites are currently mixed into ordinary collection, prefer explicit pytest markers/config and a clearly named Make target such as `test-live` rather than an opaque directory omission.

Canonical `make test` may exclude explicit `live`/external markers **only if**:

1. those tests are characterized as requiring external environment;
2. the exclusion is visible in Make/docs;
3. there is a separate command that runs them;
4. deterministic supported tests are not hidden under the same marker.

Do not use `--ignore=tests/<whole-family>` as a substitute for classification unless that entire family is genuinely live and documented.

---

# Phase C — resolve orphaned / obsolete tests needed for CI truth

At minimum resolve `tests/scripts/test_grace_changed_files_lint.py` using the evidence rule above.

Also audit every baseline failure/error that would otherwise be inside `CI_REQUIRED`.

Allowed work in this packet:

- repair deterministic test fixture/setup errors;
- delete tests proven to target removed/dead surfaces;
- add/fix a small CI/dev helper script that is demonstrably still part of supported repository workflow;
- add missing **dev/test tooling dependencies** necessary for clean CI installation;
- add a missing **runtime dependency** only if current production code imports it and clean-install CI proves package metadata is wrong.

Not allowed:

- product behavior changes to satisfy stale tests;
- rebuilding old Prefect/OpenCode/control-CLI surfaces;
- changing API responses because an old test expects them;
- large unrelated refactors.

If a stale test contradicts the accepted current product architecture, delete/update the stale test rather than regress the product.

---

# Phase D — make Makefile canonical

Refactor `Makefile` so the targets have non-overlapping, truthful meanings.

Required targets:

```text
make test
make lint
make docs-check
make hygiene
make ci
```

`test-all` may remain only if it has a real broader meaning after classification. If it remains, document exactly how it differs from `test`.

## `make test`

Must run the full deterministic `CI_REQUIRED` test set. It must not be merely `tests/grace_control/` by historical accident.

Prefer one pytest invocation rooted at `tests/` plus explicit supported marker expression/config over manually enumerating dozens of directories.

## `make lint`

Must invoke both:

```text
Ruff
GraceLint
```

Use one canonical scope that covers supported Python source/test/script code. Do not let GitHub Actions use a broader/different scope than Make.

If broad Ruff/GraceLint reveals existing debt, fix new/current violations needed for the canonical supported scope. Do not add broad ignores or allowlist entries as a shortcut.

## `make hygiene`

Add an explicit target delegating only to:

```bash
$(PYTHON) scripts/ci_repo_hygiene.py
```

No duplicate policy in Make.

## `make ci`

Must compose canonical targets, conceptually:

```text
test + lint + docs-check + hygiene
```

Do not duplicate their commands inside `ci`.

`make ci` must be the authoritative local gate for this programme.

---

# Phase E — simplify GitHub Actions

Update `.github/workflows/ci.yml` so CI jobs/steps call canonical Make targets instead of reimplementing policy.

A Python 3.11/3.12 test matrix may remain. Acceptable patterns include:

```text
matrix job -> make test
single 3.12 quality job -> make lint && make docs-check && make hygiene
```

or a clean equivalent.

Requirements:

1. No inline Python copy of repo-hygiene policy remains.
2. No direct `pytest tests/grace_control/` remains if `make test` is canonical.
3. No separate GraceLint command with scope different from `make lint`.
4. Ruff is not omitted from GitHub CI.
5. Docs freshness uses canonical `make docs-check`.
6. Install step provides everything those canonical targets need on a fresh Ubuntu runner.
7. Do not add network/service dependencies to tests beyond normal package/dependency installation.

If GitHub matrix repeats expensive quality gates unnecessarily, keep quality gates on one Python version and tests on the supported matrix.

---

# Phase F — dependency/install truth

A fresh GitHub runner executes:

```bash
pip install -e ".[dev]"
```

Audit whether `[dev]` plus runtime dependencies actually provide the tools/imports required by canonical CI.

Current `pyproject.toml` does not visibly list every tool used by current workflow/Make targets (for example, verify `pytest`, `pytest-asyncio`, `ruff`, `fastapi`, `httpx`, template/browser requirements, etc. rather than assuming the image provides them).

Rules:

- add dev dependencies only when canonical tests/lint require them;
- add runtime dependencies only when production package imports require them;
- do not rely on globally preinstalled packages on the developer VPS or GitHub runner;
- do not add giant convenience dependency bundles.

Add a narrow clean-install/metadata test only if useful and deterministic; do not build a package-manager framework.

---

# Phase G — final active-doc alignment

Update only current active docs/runbooks that are factually stale because Waves 1–7 are complete.

Inspect at minimum:

```text
README.md
AGENTS.md
docs/README.md
docs/grace/CANON.md
docs/grace/ARCHITECTURE.md
docs/grace/API_FIRST_CONTROL_PLANE.md
docs/grace/EXECUTION_BACKENDS.md
docs/grace/RUNBOOK_LOCAL_DEV.md
docs/SUPERVISOR.md
```

Change only what current architecture evidence supports.

Must accurately state:

- OpenCode runtime removed;
- control/user CLI removed;
- mini-swe and generic internal CLI/subprocess backend remain supported execution infrastructure;
- API/OpenAPI is the only public runtime/operator control surface after bootstrap;
- lifecycle router delegates to explicit service/ports;
- Admin cross-project/Control Center/aggregation services use explicit composition/DI rather than reverse facade/private setter coupling;
- typed Admin read models exist only at bounded shared boundaries;
- repository hygiene rejects tracked generated runtime state;
- `make ci` is canonical CI truth and GitHub Actions delegates to repository targets.

Do not rewrite historical `docs/work/`, old submissions, archived evidence, or migration history.

Fix active-doc links that point to nonexistent active files when encountered in the files you touch. Example already observed: `docs/grace/API_FIRST_CONTROL_PLANE.md` references `docs/grace/CI_CD.md`, which is absent; point to the actual canonical CI documentation/Makefile/runbook rather than creating a fake file solely to preserve the link.

---

# Phase H — architecture/final guards

Add focused tests only where necessary to lock CI truth. Preferred new guard:

```text
tests/grace_control/architecture/test_ci_single_source_of_truth.py
```

At minimum assert structurally:

1. Makefile defines `test`, `lint`, `docs-check`, `hygiene`, `ci`.
2. `ci` composes canonical targets instead of reimplementing hygiene policy.
3. workflow does not contain inline `git ls-files agents/` / legacy-entrypoint / `src/prefect_grace` policy copies.
4. workflow invokes canonical Make targets.
5. workflow does not directly hardcode `pytest tests/grace_control/`.
6. workflow quality gates include Ruff through canonical `make lint`.
7. `scripts/ci_repo_hygiene.py` remains the single executable hygiene policy.
8. no orphan reference remains to deleted tests/helpers resolved in this packet.

Keep the guard structural, not a YAML-parser framework.

---

# Mandatory final programme scans

Run exactly after implementation:

```bash
rg -n -i 'opencode|agent_runtime_use_opencode_adapter|OPENCODE_' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true

rg -n 'grace_control\.cli|grace_ctl|python -m grace_control\.cli' \
  src tests scripts docs/grace docs/SUPERVISOR.md README.md AGENTS.md pyproject.toml docker || true

rg -n 'self\._facade|_facade\._hub|_hub\._registry' \
  src/grace_control/services/admin_* || true

rg -n 'class .*Mixin' src/grace_control/services/admin_cross_project* || true

rg -n '\._artifact_service\s*=|\._session_service\s*=' \
  src/grace_control/services/admin_* || true

rg -n 'os\.environ|subprocess|get_db\(|\.query\(|supervisor\.json|AsyncHTTPTransport' \
  src/grace_control/api/routers/lifecycle.py || true

git ls-files | rg '(^|/)(%2Ftmp%2F|\.goldw/|\.lw3/|\.grace-live-wt/|src/gold-test/)' || true
```

Interpret every hit.

Allowed examples:

- architecture negative tests containing banned terms as test data;
- historical docs are excluded from scans above where intended;
- `UniversalCliAgentBackend` / `backend: cli` is allowed because it is internal execution infrastructure, not the removed operator CLI.

Not allowed:

- active OpenCode runtime/profile/setting references;
- active user/control CLI entrypoints or runbook commands;
- Control Center reverse facade coupling;
- aggregation setter injection;
- lifecycle router infrastructure logic;
- tracked proven runtime artifacts.

---

# Required verification

After classification/fixes, run:

```bash
make test
make lint
make docs-check
make hygiene
make ci
```

All five must exit 0.

Also run:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture
python3 scripts/grace_lint.py src/grace_control tests scripts
python -m ruff check src/grace_control tests scripts
git diff --check
```

If `test-all` remains, run it and report its exact semantics/results. If it intentionally includes live/external tests and is non-green without an environment, its name/help text must say so clearly and it must not be a dependency of `make ci`.

Run `make docs` only if generated docs need regeneration from current source; there should be no route drift. `make docs-check` must pass afterward.

If OpenAPI changes unexpectedly, STOP and report BLOCKER; this packet does not authorize HTTP contract changes.

---

# Acceptance criteria

PASS only if all are true:

1. `make test` represents the explicitly classified deterministic supported CI test surface, not an accidental directory subset.
2. Any live/external test exclusion is explicit, documented and separately runnable.
3. Orphan tests such as `test_grace_changed_files_lint.py` are resolved by evidence — supported helper restored/fixed or obsolete test deleted; no zombie contract remains.
4. `make lint` is the only canonical Ruff + GraceLint definition and uses one deliberate supported scope.
5. `make hygiene` delegates to `scripts/ci_repo_hygiene.py`.
6. `make ci` composes canonical repository targets and exits 0.
7. `.github/workflows/ci.yml` delegates to canonical Make targets and contains no duplicate repo-hygiene implementation.
8. GitHub CI does not silently omit Ruff or use a different GraceLint/test scope.
9. Fresh install metadata includes the actual dependencies needed by supported runtime and canonical CI; no reliance on machine-global packages.
10. No supported product/API/state-machine behavior is changed to satisfy stale tests.
11. Active docs reflect final architecture and canonical CI truth; historical evidence is not rewritten.
12. Mandatory OpenCode/control-CLI/Admin-DI/lifecycle/runtime-artifact scans have no active violations.
13. Architecture guard(s), focused tests, lint, docs check, hygiene and `make ci` pass.
14. No new GRC005/GRC012 allowlist exception is added.
15. No unrelated refactor or new product capability is included.

---

# Required submission

After implementation, commit and push the implementation to `origin/main`.

Create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CI_SINGLE_SOURCE_OF_TRUTH_SUBMISSION.md`

It must begin exactly:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CI_SINGLE_SOURCE_OF_TRUTH
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-40-character-implementation-commit-sha>
WEB_ORCH_CHECKS: PASS
```

Submission must include:

- synced base SHA and initial status;
- before-edit baseline exit codes/failure categories;
- complete top-level test-family classification (`CI_REQUIRED`, `EXPLICIT_LIVE_OR_EXTERNAL`, `DELETE_OBSOLETE`, `MANUAL_REVIEW_BLOCKER`);
- decision/evidence for `test_grace_changed_files_lint.py` and any other orphan tests;
- exact Makefile target semantics after refactor;
- exact workflow delegation graph;
- dependency metadata changes and why, if any;
- active docs changed and factual reason for each;
- mandatory final scan output/interpretation;
- exact test/lint/docs/hygiene/`make ci` results;
- exact changed/deleted files;
- confirmation that OpenAPI/routes/schema/runtime behavior did not change.

Do not create a next task.