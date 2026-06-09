# TZ: Admin UI for Dev Replay / Checkpoints

Status: draft for coder implementation  
Scope: development-only admin UI improvement  
Depends on: `docs/work/tz-dev-run-replay-checkpoints.md`

## 1. Problem

The Dev Run Replay / Checkpoints API now exists and allows developers to rerun failed stages without restarting the full GRACE loop.

However, using it through `curl` is still too slow for day-to-day debugging. The operator needs visible buttons in the admin UI for the most common actions:

```text
Replay T0
Replay T1
Replay T2
Replay full acceptance
Replay verifier
Replay reviewer
```

The goal is to make real-loop debugging fast from the UI: open a failed packet/run, press the relevant replay button, inspect result, repeat.

## 2. Goal

Add dev-only UI controls in the existing admin/dashboard surface so a developer can run replay actions from a failed `PacketRun` detail view without using curl.

Required outcome:

- A failed packet/run page shows replay buttons when dev tools are enabled.
- Buttons call the existing `/api/dev/runs/{run_id}/...` endpoints.
- UI displays replay result summary, status, blocking issues, and replay artifact path.
- Replay actions do not mutate packet state.
- Replay UI is hidden or disabled when dev tools are disabled.

## 3. Non-goals

Do not implement new replay backend logic in the frontend.

Do not add new production controls.

Do not add automatic retry/merge/accept from the UI.

Do not make replay buttons available when `GRACE_DEV_TOOLS_ENABLED=false`.

Do not call coder, architect, or context builder from any replay UI action.

Do not introduce React or a heavy frontend framework unless the existing project already uses it for this screen.

## 4. UX requirements

### 4.1 Placement

Add replay controls to the run detail area, preferably near the existing packet trace/run result panel.

The UI should be visible only when all conditions are true:

```text
run_id is known
current run has dev_replay metadata or is otherwise replayable
dev tools are enabled
```

If dev tools are disabled, either:

- hide the entire replay block; or
- show a small disabled note: `Dev replay tools disabled`.

Prefer hiding for normal production safety.

### 4.2 Buttons

Required buttons:

```text
Replay T0
Replay T1
Replay T2
Replay Full Acceptance
Replay Verifier
Replay Reviewer
```

Optional/reserved buttons:

```text
Replay Browser E2E
Replay Visual
```

If browser/visual replay is not stable enough, show them only when API reports support, or omit them for MVP.

### 4.3 Button states

While request is running:

- disable all replay buttons for the same run;
- show loading state on the clicked button;
- do not block the whole admin UI.

On success:

- show stage/status summary;
- show blocking issues if any;
- show replay artifact path;
- append result to a local `Replay History` panel if possible.

On failure:

- show explicit error code/message;
- for `WORKTREE_MISSING`, show `patch_path` when present;
- do not hide the failed result.

### 4.4 Replay History panel

Add a compact panel:

```text
Replay History
- 14:03 Replay T2: failed — 1 command failed
- 14:06 Replay T2: passed — T2 passed: 1 command ok
- 14:07 Verifier: PASS — all checks passed
```

This can be loaded from `PacketRun.result_json.dev_replays[]` if exposed by the trace/run endpoint. If not exposed yet, use the response from the current UI session and leave persisted history for a follow-up.

## 5. API contracts to use

Existing endpoints from previous TZ:

```http
POST /api/dev/runs/{run_id}/replay-acceptance
POST /api/dev/runs/{run_id}/rerun-verifier
POST /api/dev/runs/{run_id}/rerun-reviewer
```

### 5.1 Replay acceptance request

```json
{
  "stage": "t0"
}
```

Allowed stages for UI MVP:

```text
t0
t1
t2
full_acceptance
```

### 5.2 Replay verifier request

```json
{}
```

### 5.3 Replay reviewer request

```json
{}
```

## 6. Frontend behavior mapping

Button mapping:

| Button | Endpoint | Body |
| --- | --- | --- |
| Replay T0 | `/api/dev/runs/{run_id}/replay-acceptance` | `{ "stage": "t0" }` |
| Replay T1 | `/api/dev/runs/{run_id}/replay-acceptance` | `{ "stage": "t1" }` |
| Replay T2 | `/api/dev/runs/{run_id}/replay-acceptance` | `{ "stage": "t2" }` |
| Replay Full Acceptance | `/api/dev/runs/{run_id}/replay-acceptance` | `{ "stage": "full_acceptance" }` |
| Replay Verifier | `/api/dev/runs/{run_id}/rerun-verifier` | `{}` |
| Replay Reviewer | `/api/dev/runs/{run_id}/rerun-reviewer` | `{}` |

## 7. Backend support if needed

If the current UI cannot know whether dev tools are enabled, add a small read-only endpoint or include a flag in diagnostics/state.

Preferred minimal endpoint:

```http
GET /api/dev/status
```

Response:

```json
{
  "data": {
    "enabled": true,
    "keep_failed_worktrees": true
  },
  "timestamp": "..."
}
```

Rules:

