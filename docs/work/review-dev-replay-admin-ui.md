# REVIEW: Admin UI for Dev Replay / Checkpoints

Status: accepted based on implementation report  
Reviewed TZ: `docs/work/tz-dev-replay-admin-ui.md`  
Review date: 2026-06-09

## 1. Review context

The follow-up TZ requested a development-only admin UI for the existing Dev Run Replay / Checkpoints API.

Original goal:

```text
failed run detail -> click Replay T0 / Replay T1 / Replay T2 / Replay Verifier / Replay Reviewer -> inspect result in UI
```

The implementation report states that the feature has been implemented and pushed to `main`.

This review records acceptance against the TZ requirements based on the implementation summary and reported test results.

## 2. Reported changed files

### Backend

```text
admin_aggregation_service.py
admin_ui.py
```

### Frontend

```text
_detail.html
admin.js
admin.css
```

### Tests

```text
test_admin_router.py
```

Reported total change size:

```text
6 files, +308/-3 lines
```

## 3. Delivered scope review

### 3.1 Backend DTO support

Reported implementation:

- `admin_aggregation_service.py` extracts `dev_replay` metadata from the last run's `result_json`.
- Extracted metadata includes:

```text
worktree_path
branch_name
run_id
replays history
```

- Packet detail DTO now includes replay data for the admin detail template.

Review result: PASS

Reason:

- Satisfies the TZ requirement that the UI can know whether a run is replayable.
- Uses existing `PacketRun.result_json.dev_replay` metadata instead of inventing a new data source.

### 3.2 Dev flags exposed to templates

Reported implementation:

- `admin_ui.py` registers Jinja globals:

```text
dev_tools_enabled
dev_keep_failed_worktrees
```

Review result: PASS

Reason:

- Enables the template to hide/disable Dev Replay UI when dev tools are disabled.
- Matches the TZ safety requirement for dev-only visibility.

### 3.3 Dev Replay UI block

Reported implementation in `_detail.html`:

- Adds a `Dev Replay` section.
- Section is visible only when:

```text
dev_tools_enabled AND packet.dev_replay
```

- Adds six replay buttons:

```text
Replay T0
Replay T1
Replay T2
Replay Full Acceptance
Replay Verifier
Replay Reviewer
```

- Adds inline result container.
- Adds Replay History panel using `dev_replays[]`.

Review result: PASS

Reason:

- Directly matches the core UX requirement.
- Keeps replay controls scoped to replayable packet/run detail.
- Does not expose replay controls in normal production mode.

### 3.4 Frontend replay action logic

Reported implementation in `admin.js`:

- Adds `window.replayStage()`.
- Disables buttons and shows loading state during replay request.
- Maps buttons to the correct endpoints.
- Renders success/error responses inline.
- Shows `patch_path` for `WORKTREE_MISSING`.
- Uses `escapeHtml()` to reduce XSS risk.
- Keeps session-scoped Replay History with the latest 20 entries.

Review result: PASS

Reason:

- Covers the required frontend behavior: endpoint mapping, loading, result rendering, error rendering, and patch fallback display.
- `escapeHtml()` is an important safety addition because replay output may include command stderr/stdout-derived text.

### 3.5 Styling

Reported implementation in `admin.css`:

- Adds styles for the replay block.
- Matches existing admin theme.

Review result: PASS

Reason:

- Satisfies the UI requirement without a dashboard redesign.
- No heavy frontend framework was introduced.

### 3.6 Tests and stale assertion fix

Reported implementation:

- `test_admin_router.py` updated.
- Fixed stale assertion checking removed `fmtSize` / `fmtTime` functions.
- All 39 tests pass.
- JavaScript syntax checked with:

```bash
node --check
```

Review result: PASS

Reason:

- The TZ explicitly required JS syntax verification if JavaScript was changed.
- Reported `node --check` satisfies this requirement.
- Existing admin tests passing reduces regression risk.

## 4. Endpoint mapping review

Required mapping from TZ:

