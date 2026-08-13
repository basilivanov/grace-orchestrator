# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_09_CI_SINGLE_SOURCE_OF_TRUTH — Packet 09: canonical CI truth and final programme verification

## Packet identity

- `TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_09_CI_SINGLE_SOURCE_OF_TRUTH`
- Role: Coder
- Repository: `/opt/grace-orchestrator`
- Upstream: `origin/main`
- Parent source: `docs/work/TZ_GRACE_ARCHITECTURE_REFACTOR_V2.md`
- Normative detail: Architecture Refactor V2 Wave 7 + final programme verification only.
- Previous new-cycle packet `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_08_DEAD_CODE_REPO_HYGIENE` is ACCEPTED after review correction.
- Historical agent-exchange packets from earlier cycles are evidence only. Do not edit/reuse their submission/review files.

Implement only this named packet. Do not start unrelated product refactors, API/schema work, mutation-service cleanup, dependency-architecture rewrites, new runtime capabilities, or another packet.

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

This new cycle verifies/refines a repository that already may contain the earlier accepted Wave 7 implementation.

1. Current synced `main` is authoritative.
2. Audit actual Makefile/workflow/tests/scripts/docs first; do not recreate historical CI drift merely because older TZs describe the pre-refactor state.
3. If every acceptance criterion is already satisfied, run the required verification and submit a **verified no-op** using synced `HEAD` as `WEB_ORCH_COMMIT`.
4. Do not manufacture Makefile/workflow/docs edits merely to produce an implementation commit.
5. If a real gap exists, make only the smallest in-scope correction, commit/push it, and report the actual implementation SHA.
6. Packet 08 correction is now part of the frozen baseline: canonical hygiene must continue rejecting tracked `%2Ftmp%2F*`, `.goldw/`, `.lw3/`, `.grace-live-wt/`, `src/gold-test/`, `*.db`, `*.db-shm`, and `*.db-wal` families through the executable hygiene gate.

## Objective

Ensure repository-local commands are the single implementation of CI policy and GitHub Actions delegates to those commands. Then perform final Architecture Refactor V2 verification.

Target model:

```text
Makefile / canonical scripts
    make test       -> deterministic supported pytest surface
    make test-live  -> explicitly external/live pytest + live scenarios
    make lint       -> canonical Ruff + GraceLint baseline-aware gate
    make docs-check -> generated docs freshness
    make hygiene    -> scripts/ci_repo_hygiene.py
    make ci         -> test + lint + docs-check + hygiene

GitHub Actions
    install supported deps
    call canonical Make targets
    do not duplicate test/lint/hygiene policy inline
```

The final state must answer one question unambiguously: **what does CI mean?** The answer must live in repository commands, not be split across YAML, Make, ad-hoc shell snippets, and stale helper scripts.

## Frozen product / architecture invariants

Preserve all accepted behavior from Packets 01–08:

- OpenCode runtime remains removed;
- public/user control CLI remains removed;
- mini-swe, Agy and generic internal subprocess/CLI execution infrastructure remain supported;
- FastAPI/OpenAPI remains the public runtime/operator control surface after bootstrap;
- `scripts/live_supervisor.sh` remains bootstrap;
- Admin cross-project transport/composition boundaries remain explicit;
- Admin Control Center dependency inversion remains explicit with no reverse facade/private-state coupling;
- Admin aggregation graph remains acyclic with shared `PacketRunResolver` and constructor-only wiring;
- lifecycle router remains a thin HTTP adapter over explicit services/ports;
- bounded typed Admin read models preserve exact external dictionaries;
- Packet 08 repository hygiene remains canonical and executable;
- DB schema/Alembic, API/OpenAPI, packet states/IDs, execution/reviewer/recovery/merge semantics remain unchanged.

Do not add GRC005/GRC012 allowlist entries. Do not weaken tests/lint simply to obtain green CI. Do not add blanket ignores/deselection without an explicit already-accepted external/live classification.

## Audit before edits

Inspect at minimum:

```text
Makefile
.github/workflows/ci.yml
pyproject.toml
scripts/ci_lint_baseline.py
.grace/ci_lint_baseline.json
scripts/ci_repo_hygiene.py
tests/grace_control/architecture/test_ci_single_source_of_truth.py

tests/grace_control/architecture/test_no_opencode_legacy.py
tests/grace_control/api/test_no_control_cli_surface.py
tests/grace_control/architecture/test_admin_cross_project_composition.py
tests/grace_control/architecture/test_admin_control_center_dependency_inversion.py
tests/grace_control/architecture/test_admin_aggregation_dependency_graph.py
tests/grace_control/architecture/test_lifecycle_router_boundary.py
tests/grace_control/architecture/test_admin_read_models_boundary.py
tests/grace_control/architecture/test_repo_hygiene_boundary.py
```

