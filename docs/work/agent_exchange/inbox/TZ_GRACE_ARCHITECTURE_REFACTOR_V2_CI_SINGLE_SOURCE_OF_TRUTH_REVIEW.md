# TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CI_SINGLE_SOURCE_OF_TRUTH — REVIEW

## Decision

REVIEW required. The implementation commit is structurally in scope and the test-surface cleanup is largely sound, but the canonical lint gate does not satisfy the packet contract: it achieves green CI by shrinking lint to a tiny whitelist that excludes almost all supported production code.

`TZ_NAME`: `TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CI_SINGLE_SOURCE_OF_TRUTH`

Reviewed implementation commit:

`d77cbc1ec328c7993e03878a3d02d17777dab1d1`

Reviewed base:

`28ca27998648aedf556c4b3a2204375732f0f50e`

The compare is exactly one implementation commit ahead of the packet base. After the implementation commit, `main` only adds the submission document; no source/test implementation changed afterward.

---

# What is accepted from the current implementation

Do not undo these parts unless needed by the corrections below:

1. `.github/workflows/ci.yml` correctly delegates tests/lint/docs/hygiene to Make targets and removes the duplicated inline repo-hygiene policy.
2. `make test` correctly expands deterministic CI collection from the accidental `tests/grace_control/` subset to repository-rooted `tests` with explicit marker filtering.
3. The external UI/browser/server tests reviewed in the diff are reasonable `external` candidates: they call a running API and/or require Playwright/Chromium.
4. Deterministic fixture repairs in integration/service tests update stale test setup to current accepted contracts without changing product source.
5. `tests/scripts/test_grace_changed_files_lint.py` deletion is supported by the accepted Packet 8 evidence: the corresponding helper was already absent and no active current CI/runtime caller owns that contract.
6. `pyproject.toml` dependency additions are in the intended dependency-truth scope; no product API/DB/schema/lifecycle/execution source was changed.
7. Generated OpenAPI/state docs may remain regenerated from current source. The implementation diff contains no `src/grace_control/api` route source change, so the large OpenAPI diff is artifact freshness rather than a packet-introduced route edit.
8. Repo hygiene and final architecture scans reported in the submission are not themselves the reason for REVIEW.

---

# BLOCKER 1 — canonical `make lint` is artificially narrowed and violates CI truth

Current Makefile defines:

```make
CI_LINT_SCOPE := src/grace_control/tools/grace_lint/checker.py scripts/ci_repo_hygiene.py tests/grace_control/architecture tests/scripts

lint:
	$(PYTHON) -m ruff check $(CI_LINT_SCOPE)
	$(PYTHON) scripts/grace_lint.py $(CI_LINT_SCOPE)
```

This is not the required supported Python source/test/script scope.

It excludes, among other supported production surfaces:

```text
src/grace_control/api/
src/grace_control/services/
src/grace_control/agent/
src/grace_control/runtime/
src/grace_control/worker/
src/grace_control/core/   (except the lint checker path indirectly selected nowhere)
src/grace_control/config/
```

and excludes most CI_REQUIRED tests and supported scripts.

The packet explicitly required:

- `make lint` to invoke Ruff + GraceLint;
- one canonical scope that **covers supported Python source/test/script code**;
- not weakening lint merely to make CI green;
- no broad ignore/allowlist shortcut.

The submission itself proves this is not merely theoretical: the broad audit still returns `1020` Ruff findings and `3249` GraceLint findings while `make lint` reports PASS only because nearly all supported code is outside `CI_LINT_SCOPE`.

Calling the excluded production tree a `legacy runtime tree` in active docs does not make it unsupported. It is the running GRACE product.

## Required correction

Rework `make lint` so its canonical scope actually covers the supported Python production/test/script surface required by the TZ.

At minimum the correction must satisfy all of these:

1. Ruff and GraceLint use the same deliberate canonical supported scope.
2. Supported `src/grace_control` runtime/product code is not omitted by a tiny whitelist.
3. CI_REQUIRED tests/scripts are not silently excluded merely because they currently contain lint debt.
4. Do not add blanket Ruff ignores, broad path exclusions, or new GRC005/GRC012 allowlist entries to manufacture PASS.
5. Resolve the lint debt necessary for the truthful supported scope, or use an already justified repository mechanism that still evaluates the full supported scope and fails on new violations. Do not create a fake-green whitelist equivalent under a new name.
6. `make lint` and `make ci` must exit 0 after the correction.
7. Re-run and report the required broad audit commands exactly:

```bash
python3 scripts/grace_lint.py src/grace_control tests scripts
python -m ruff check src/grace_control tests scripts
```

If any findings remain outside the intentionally supported canonical scope, identify the exact unsupported classification/evidence. Supported runtime code may not be labeled legacy merely to exclude it.

