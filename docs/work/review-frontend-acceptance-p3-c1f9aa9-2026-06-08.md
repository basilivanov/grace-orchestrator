# Review: `c1f9aa9` TZ_FRONTEND_ACCEPTANCE P3 stabilization

Date: 2026-06-08
Reviewer: ChatGPT
Commit reviewed: `c1f9aa9e76ed78eba8251b3841f03fa11a55379b`

## Verdict

**REQUEST CHANGES.**

The commit is directionally correct: it adds a manifest service, fail-closed tests, and replaces broad `pgrep -f` cleanup with scoped `/proc`-based cleanup. However, the main P3 requirement was end-to-end stabilization. The new artifact manifest is currently implemented as a standalone helper and unit-tested directly, but it is not wired into the real frontend acceptance execution path.

## What is good

- New `artifact_manifest.py` introduces a standard `artifacts-manifest.json` format.
- Manifest validation detects missing files and size mismatches.
- Artifact classification covers screenshot, trace, console log, network log, visual diff, a11y report, and DOM snapshot.
- Added fail-closed tests for missing Playwright, missing visual diff report, missing a11y command, missing a11y report, and backend-only compatibility.
- Cleanup moved away from broad `pgrep -f` to `/proc` cwd-based process scoping.
- Documentation status was updated to show P0/P1/P2 implemented and P3 in progress.

## Blockers / major findings

### BLOCKER 1 — Artifact manifest is not integrated into real frontend runs

The commit adds `write_artifact_manifest()` and tests it directly, but the diff does not wire it into:

- `PlaywrightRunner`;
- `_run_frontend_stages()`;
- `AcceptancePipeline.run()`;
- `EvidenceChecker` / `_check_evidence_kind()`;
- admin aggregation;
- trace service.

Impact:

- A real frontend acceptance run will not automatically create `run_dir/browser/artifacts-manifest.json`.
- Manifest tests can pass while production runs produce no manifest.
- The manifest is not yet the “single source of truth” for browser artifacts.

Required fix:

- Call `write_artifact_manifest(...)` after browser/a11y/visual stages complete for a run.
- Use actual `packet_id` and `run_id`, not placeholder values.
- Ensure manifest generation happens even on frontend stage failure, as long as `run_dir/browser` exists.
- Add an integration test through `_run_frontend_stages()` or `AcceptancePipeline.run()` proving the manifest exists after a real frontend stage.

### BLOCKER 2 — Manifest validation is not part of evidence checking or acceptance verdict

`validate_artifact_manifest()` exists, but the reviewed delta does not make missing/invalid manifests affect acceptance.

Impact:

- A broken manifest does not fail evidence validation.
- `expected_evidence` cannot require manifest consistency.
- Missing screenshot/report files can still be caught by direct evidence kinds, but not by the new P3 manifest contract.

Required fix:

Choose one:

1. Add an evidence kind, for example `artifact_manifest`, that calls `validate_artifact_manifest(run_dir)` and fails on any error.
2. Or automatically call `validate_artifact_manifest()` inside frontend acceptance before final report verdict.

Add tests:

- manifest missing → evidence fails;
- manifest has orphan entry → evidence fails;
- file exists but size mismatch → evidence fails;
- unlisted file in browser dir → evidence fails if this is intended policy.

### BLOCKER 3 — Manifest is not visible in admin/trace/report

P3 checklist required admin/trace/report display. The commit adds the manifest service but does not appear to expose manifest path or validation status through existing reporting/UI layers.

Impact:

- Operator still has to dig through filesystem to find frontend artifacts.
- Trace does not show the unified artifact inventory.
- P3 “operationalization” is only partial.

Required fix:

- Include manifest path in `StageResult` evidence/artifact list or report metadata.
- Surface it in admin/trace wherever frontend artifacts are listed.
- Add tests that aggregation/report contains `artifacts-manifest.json` after frontend run.

### MAJOR 4 — `browser_dir` in manifest is absolute path

Manifest stores:

```json
"browser_dir": "/absolute/path/to/run/browser"
```

P3 checklist asked for relative/safe paths where possible.

Impact:

- Leaks host filesystem paths into artifacts/prompts/admin output.
- Reduces portability if artifacts are copied elsewhere.

Recommended fix:

- Store `browser_dir` as relative path (`browser`) or omit it and resolve relative to manifest location.
- If absolute path is needed internally, do not expose it in user-facing evidence.

### MAJOR 5 — Artifact classification has ordering bug for `diff-report.json`

`_classify_artifact()` checks generic network JSON before `diff-report.json`:

```python
if "network" in name and (name.endswith(".har") or name.endswith(".json")):
    return "network_log"
if "diff" in name and name.endswith(".png"):
    return "visual_diff"
if "diff-report" in name and name.endswith(".json"):
    return "visual_diff"
```

This is probably fine for `diff-report.json` because it does not contain `network`, but similar report names could be misclassified. More importantly, `a11y-report.json` is identified by name only; metadata such as `critical_count` is not extracted.

Recommended fix:

- Explicitly classify known report filenames first:
  - `diff-report.json` → `visual_diff` with `diff_pct`, `max_diff_pct` metadata if available;
  - `a11y-report.json` → `a11y_report` with `critical_count`, `violations_count` metadata.
- Then apply generic extension/name heuristics.

### MAJOR 6 — Cleanup scoping may miss real worktrees and has no test evidence in the reviewed snippet

The cleanup now kills processes only when cwd contains `.grace` or `grace-live-wt`.

This is safer than broad `pgrep -f`, but audit should verify real worktree paths. Earlier GRACE worktrees commonly look like `.grace/worktrees/...`, so this may be OK, but it is still heuristic.

Potential issues:

- If dev-server cwd is the target repo root instead of `.grace/worktrees/...`, cleanup will not kill it.
- If ngrok is launched from a different cwd, cleanup will not kill it.
- The comment mentions “GRACE worker environment marker”, but code only checks cwd, not env.
- Unused `import re as _re` should be removed.

Required tests:

- process with cwd inside `.grace/worktrees` is selected;
- process with cwd outside project is not selected;
- ngrok cwd used by `TelegramBridgeService` is actually covered;
- no broad kill of unrelated node/ngrok processes.

### MAJOR 7 — P3 tests are mostly service-level, not full pipeline-level

The added tests cover helper behavior well, but P3 explicitly required end-to-end proof:

`packet spec → contract → routing → runner → artifacts → manifest/evidence → report/admin/trace`

Required missing tests:

- `_run_frontend_stages()` or `AcceptancePipeline.run()` creates manifest after a mocked frontend run;
- manifest validation failure makes evidence/report fail;
- report/admin/trace contains manifest path;
- command reaches subprocess and resulting artifact appears in manifest.

## Suggested fix order

1. Wire `write_artifact_manifest()` into the real frontend run path.
2. Add `artifact_manifest` evidence validation or automatic manifest validation in acceptance.
3. Surface manifest path/status in report/admin/trace.
4. Extract metadata from `diff-report.json` and `a11y-report.json` into manifest entries.
5. Add pipeline-level regression tests.
6. Add cleanup-scoping tests with mocked `/proc` or factored process scanner.

## Acceptance after fixes

Accept P3 when:

- every frontend run writes `run_dir/browser/artifacts-manifest.json`;
- invalid/missing manifest can fail evidence/acceptance;
- manifest path is visible in report/admin/trace;
- manifest entries include useful metadata for visual/a11y reports;
- cleanup scoping is tested against real expected worktree/ngrok cwd behavior;
- backend-only packets remain unchanged.
