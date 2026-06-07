# Review: `7e8fd13` TZ_FRONTEND_ACCEPTANCE P0

Date: 2026-06-07
Reviewer: ChatGPT
Commit reviewed: `7e8fd1378ec6fcc4b1e18e44697142bda82adcad`
Spec: `docs/TZ_FRONTEND_ACCEPTANCE.md`

## Verdict

**REQUEST CHANGES.**

The implementation has the right direction and introduces the expected high-level pieces, but the P0 acceptance is not yet reliable enough to accept. The biggest issues are:

1. new frontend stages are emitted as `SKIPPED` without `skipped_reason`, which violates the existing stage contract;
2. new evidence kinds are only declared/commented, but `core/evidence.py` was not changed, so `screenshot`, `visual_diff`, `console_log`, etc. are not actually validated;
3. no dedicated frontend acceptance tests were added;
4. `verification.t2_browser` / `verification.t3_visual` from the TZ example are not propagated through `build_packet_contract()`;
5. Playwright/browser execution is not yet represented as command evidence, so reports lose command/stdout/stderr details.

## What is implemented well

- `StageName` was extended with `T2_BROWSER_E2E` and `T3_VISUAL_REGRESSION`.
- `build_packet_contract()` now passes `spec.frontend` into `packet.metadata["frontend"]`, so the main previously predicted hidden bug is partially addressed.
- `AcceptancePipeline.run()` calls frontend stages after T2 and includes those stages in final report/evidence checking.
- `frontend_stages.py`, `playwright_runner.py`, and `telegram_webapp_mock.py` were added.
- Routing edge cases are at least represented in the commit: no frontend → skip, FAST → skip, NORMAL+real → mock downgrade, STRICT+real allowed.

## Blockers / Major findings

### BLOCKER 1 — `SKIPPED` frontend stages do not set `skipped_reason`

Existing `validate_stage_result()` requires every skipped stage to have `skipped_reason`.

The new `_run_frontend_stages()` creates skipped stages like:

```python
StageResult(
    name=StageName.T2_BROWSER_E2E,
    status=StageStatus.SKIPPED,
    summary=f"T2_BROWSER skipped: {routing.reason}",
    commands=[],
)
```

and similarly for T3 visual.

Impact:

- Any caller that validates `AcceptanceReport` will consider otherwise successful backend-only packets invalid.
- This breaks the “frontend.enabled=false should not change old backend-only pipeline” acceptance gate.

Fix:

- Add `skipped_reason=routing.reason` to both skipped frontend stage results.
- Add tests:
  - `frontend.enabled=false` final report validates cleanly;
  - `FAST + frontend.enabled=true` final report validates cleanly.

### BLOCKER 2 — New evidence kinds are not implemented in `core/evidence.py`

The commit changes `EvidenceRequirement.kind` comment to include:

- `screenshot`
- `dom_snapshot`
- `console_log`
- `network_log`
- `visual_diff`

But the diff does **not** include `src/grace_control/core/evidence.py`. The TZ explicitly requires extending `_check_evidence_kind()` / equivalent handlers.

Impact:

- `expected_evidence` for browser/visual packages is not actually enforceable.
- A packet can claim frontend acceptance while screenshots, HAR, console logs, or visual diffs are missing or invalid.
- P0 requirement “visual/UX evidence is checkable” is not met.

Fix:

- Extend evidence checker with handlers:
  - `screenshot`: glob exists, non-empty PNG;
  - `dom_snapshot`: file exists and/or selector/role found;
  - `console_log`: fail if errors present unless explicitly allowed;
  - `network_log`: HAR/log contains expected URL pattern;
  - `visual_diff`: parse diff result and compare to `max_diff_pct`.
- Add tests for each new kind.

### BLOCKER 3 — `verification.t2_browser` / `verification.t3_visual` are not propagated

The TZ example specifies:

```json
"verification": {
  "t2_browser": [["npx", "playwright", "test", "tests/e2e/login.spec.ts"]],
  "t3_visual":  [["npx", "playwright", "test", "tests/e2e/login.visual.spec.ts"]]
}
```

The current contract still only propagates `t0`, `t1`, and `t2`; the commit only adds `metadata.frontend`.

Impact:

- Architect-provided browser/visual commands are silently ignored.
- The runner likely falls back to generic/default Playwright behavior.
- This is exactly the class of silent green false-positive we wanted to avoid.

