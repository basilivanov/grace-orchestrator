# Pre-audit: TZ_FRONTEND_ACCEPTANCE P1

Date: 2026-06-07
Scope: preparation checklist for upcoming P1 audit after accepted P0 frontend acceptance work.

## P1 scope from TZ

P1 covers quality/reliability around browser acceptance:

- `VisualBaselineManager`.
- `MultimodalEvidencePack`.
- Evidence verifier multimodal prompt and fallback.
- `multimodal: true` on verifier profiles.
- `ScreenshotRef` / `DomSnapshotRef` contracts.
- Cleanup dev-server / ngrok.
- Frontend profiles in `agent_profiles.yaml`.
- `TelegramBridgeService` real mode.
- `npx playwright install chromium` through process supervisor.
- Documentation updates.

## Current static observations before audit

### Already present / partially present

- `VisualBaselineManager` exists, but fallback pixel comparison is a file-size ratio surrogate, not a real pixelmatch/Pillow comparison.
- `TelegramBridgeService` exists and starts ngrok plus generates signed initData.
- `evidence_verifier.py` has a multimodal path and `_build_multimodal_context()` with `<image>` tags.
- `supervisor_cleanup_service.py` has frontend process cleanup for node/vite/next/ngrok patterns.

### Likely gaps to verify

1. `MultimodalEvidencePack` file appears missing as `src/grace_control/core/multimodal_evidence.py`.
2. `ScreenshotRef` / `DomSnapshotRef` dataclasses do not appear in `core/contracts.py`.
3. `agent_profiles.yaml` visible verifier profile does not clearly show `multimodal: true` in the fetched section.
4. `process_supervisor.py` appears generic and does not visibly include an idempotent `playwright_install` action.
5. `supervisor_cleanup_service.py` kills processes by broad `pgrep -f` patterns, which may be unsafe on shared servers unless scoped to worktree/run metadata.
6. `TelegramBridgeService` signs initData, but audit must verify Telegram HMAC formula correctness, token handling, ngrok cleanup on every failure path, and no leak of bot token/initData in logs.
7. `EvidenceVerifier` detects multimodal using `executor.get("multimodal", False)`, but if profile metadata nests this flag under `metadata`, it may be missed.
8. Mock injection in P0 writes `telegram-mock.js`; audit should verify whether actual Playwright `addInitScript()` happens before app bundle, not merely that a file exists.

## P1 audit checklist

### 1. VisualBaselineManager

Accept only if:

- `compare()` uses real diff data from Playwright report or a deterministic image diff implementation.
- Missing baseline behavior is explicit and documented: pass only on approved first-run/update-baseline mode, not silently for STRICT unless intended.
- `diff_pct`, `baseline_path`, `current_path`, and `diff_path` are persisted as evidence.
- Corrupt/missing diff reports fail closed when visual is required.
- Tests cover within threshold, over threshold, missing baseline, corrupt JSON, multiple viewports, and multiple screenshots.

Potential blocker:

- fallback based on file-size ratio should not be accepted as real visual regression.

### 2. Multimodal evidence contracts

Accept only if:

- `ScreenshotRef`, `DomSnapshotRef`, and/or `MultimodalEvidencePack` exist as first-class contracts.
- They include viewport, URL/page, path, artifact kind, optional diff percent, and failure context.
- Paths are relative/safe for prompts and do not expose host secrets.
- Evidence pack is built from actual run artifacts in `run_dir/browser/**`, not inferred from expected evidence only.

Potential blocker:

- visual evidence exists only as free-form prompt strings and cannot be validated/tested structurally.

### 3. EvidenceVerifier multimodal prompt

Accept only if:

- Multimodal executor detection works with the real `agent_profiles.yaml` shape.
- If executor is multimodal, screenshot references are included in the format actually supported by the selected backend.
- If executor is not multimodal, text fallback includes screenshot paths, viewport, URL, console errors, and diff_pct.
- Missing or invalid visual artifacts cannot still produce PASS.
- Tests cover multimodal true, multimodal false fallback, no artifacts, console errors, and visual diff summary.

Potential blocker:

- `executor.get("multimodal")` while config stores the flag under `metadata.multimodal`.

### 4. TelegramBridgeService real mode

Accept only if:

- Real mode is only allowed for STRICT or explicitly controlled profiles.
- Bot token is read from env only and never logged.
- initData HMAC matches Telegram WebApp validation rules exactly.
- ngrok process is killed on success, failure, timeout, and exceptions.
- base_url is actually switched to public ngrok URL for Playwright.
- real-mode failures fail closed or downgrade only when policy allows it.
- Tests cover missing token, ngrok missing, ngrok timeout, API tunnel discovery, HMAC verification, and cleanup.

Potential blocker:

- bridge service exists but is not integrated into `PlaywrightRunner` / routing path.

### 5. Process supervisor and cleanup

Accept only if:

- frontend dev-server runs via a reusable supervisor abstraction or equivalent process-group tracking.
- cleanup is scoped to processes started by this run, not broad global patterns.
- ngrok cleanup is tied to bridge instance/run id.
- `npx playwright install chromium` is idempotent and can be skipped when already installed.
- Tests verify no orphan dev-server/ngrok remains after crash/timeout.

Potential blocker:

- broad `pgrep -f node vite/next/ngrok` killing unrelated user processes.

### 6. Agent profiles

Accept only if:

- `frontend_e2e`, `frontend_visual`, and optionally `frontend_a11y` profiles exist in the config shape actually consumed by executor selection.
- verifier premium profile has a multimodal flag in the exact location the code reads.
- cheap verifier fallback is intentionally non-multimodal and tested.

Potential blocker:

- config includes new profile fields but executor selector drops them before runtime.

### 7. Documentation

Accept only if docs are updated:

- `docs/SUPERVISOR.md` — frontend execution lifecycle.
- `docs/grace/EXECUTION_BACKENDS.md` — browser E2E and visual regression.
- `docs/grace/CONFIGURATION.md` — FrontendSpec schema.
- `docs/TZ_FRONTEND_ACCEPTANCE.md` status updated from pending if P1 is implemented.

## Suggested tests required for P1 accept

Minimum test set:

1. `test_visual_baseline_manager_real_report_thresholds`.
2. `test_visual_baseline_manager_missing_baseline_policy`.
3. `test_multimodal_evidence_pack_collects_run_dir_artifacts`.
4. `test_evidence_verifier_multimodal_prompt_includes_image_refs`.
5. `test_evidence_verifier_text_fallback_includes_visual_summary`.
6. `test_executor_multimodal_flag_detected_from_real_agent_profile_shape`.
7. `test_telegram_bridge_missing_token_fails_closed`.
8. `test_telegram_bridge_hmac_matches_telegram_spec_vector`.
9. `test_telegram_bridge_ngrok_cleanup_on_failure`.
10. `test_real_mode_updates_playwright_base_url_to_ngrok_url`.
11. `test_process_supervisor_playwright_install_idempotent`.
12. `test_cleanup_does_not_kill_unrelated_node_processes`.
13. `test_frontend_profiles_survive_config_parse_and_executor_selection`.

## Final pre-audit posture

P1 should be audited as an integration-quality layer, not as file-presence work. The critical question is whether real visual/Telegram/multimodal evidence is part of the acceptance path end-to-end:

`packet spec → routing → runner/bridge/supervisor → artifacts → evidence pack → verifier prompt → admin/trace/report`.