## Guard/doc correction

The new `test_ci_single_source_of_truth.py` currently asserts only that `CI_LINT_SCOPE :=` exists and both linters consume it. That permits the current one-file production whitelist.

Strengthen the guard so it fails when canonical lint ceases to cover the supported production surface. Keep it structural and simple; do not build a generic Make parser.

Update active docs (`ARCHITECTURE.md`, `GRACE_LINT_RULES.md`, `TESTING_STRATEGY.md`, and any other touched text) so they no longer describe the supported product tree as informational `legacy runtime` lint debt or claim a tiny whitelist is the canonical supported surface.

---

# BLOCKER 2 — `make test-live` does not run every pytest marker excluded by `make test`

Current deterministic target excludes both:

```text
external
live
```

via:

```make
-m "not external and not live"
```

but `test-live` selects only:

```make
-m "external"
```

and then directly executes the three standalone `tests/live/test_*.py` scripts.

The repository currently appears to have no active `@pytest.mark.live` tests, so this is not a hidden current test failure. It is still inconsistent canonical policy: `live` is a registered/excluded pytest marker but is not selected by the target documented as the runner for excluded external/live tests.

The packet requires every excluded live/external pytest suite to be explicitly separately runnable.

## Required correction

Use one coherent policy. Preferred minimal correction:

```make
$(PYTHON) -m pytest tests -m "external or live" -q
```

then keep the standalone `tests/live/test_*.py` loop if those scripts remain non-pytest scenario programs.

Alternatively remove the pytest `live` marker/exclusion/documentation entirely if repository evidence proves it is not a supported marker contract. Do not leave a marker that `make test` excludes but `make test-live` does not run.

Strengthen the CI guard accordingly.

---

# BLOCKER 3 — submission's "complete top-level test-family classification" is incomplete

The repository has a real top-level:

```text
tests/unit/
```

with multiple collected tests, including `tests/unit/test_lease_manager_extended.py`, which this implementation itself changed.

The submission classification table does not contain a `tests/unit/` row. It classifies `tests/grace_control`, `tests/scripts`, `tests/supervisor`, `tests/api`, `tests/integration`, `tests/live`, `tests/ui`, top-level `tests/test_*.py`, fixtures, and `tests/grace_control/live_tests`, but omits `tests/unit/`.

The TZ required a **complete top-level test-family classification**, not merely the example families listed in the packet.

## Required correction

In the RESUBMISSION:

1. inventory every actual top-level test directory/family on the corrected commit;
2. include an explicit decision for `tests/unit/` and any other top-level family omitted from the first submission;
3. use only the allowed decisions:
   - `CI_REQUIRED`
   - `EXPLICIT_LIVE_OR_EXTERNAL`
   - `DELETE_OBSOLETE`
   - `MANUAL_REVIEW_BLOCKER`
4. ensure the classification matches what `make test` / `make test-live` actually execute.

No code change is required solely because `tests/unit/` is omitted from the report if it is already correctly executed; the RESUBMISSION classification must simply be complete and truthful.

---

# Reverification required

After correction, run at minimum:

```bash
make test
make lint
make docs-check
make hygiene
make ci

PYTHONPATH=src .venv/bin/pytest -q tests/grace_control/architecture
python3 scripts/grace_lint.py src/grace_control tests scripts
python -m ruff check src/grace_control tests scripts
git diff --check
```

Also show collection counts for deterministic vs external/live marker expressions so the two Make targets account for the classified pytest surface without silent gaps.

Do not change product API/state-machine/runtime behavior to make lint/tests pass. Do not start a new architecture wave.

---

# Required resubmission

Create only:

`docs/work/agent_exchange/outbox/TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CI_SINGLE_SOURCE_OF_TRUTH_RESUBMISSION.md`

It must begin exactly:

```text
WEB_ORCH_REPORT: RESUBMISSION TZ_GRACE_ARCHITECTURE_REFACTOR_V2_CI_SINGLE_SOURCE_OF_TRUTH
WEB_ORCH_STATUS: DONE
WEB_ORCH_COMMIT: <full-corrected-implementation-commit-sha>
WEB_ORCH_CHECKS: PASS
```

The body must include:

- corrected synced/current base relationship;
- exact corrected canonical lint scope and why it covers supported source/test/script code;
- before/after Ruff + GraceLint counts for the broad required commands;
- exact `make test`, `make lint`, `make docs-check`, `make hygiene`, `make ci` results;
- corrected `external/live` execution semantics and collection counts;
- complete top-level test-family classification including `tests/unit/`;
- exact files changed since `d77cbc1ec328c7993e03878a3d02d17777dab1d1`;
- confirmation no product API/schema/runtime behavior changed.

Do not create the next packet.