Fix:

- Add `t2_browser` and `t3_visual` to `ExecutionPacketContract.verification` parsing.
- Pass those commands into frontend stages / `PlaywrightRunner`.
- Add a test proving a packet with custom `verification.t2_browser` causes that exact command to run.

### MAJOR 4 — Browser/visual stages lose command evidence

`_run_frontend_stages()` converts `BrowserStageResult` into `StageResult` with `commands=[]`.

Impact:

- Acceptance report does not show the actual `npx playwright ...` command.
- `EvidenceCollector.collect_from_stage()` cannot collect stdout/stderr command evidence for browser stages if it relies on `StageResult.commands`.
- Admin UI/debugging will show “failed” but not the underlying command, exit code, stdout/stderr paths.

Fix:

- `BrowserStageResult` should include one or more `CommandResult`s or the runner should return full `StageResult` directly.
- Include command, cwd, exit_code, stdout_path, stderr_path, duration, trace path.

### MAJOR 5 — No dedicated frontend acceptance tests in the delta

The compare only shows one test file changed: `tests/grace_control/services/test_session_resume_followup.py`. No dedicated `test_frontend_stages.py`, `test_playwright_runner.py`, `test_telegram_webapp_mock.py`, or `test_acceptance_pipeline_frontend.py` was added.

Impact:

- Routing table is not protected by table-driven tests.
- Old backend-only pipeline compatibility is not protected.
- Evidence-kind enforcement is not tested.
- Dev-server cleanup on failure/timeout is not tested.

Required tests before acceptance:

1. `resolve_browser_routing()` table:
   - no frontend → both skip;
   - FAST + enabled → both skip;
   - NORMAL + mock → e2e runs, visual according to `visual.required`;
   - NORMAL + real → downgrade mock + warning;
   - STRICT + real → allowed.
2. `AcceptancePipeline`:
   - backend-only report remains accepted and validates;
   - frontend enabled + e2e failure returns REWORK;
   - frontend enabled + visual failure returns REWORK/BLOCKED as appropriate.
3. `Evidence`:
   - all five new kinds pass/fail correctly.
4. `PlaywrightRunner`:
   - dev server is killed in `finally` on success, failure, and timeout.
5. `TelegramWebAppMock`:
   - script includes `window.Telegram.WebApp` before app bundle execution.

### MAJOR 6 — CI status is absent

The commit has no GitHub combined statuses and no workflow runs visible from the connector.

Impact:

- The claimed implementation has not been independently confirmed by CI.
- Given the pipeline-contract changes, lack of CI is a significant risk.

Fix:

- Run at minimum:
  - `pytest tests/grace_control/core/test_acceptance* tests/grace_control/core/test_frontend* tests/grace_control/services/test_playwright* -q`
  - full existing suite or the known 696-pass baseline.

## Non-blocking but important design notes

### 1. `FrontendSpec` added to `project_config.py` but not clearly used as validation

Adding Pydantic models is good, but routing appears to receive raw `dict` from `packet.metadata["frontend"]`. Ensure invalid frontend specs fail closed in a visible way, not silently “browser disabled”.

### 2. Visual regression threshold must be deterministic

Default `0.001` is strict. Runner should freeze:

- viewport;
- device scale factor;
- locale/timezone;
- animation/reduced-motion;
- font loading.

Otherwise visual gates will be flaky.

### 3. Real Telegram/ngrok should stay non-default

STRICT+real is allowed by the routing model, but should remain opt-in. Mock mode should be the reliable P0 gate; real Telegram is better as P1/manual smoke unless CI environment is fully controlled.

## Suggested fix order

1. Add `skipped_reason` to frontend skipped stages.
2. Implement new evidence kinds in `core/evidence.py`.
3. Propagate `verification.t2_browser` and `verification.t3_visual` through the packet contract.
4. Return/use `CommandResult` for browser/visual stages.
5. Add targeted frontend tests.
6. Run baseline tests and record evidence.

## Acceptance bar

Accept when:

- backend-only packets still produce a valid report with no frontend side effects;
- frontend routing is table-tested;
- custom browser/visual commands from packet spec are honored;
- failed Playwright/visual stages fail the acceptance report with useful stdout/stderr/trace paths;
- new evidence kinds are actually validated;
- dev-server cleanup is guaranteed on all exit paths;
- tests prove the above.