If exact guard filenames differ, discover their current equivalents rather than duplicating ownership.

Also inspect current active CI/runbook statements in:

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

Only change active docs if current facts are stale. Historical `docs/work/` evidence must not be rewritten.

## Required target state

### 1. Canonical Make targets

`Makefile` must define and truthfully implement:

```text
make test
make test-live
make lint
make docs-check
make hygiene
make ci
```

Expected accepted shape/equivalent:

```make
CI_LINT_SCOPE := src/grace_control tests scripts
CI_LINT_BASELINE := .grace/ci_lint_baseline.json

test:
	@mkdir -p "$(GRACE_PLANNING_LOGS_ROOT)"
	GRACE_DB_URL=$(GRACE_DB_URL) GRACE_PLANNING_LOGS_ROOT=$(GRACE_PLANNING_LOGS_ROOT) $(PYTHON) -m pytest tests -m "not external and not live" -q

test-live:
	$(PYTHON) -m pytest tests -m "external or live" -q
	# plus accepted standalone tests/live/test_*.py scenarios when present

lint:
	$(PYTHON) scripts/ci_lint_baseline.py --baseline $(CI_LINT_BASELINE) --scope $(CI_LINT_SCOPE)

hygiene:
	$(PYTHON) scripts/ci_repo_hygiene.py

ci: test lint docs-check hygiene
```

Equivalent factoring is allowed, but semantics must remain explicit and non-duplicated.

### 2. Deterministic vs external/live test truth

`make test` must run the full deterministic supported pytest tree, not an accidental `tests/grace_control/` subset.

External/live exclusions must be explicit through registered/current pytest markers and have a separate runnable `make test-live` path. Every marker excluded from deterministic CI must be included by the live/external runner.

Do not hide deterministic failing tests under live markers merely to make CI green.

### 3. Canonical lint truth

`make lint` must own the complete supported lint scope:

```text
src/grace_control
tests
scripts
```

Both Ruff and GraceLint must run through the accepted baseline-aware gate. The baseline is debt accounting, not a whitelist of files.

Verify `.grace/ci_lint_baseline.json` is deterministic and matches the accepted current scope. Do not shrink the scope or add new allowed violations merely for this packet.

### 4. Canonical hygiene truth

`make hygiene` delegates only to `scripts/ci_repo_hygiene.py`.

Packet 08's tracked runtime/generated policy remains executable and must include the corrected DB suffix family. GitHub workflow/Makefile must not duplicate the policy.

### 5. `make ci` composes rather than reimplements

`make ci` must depend on/compose the canonical `test`, `lint`, `docs-check`, and `hygiene` targets. It must not inline a second implementation of those gates.

### 6. GitHub Actions delegates to Make

`.github/workflows/ci.yml` must invoke canonical Make targets. It may keep a supported Python matrix for tests and a single Python version for quality gates.

Requirements:

- no direct `pytest tests/grace_control/` policy;
- no separate GraceLint/Ruff scope differing from Make;
- no inline repo-hygiene implementation;
- docs freshness through `make docs-check`;
- hygiene through `make hygiene`;
- normal clean-runner install such as `pip install -e ".[dev]"` provides required tools.

### 7. No orphaned CI helpers/tests

Verify the previously obsolete changed-files lint helper/test do not reappear unless current supported workflow evidence now requires them.

Do not resurrect deleted CI scripts merely because historical docs mention them.

### 8. Final programme architecture verification

Run the current architecture guards for all completed waves. At minimum prove current equivalents of:

```text
OpenCode runtime removal
control CLI removal
Admin cross-project explicit composition
Admin Control Center dependency inversion
Admin aggregation acyclic dependency graph
lifecycle thin-router boundary
typed Admin read-model boundary
repo-hygiene boundary
CI single-source-of-truth boundary
```

A failure in one of these is a programme blocker. Do not paper over it in CI configuration.

## Required structural guard

Current preferred guard:

`tests/grace_control/architecture/test_ci_single_source_of_truth.py`

It must prove directly or equivalently:

