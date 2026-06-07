# Review: `d048df4` TZ_FRONTEND_ACCEPTANCE P2

Date: 2026-06-07
Reviewer: ChatGPT
Commit reviewed: `d048df4d38f346604aee46ff314f7a712cdf93a5`

## Verdict

**REQUEST CHANGES.**

P2 is directionally correct for routing/config, but the a11y implementation is not yet a real axe-core acceptance gate. Desktop viewport and Storybook/video constraints are mostly fine. Visual threshold routing is present, but evidence validation still has an old weak fallback.

## What is OK

- `FrontendA11ySpec.required` was added to `FrontendSpec`.
- `resolve_browser_routing()` keeps a11y disabled by default and enables it only when `frontend.a11y.required=true`.
- FAST still skips browser/a11y stages.
- Default viewports remain `android` + `iphone`.
- `desktop` was added as an optional viewport in the frontend routing map.
- P2 tests explicitly check that Storybook runner and video evidence are absent.

## Blockers / major findings

### BLOCKER 1 — A11y is not actually implemented as an axe-core gate

`PlaywrightRunner.run_a11y()` only calls:

```python
return self._run_playwright("a11y")
```

Inside `_run_playwright()`, `mode == "a11y"` only changes the test file glob to ordinary `tests/e2e/**/*.spec.ts`. The command remains the same default Playwright command:

```python
npx playwright test --config ... --reporter html,json,list --project=<viewport>
```

There is no explicit axe-core runner, no axe package command, no injected axe scan, and no `a11y-report.json` generation.

Impact:

- `frontend.a11y.required=true` does not guarantee accessibility scanning.
- It only runs whatever existing Playwright specs happen to do.
- A package can pass the a11y stage without any axe checks.

Required fix:

- Either require a dedicated `verification.t2_a11y` command and execute it, or implement a real a11y runner that runs axe-core and writes `a11y-report.json`.
- The report should include violation count, severity/impact, affected nodes/selectors, viewport, and URL.

### BLOCKER 2 — A11y stage reuses `StageName.T2_BROWSER_E2E`

`_run_frontend_stages()` stores the a11y result under key `t2_browser_a11y`, but the `StageResult.name` is still:

```python
name=StageName.T2_BROWSER_E2E
```

`StageName` has no `T2_BROWSER_A11Y` value.

Impact:

- Admin UI, trace, verifier, reports, and any aggregation by `StageName` will confuse browser E2E with a11y.
- A failed a11y stage can look like a duplicate/second browser E2E stage.
- The acceptance matrix cannot reliably distinguish `T2_BROWSER_E2E` from `T2_BROWSER_A11Y`.

Required fix:

- Add `StageName.T2_BROWSER_A11Y = "T2_BROWSER_A11Y"`.
- Use it in the a11y `StageResult` for pass/fail/skipped.
- Add report validation/admin rendering tests for the new stage name.

### BLOCKER 3 — No a11y evidence kind / report validation

The P2 requirement says violations must be saved and become evidence. The implementation adds no `a11y_report` / `a11y_log` evidence kind and does not validate any `a11y-report.json` artifact.

Impact:

- The pipeline can mark a11y passed/failed based on command exit code, but evidence verifier cannot independently check that an a11y scan happened.
- There is no artifact-level proof for reviewers.

Required fix:

- Add an evidence kind, for example `a11y_report`.
- Validate that `run_dir/browser/<viewport>/a11y-report.json` exists and is parseable.
- Fail if critical/serious violations exceed threshold.
- Include a11y report paths in `EvidenceCollector`.

### MAJOR 4 — Desktop viewport exists in frontend routing map but not PlaywrightRunner viewport config

`frontend_stages._VIEWPORT_MAP` includes `desktop`, but `PlaywrightRunner._VIEWPORT_CONFIG` still only has `android` and `iphone`. `viewport_config` falls back to android for unknown names.

Impact:

- `frontend.viewports: [desktop]` can route to desktop, but runner-level viewport config may silently use android dimensions.
- If Playwright config does not define a desktop project, this can run the wrong viewport while reporting desktop.

Required fix:

- Add `desktop` to `PlaywrightRunner._VIEWPORT_CONFIG`, or remove duplicate viewport maps and use one canonical config.
- Add a runner-level test proving `PlaywrightRunner(viewport="desktop").viewport_config == {width: 1280, height: 720}`.

### MAJOR 5 — Visual evidence still has old weak fallback

`core/evidence.py` still treats an empty `*diff*.png` as pass when no `diff-report.json` exists, and on JSON parse error falls back to checking for any diff PNG.

Impact:

- This partially reintroduces the old weak visual evidence behavior even though `VisualBaselineManager` was fixed in P1.
- P2 threshold tuning should not pass on empty PNG surrogate evidence.

Required fix:

- For `visual_diff`, require parseable `diff-report.json` with `diff_pct`, or delegate to `VisualBaselineManager` result metadata.
- Remove empty-PNG pass fallback.

### MAJOR 6 — Tests are too shallow around a11y

Current a11y tests mock `subprocess.run()` stdout/returncode but do not prove axe-core was invoked or that an `a11y-report.json` artifact is produced and validated.

Required tests:

1. `frontend.a11y.required=false` → no a11y runner call.
2. `frontend.a11y.required=true` → a real a11y command/runner is invoked.
3. No violations → `a11y-report.json` exists and stage passes.
4. Critical/serious violation → stage fails and report path is included in evidence.
5. Non-critical violations → policy is explicit: warn/pass or fail depending on chosen threshold.
6. Evidence checker rejects missing/corrupt a11y report.
7. Admin/report/trace show `T2_BROWSER_A11Y` separately from `T2_BROWSER_E2E`.

## Non-blocking notes

- There is a typo in test name: `test_a11y_enabled_norinal_runs` should be `normal`.
- Module header in `playwright_runner.py` still says Playwright missing “skips (passed=True)”, but current behavior is fail. Update docs/comments.
- CI/workflow status was not visible through connector.

## Acceptance after fixes

Accept P2 when:

- a11y is a real axe-core/report-backed gate;
- a11y has its own stage name and evidence kind;
- desktop viewport is canonical and runner-level tested;
- visual evidence no longer has weak fallback;
- targeted tests cover all new gates;
- Storybook/video remain absent.