- When dev tools are disabled, this endpoint may return 404 if the previous TZ established 404 for disabled dev surface.
- UI can treat 404 as `dev replay disabled`.
- Do not expose secrets, filesystem roots beyond already exposed replay metadata, or env values.

If adding this endpoint is unnecessary because the run detail endpoint already exposes enough information, skip it.

## 8. Files to inspect

Coder must inspect the current UI structure before changing files.

Likely areas:

```text
src/grace_control/api/routers/*
src/grace_control/api/app_factory.py
src/grace_control/api/main.py
src/grace_control/static/*
src/grace_control/templates/*
src/grace_control/ui/*
tests/grace_control/api/*
tests/grace_control/static/*
```

Do not assume exact paths. Search for existing admin/dashboard/run detail code first.

## 9. Implementation rules

1. Keep UI simple.
2. Use the existing frontend style and architecture.
3. Do not introduce a large framework.
4. Do not duplicate replay backend logic in JavaScript.
5. All replay calls must go through existing dev replay API endpoints.
6. Replay block must be safe when API returns 404/403.
7. Replay block must not require a page reload after each action, unless current UI is fully server-rendered and reload is the established pattern.
8. If JavaScript is added, ensure syntax is tested.
9. Any new API route must be included in OpenAPI tests if applicable.
10. Do not mutate packet state from UI replay actions.

## 10. JavaScript safety requirement

Previous frontend bugs were only visible later in the admin UI because JavaScript syntax/runtime errors were not caught early.

Therefore this TZ requires explicit JS checks if any JS is touched.

Add at least one of:

```bash
node --check path/to/file.js
```

or a project-appropriate equivalent test.

If JS is inline inside HTML/template, either:

- extract it to a `.js` file and run `node --check`; or
- add a lightweight test that parses/checks the inline script content.

Acceptance must fail if a syntax error would reach the admin UI.

## 11. Tests

Add tests appropriate to the existing project structure.

Required test coverage:

### 11.1 Dev replay block visibility

- When dev tools disabled, replay block/buttons are hidden or disabled.
- When dev tools enabled and run is replayable, replay block/buttons are visible.

### 11.2 Button calls

Test that each button maps to the correct endpoint/body:

```text
Replay T0 -> replay-acceptance {stage:t0}
Replay T1 -> replay-acceptance {stage:t1}
Replay T2 -> replay-acceptance {stage:t2}
Replay Full Acceptance -> replay-acceptance {stage:full_acceptance}
Replay Verifier -> rerun-verifier {}
Replay Reviewer -> rerun-reviewer {}
```

This can be done through JS unit tests, Playwright test, or server-rendered HTML assertions plus a small JS function test.

### 11.3 Result rendering

- Successful replay result displays status and summary.
- Failed replay result displays error code/message.
- `WORKTREE_MISSING` displays `patch_path` if present.

### 11.4 State safety

- UI replay action must not call packet release/retry/merge endpoints.
- If backend tests already cover packet state immutability, UI tests should still verify no wrong endpoint is called.

### 11.5 JavaScript syntax

- Any changed JS file passes syntax check.
- Add this to `make test`, `make lint`, or targeted test command if consistent with the repo.

## 12. Manual smoke

Run GRACE in dev mode:

```bash
export GRACE_DEV_TOOLS_ENABLED=1
export GRACE_DEV_KEEP_FAILED_WORKTREES=1
scripts/live_supervisor.sh --target-dir /tmp/grace-live-wt --source-dir /path/to/grace-orchestrator
```

Open admin UI.

Use a failed real packet run.

Expected:

1. Replay block appears on run detail.
2. Press `Replay T2`.
3. Button enters loading state.
4. Result appears without page crash.
5. No context builder, architect, or coder process starts.
6. Packet state is unchanged.
7. Replay artifacts are visible in response/path.
8. Press `Replay Verifier`.
9. Verifier result appears.

## 13. Acceptance criteria

Implementation is accepted only if all are true:

1. UI exposes replay buttons for replayable runs when dev tools are enabled.
2. UI hides or disables replay controls when dev tools are disabled.
3. Buttons call the correct existing dev replay API endpoints.
4. Results and errors are rendered clearly.
5. `WORKTREE_MISSING` shows `patch_path` if API returns it.
6. Replay UI does not mutate packet state.
7. Replay UI does not call coder/architect/context endpoints.
8. JavaScript syntax is tested if JS is changed.
9. Tests cover visibility, endpoint mapping, result rendering, error rendering, and state safety.
10. No heavy frontend framework is introduced.
11. OpenAPI/docs are updated only if new backend endpoint is added.

## 14. Suggested implementation order

1. Locate existing admin/run detail UI.
2. Identify how run detail data is loaded.
3. Add small replay API client helper in existing frontend style.
4. Add replay controls block.
5. Add result/history rendering.
6. Add tests for endpoint mapping and rendering.
7. Add JS syntax check.
8. Manual smoke with real failed run.

## 15. Notes for coder model

Keep the first version boring and reliable.

The user needs fewer clicks during real-loop debugging, not a complex dashboard redesign.

Do not overbuild history, charts, filters, or automatic recovery.

The correct MVP is: open failed run -> press replay button -> see result.