1. Makefile defines canonical `test`, `lint`, `docs-check`, `hygiene`, `ci` and explicit live/external runner.
2. `ci` composes canonical targets.
3. lint scope is the full accepted `src/grace_control tests scripts` scope and uses the baseline-aware Ruff + GraceLint runner.
4. deterministic test target excludes only explicit external/live markers.
5. `test-live` includes every marker excluded from deterministic CI.
6. workflow invokes canonical Make targets and does not duplicate test/lint/hygiene policy.
7. hygiene policy has one executable owner.
8. obsolete changed-files lint helper/test does not return as an active dependency.

If the existing guard already proves these, do not duplicate it.

## Required verification

Run and report exact results for:

```bash
make test
make lint
make docs-check
make hygiene
make ci
```

Also run:

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture/test_ci_single_source_of_truth.py
```

Run all current Architecture Refactor V2 architecture guards discovered above in one focused command where practical.

Verify the explicit live runner is structurally sound without requiring an unavailable external environment to become green. At minimum run pytest collection for markers or the architecture guard proving deterministic/live symmetry. If the live environment is actually available, `make test-live` may be run and reported separately; lack of live external services is not permission to alter deterministic CI.

Run final scans:

```bash
rg -n 'pytest tests/grace_control/|scripts/ci_repo_hygiene.py|python scripts/grace_lint.py' .github/workflows/ci.yml || true

rg -n 'grace_changed_files_lint|grace_changed_files_' Makefile .github src tests scripts README.md AGENTS.md docs/grace || true

git ls-files | rg '(^|/)(%2Ftmp%2F|\.goldw/|\.lw3/|\.grace-live-wt/|src/gold-test/)|\.db($|-(?:shm|wal)$)' || true
```

Interpret every surviving hit; intended references inside canonical scripts/negative guards are allowed where appropriate.

Then:

```bash
python3 -m py_compile <changed-python-files-if-any>
git diff --check
```

## Final active-doc alignment

If current active docs are already aligned, do not edit them. If a factual stale statement remains in the named active docs, make the smallest correction required to state current accepted architecture and canonical CI truth.

Do not rewrite historical work packets/submissions/reviews.

## Submission protocol

If corrections are required, commit/push them and use the full 40-character implementation SHA. If current `main` already satisfies the packet, use synced `HEAD` and explicitly state `verified no-op`.

Create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_09_CI_SINGLE_SOURCE_OF_TRUTH_SUBMISSION.md`

It MUST begin exactly:

```text
WEB_ORCH_REPORT: SUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_09_CI_SINGLE_SOURCE_OF_TRUTH
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-40-character-implementation-sha>
WEB_ORCH_CHECKS: PASS
```

Then include:

- synced base SHA and initial status;
- implementation SHA or verified-no-op statement;
- exact canonical Make target semantics;
- deterministic vs external/live classification evidence;
- lint scope/baseline evidence;
- workflow delegation evidence;
- Packet 08 hygiene/DB matcher preservation evidence;
- exact CI single-source guard result;
- final architecture-guard matrix/results for Waves 1–7;
- exact `make test/lint/docs-check/hygiene/ci` results;
- active-doc changes, or `none` if already aligned;
- changed paths, or `none` for verified no-op.

Do not create/start any next packet. Wait for Architect ACCEPT/REVIEW.

## Acceptance criteria

Architect ACCEPT requires all of:

1. `make test` is the full deterministic supported CI pytest surface with only explicit external/live exclusions.
2. `make test-live` covers the excluded external/live marker surface and accepted live scenarios.
3. `make lint` uses the full accepted `src/grace_control tests scripts` scope and both Ruff + GraceLint through the baseline-aware gate.
4. `make docs-check` remains canonical docs freshness.
5. `make hygiene` remains the single executable repository-hygiene owner and includes Packet 08's corrected DB suffix policy.
6. `make ci` composes `test + lint + docs-check + hygiene` without duplicate recipes.
7. GitHub Actions delegates to canonical Make targets and does not reimplement policy inline.
8. No obsolete CI helper/test is resurrected without current supported evidence.
9. All Architecture Refactor V2 wave guards pass; no OpenCode/control-CLI/reverse-coupling/lifecycle/read-model/hygiene regression remains.
10. No API/DB/lifecycle/packet/runtime semantic drift or unrelated refactor is included.
11. No lint/size allowlist expansion or hidden deterministic-test exclusion is introduced.
12. Submission follows the exact named-file protocol with a full SHA.
13. If all criteria already hold, verified no-op is preferred over manufactured edits.