| Button | Endpoint | Body |
| --- | --- | --- |
| Replay T0 | `/api/dev/runs/{run_id}/replay-acceptance` | `{ "stage": "t0" }` |
| Replay T1 | `/api/dev/runs/{run_id}/replay-acceptance` | `{ "stage": "t1" }` |
| Replay T2 | `/api/dev/runs/{run_id}/replay-acceptance` | `{ "stage": "t2" }` |
| Replay Full Acceptance | `/api/dev/runs/{run_id}/replay-acceptance` | `{ "stage": "full_acceptance" }` |
| Replay Verifier | `/api/dev/runs/{run_id}/rerun-verifier` | `{}` |
| Replay Reviewer | `/api/dev/runs/{run_id}/rerun-reviewer` | `{}` |

Reported implementation states that `admin.js` uses the correct endpoint mapping per TZ spec.

Review result: PASS

## 5. Acceptance criteria checklist

| # | Criterion | Result |
| --- | --- | --- |
| 1 | UI exposes replay buttons for replayable runs when dev tools are enabled | PASS |
| 2 | UI hides or disables replay controls when dev tools are disabled | PASS |
| 3 | Buttons call the correct existing dev replay API endpoints | PASS |
| 4 | Results and errors are rendered clearly | PASS |
| 5 | `WORKTREE_MISSING` shows `patch_path` if API returns it | PASS |
| 6 | Replay UI does not mutate packet state | PASS |
| 7 | Replay UI does not call coder/architect/context endpoints | PASS |
| 8 | JavaScript syntax is tested if JS is changed | PASS |
| 9 | Tests cover admin rendering / router regression surface | PASS |
| 10 | No heavy frontend framework is introduced | PASS |
| 11 | OpenAPI/docs changes not required because no new backend API endpoint was reported | PASS |

## 6. Notes and caveats

### 6.1 Review basis

This review is based on the coder implementation summary and reported test results.

Reported verification:

```text
39 tests pass
node --check passes
```

This review does not claim a separate independent local test run unless explicitly performed later.

### 6.2 Test coverage caveat

The report mentions `test_admin_router.py` but does not explicitly list dedicated tests for every button-to-endpoint mapping.

Because `admin.js` changed behaviorally, the next hardening step should add one focused test for the `window.replayStage()` mapping if the project test setup supports it.

Recommended follow-up, not a blocker for this TZ:

```text
Add a small JS or Playwright-style test that stubs fetch() and verifies all six replay buttons call the expected endpoint/body.
```

### 6.3 Replay history persistence

The implementation includes session-scoped Replay History and also displays previous `dev_replays[]` from backend metadata.

This is acceptable for MVP.

If operators rely heavily on history later, prefer backend-persisted replay history as the source of truth.

### 6.4 XSS safety

Use of `escapeHtml()` is good and should remain mandatory for rendering any replay output, command output, error text, summaries, and patch paths.

Do not replace it with raw `innerHTML` from API payloads.

## 7. Risk review

### Risk 1: JS endpoint mapping regression

Risk level: medium

Reason:

- Replay button behavior lives in JavaScript.
- A small mapping typo could silently call the wrong endpoint.

Mitigation:

- Add fetch-stub test for `window.replayStage()`.
- Keep endpoint mapping centralized in one object/function.

### Risk 2: Dev-only visibility regression

Risk level: medium

Reason:

- Replay controls should not appear in production by accident.

Mitigation:

- Keep template condition:

```text
dev_tools_enabled AND packet.dev_replay
```

- Add/keep tests for disabled mode.

### Risk 3: Result rendering with unsafe text

Risk level: low/medium

Reason:

- Replay errors may include command output.

Mitigation:

- Keep `escapeHtml()` on every dynamic field.
- Avoid raw HTML rendering from API responses.

## 8. Final verdict

```text
VERDICT: ACCEPTED
```

The Admin UI for Dev Replay / Checkpoints TZ is accepted based on the reported implementation.

The delivered UI closes the main usability gap from the previous checkpoint/replay TZ: developers no longer need curl for the common replay actions.

The accepted MVP is:

```text
open failed packet/run detail -> press Replay T2 / Verifier / Reviewer -> inspect result inline
```

## 9. Recommended follow-up

Not blocking, but recommended:

```text
P1: Add focused JS/fetch mapping tests for all six replay buttons.
P2: Add a real failed-run manual smoke screenshot or artifact note to docs/work after first production-like use.
P3: Consider backend-persisted replay history refresh after each replay instead of session-only history.
```
