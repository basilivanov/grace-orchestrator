# TZ: Dev Run Replay / Checkpoints for Faster Real-Loop Debugging

Status: draft for coder implementation  
Scope: development-only tooling for `grace-orchestrator`  
Target branch: `main` or feature branch from current `main`

## 1. Problem

Real GRACE feature execution is slow to debug because the full loop is expensive:

```text
context builder -> architect -> packet materialize -> coder -> T0/T1/T2 -> evidence verifier -> reviewer -> release/merge
```

Mock tests pass because they do not run real CLI agents, real worktrees, real stdout/stderr parsing, or real verification commands. When a real task fails in T0, T1, T2, evidence verifier, or reviewer, development currently tends to require starting too much of the loop again.

The project already has partial agent session resume through `agent_sessions`, `resume_mode`, `resume_session_id`, and CLI resume flags. That is useful, but it only resumes the LLM conversation. It does not let a developer rerun only the failed deterministic or verifier stage from an existing agent-produced worktree.

## 2. Goal

Add development-only replay/checkpoint support so that after a failed real run, a developer can rerun only the failed section without re-running context builder, architect, or coder.

Required MVP behavior:

```text
failed in T0 -> rerun T0 against same worktree
failed in T1 -> rerun T1 against same worktree
failed in T2 -> rerun T2 against same worktree
failed in evidence verifier -> rerun verifier using existing acceptance report and artifacts
failed in reviewer -> rerun reviewer using existing acceptance + verifier reports and artifacts
```

This must be dev-only and must not change production packet state transitions unless explicitly requested in a later TZ.

## 3. Non-goals

Do not implement a full production-grade resumable workflow engine.

Do not change the recovery ladder semantics.

Do not make replay automatically mark packets accepted, rejected, merged, or ready.

Do not skip canonical acceptance during normal packet execution.

Do not add a new CLI business-logic side channel. The project is API-first; if a thin CLI helper is later desired, it must call the API.

Do not rely on mocks as proof that this works. This feature exists specifically to debug real CLI-agent runs.

## 4. Design summary

Implement three small capabilities:

1. **Preserve failed worktrees in dev mode**
   - New setting: `GRACE_DEV_KEEP_FAILED_WORKTREES=false` by default.
   - When enabled, rejected/blocked/failed attempts must not delete their worktree or attempt branch.

2. **Persist replay metadata for every real run**
   - Store enough metadata in `PacketRun.result_json` to rerun acceptance/verifier/reviewer from the same worktree.
   - Preserve `agent_commit_sha`, `worktree_path`, `branch_name`, `base_sha`, `changed_files`, `run_dir`, `acceptance_report_path`, and detected `failed_stage` where available.

3. **Expose dev-only replay API**
   - New router under `/api/dev/runs/...`.
   - Guarded by `GRACE_DEV_TOOLS_ENABLED=false` by default.
   - Replay endpoints must not call the coder backend.
   - Replay endpoints must not mutate `Packet.state`.

## 5. Settings

Add settings in `src/grace_control/config/settings.py` or the existing canonical settings module.

Required settings:

```python
# names are illustrative; follow project style
settings.dev_tools_enabled: bool  # env: GRACE_DEV_TOOLS_ENABLED, default false
settings.dev_keep_failed_worktrees: bool  # env: GRACE_DEV_KEEP_FAILED_WORKTREES, default false
```

Rules:

- Do not read `os.environ` directly in routers, adapters, services, or core logic.
- Read env only through the existing config/settings boundary.
- Defaults must be safe for production: both flags are false.

## 6. Worktree retention change

Files to inspect/change:

```text
src/grace_control/adapters/packet_executor.py
src/grace_control/config/settings.py
```

Current behavior cleans worktree/branches on rejected/blocked/failed terminal outcomes. Add a guard:

```python
if status in cleanup_statuses and not settings.dev_keep_failed_worktrees:
    self._terminal_cleanup.run(...)
```

Apply equivalent guard in all terminal cleanup paths in `PacketExecutionAdapter`:

- `_route_after(...)._rej(...)`
- `_persist_run(...)`
- `_fast_reject(...)` if applicable

Expected behavior:

- Default: existing cleanup behavior unchanged.
- Dev flag enabled: failed worktree remains available for replay.

## 7. Persist replay metadata

Files to inspect/change:

```text
src/grace_control/adapters/packet_executor.py
src/grace_control/services/evidence_service.py
src/grace_control/db/schema.py  # only if needed; prefer result_json first
```

Prefer storing this in existing `PacketRun.result_json`, not by adding a new table in MVP.

For every run, include a `dev_replay` block in `PacketRun.result_json` when data is available:

```json
{
  "dev_replay": {
    "version": 1,
    "replayable": true,
    "packet_id": "pkt_...",
    "run_id": "pkt_...-R01",
    "run_number": 1,
    "worktree_path": "/tmp/grace-live-wt/.grace/worktrees/pkt_xxx-attempt-0001",
    "branch_name": "agent/pkt_xxx-attempt-0001",
    "base_ref": "main",
    "base_sha": "...",
    "agent_commit_sha": "...",
    "changed_files": ["src/...", "tests/..."],
    "run_dir": "/tmp/grace-live-wt/.grace/state/packets/pkt_xxx/runs/R01",
    "acceptance_report_path": "...",
    "evidence_path": "...",
    "failed_stage": "T2_E2E_OR_SMOKE",
    "created_at": "..."
  }
}
```

Important correction:

- If the coder produced a valid commit but acceptance failed, preserve the agent commit SHA in the failed `PacketRun` result.
- Today the code path can call `_persist_run(..., commit_sha="")` after acceptance failure. Change it so failed acceptance still stores the agent commit SHA if one exists.

Also write a patch artifact when possible:

```text
<run_dir>/agent.patch
```

Patch command conceptually:

```bash
git diff <base_sha>..HEAD > agent.patch
```

This patch is a recovery fallback if the worktree is later cleaned.

## 8. Dev replay API

Add a new router, for example:

```text
src/grace_control/api/routers/dev_replay.py
```

Mount it in the existing app factory/main router wiring under:

```text
/api/dev/runs
```

All endpoints must be guarded:

```text
if not settings.dev_tools_enabled: return 404 or 403
```

Prefer 404 if the project normally hides disabled surfaces; otherwise 403 with `DEV_TOOLS_DISABLED` is acceptable. Keep it consistent in tests.

### 8.1 Replay selected acceptance stage

Endpoint:

```http
POST /api/dev/runs/{run_id}/replay-acceptance
```

Request:

```json
{
  "stage": "t0",
  "worktree_path": null,
  "run_dir_suffix": null
}
```

Allowed `stage` values:

```text
t0
t1
t2
t2_browser
t3_visual
full_acceptance
```

MVP requirement:

- `t0`, `t1`, `t2`, and `full_acceptance` must work.
- `t2_browser` and `t3_visual` may return `501 NOT_IMPLEMENTED` if too large for this packet, but the API contract should reserve them.

Behavior:

1. Load `PacketRun` by `run_id`.
2. Load corresponding `Packet`.
3. Rebuild `ExecutionPacketContract` using existing `build_packet_contract` path.
4. Resolve replay metadata from `PacketRun.result_json.dev_replay`.
5. Use provided `worktree_path` only as dev override; default to stored path.
6. Validate worktree exists.
7. Run only the selected acceptance stage or full acceptance.
8. Store replay artifacts under:

```text
<original_run_dir>/replays/<timestamp>-<stage>/
```

9. Append a replay summary to `PacketRun.result_json.dev_replays[]`.
10. Return report JSON.

Response:

```json
{
  "data": {
    "run_id": "pkt_...-R01",
    "packet_id": "pkt_...",
    "stage": "t2",
    "status": "passed|failed|skipped",
    "summary": "...",
    "blocking_issues": [],
    "replay_dir": "...",
    "commands": []
  },
  "timestamp": "..."
}
```

### 8.2 Rerun evidence verifier

Endpoint:

```http
POST /api/dev/runs/{run_id}/rerun-verifier
```

Request:

```json
{
  "worktree_path": null,
  "acceptance_report_path": null
}
```

Behavior:

- Load existing packet, run metadata, changed files, artifacts, and acceptance report.
- Run `run_evidence_verifier(...)` with existing worktree/run_dir/artifacts.
- Do not call coder.
- Do not transition packet state.
- Store output under `<run_dir>/replays/<timestamp>-verifier/` and append to `dev_replays[]`.

Response includes verifier verdict and summary.

### 8.3 Rerun reviewer

Endpoint:

```http
POST /api/dev/runs/{run_id}/rerun-reviewer
```

Request:

```json
{
  "worktree_path": null,
  "acceptance_report_path": null,
  "verifier_report_path": null
}
```

Behavior:

- Load packet/run metadata.
- Load or rerun verifier report if needed only when explicitly requested by request flag. Default: require verifier report.
- Run `run_reviewer_gate(...)`.
- Do not call coder.
- Do not transition packet state.
- Store output under `<run_dir>/replays/<timestamp>-reviewer/` and append to `dev_replays[]`.

## 9. Acceptance pipeline refactor

Files to inspect/change:

```text
src/grace_control/core/acceptance_pipeline.py
```

Current canonical function `run_acceptance_pipeline(...)` must remain unchanged for normal execution.

Add a small public replay helper instead of duplicating logic in the router:

```python
def run_acceptance_stage_replay(
    *,
    packet: ExecutionPacketContract,
    legacy_result: Any,
    project_root: Path,
    worktree_path: Path,
    branch_name: str,
    run_dir: Path,
    stage: str,
    base_ref: str | None = None,
    base_sha: str | None = None,
) -> AcceptanceReport | StageResult:
    ...
```

Implementation rules:

- Reuse existing `AcceptancePipeline` internals.
- Do not duplicate command-running logic.
- For `full_acceptance`, call existing `run_acceptance_pipeline(...)`.
- For `t0`, `t1`, `t2`, run only the requested stage and return a report-shaped response.
- Do not change canonical acceptance semantics used by normal packet execution.

If a cleaner design is needed, it is acceptable to extract public methods from `AcceptancePipeline`:

```python
run_t0_for_replay(...)
run_t1_for_replay(...)
run_t2_for_replay(...)
```

Keep names explicit that these are replay/dev helpers.

## 10. Dev replay service

Add a service layer instead of putting business logic in the router:

```text
src/grace_control/services/dev_run_replay_service.py
```

Responsibilities:

- Guard dev tools setting.
- Load `PacketRun` and `Packet`.
- Validate replay metadata.
- Resolve worktree path and run directories.
- Call acceptance/verifier/reviewer helpers.
- Append replay entries to `PacketRun.result_json.dev_replays[]`.
- Return serializable DTOs.

Router should be thin.

## 11. Error handling

Use clear errors:

```text
DEV_TOOLS_DISABLED
RUN_NOT_FOUND
PACKET_NOT_FOUND
RUN_NOT_REPLAYABLE
WORKTREE_MISSING
ACCEPTANCE_REPORT_MISSING
VERIFIER_REPORT_MISSING
UNSUPPORTED_REPLAY_STAGE
```

For missing worktree, include patch fallback information if `agent.patch` exists:

```json
{
  "error": "WORKTREE_MISSING",
  "patch_path": "<run_dir>/agent.patch",
  "message": "worktree was cleaned; rehydrate from patch manually or rerun coder"
}
```

Do not silently rerun coder.

## 12. Tests

Add tests. Prefer unit/API tests with fake subprocess runners where possible, plus at least one integration-style test that uses a real temporary git worktree if existing test helpers make it practical.

Required tests:

### Settings

```text
tests/grace_control/config/test_dev_replay_settings.py
```

- dev tools disabled by default.
- keep failed worktrees disabled by default.
- env flags parse true/false correctly.

### Worktree retention

```text
tests/grace_control/adapters/test_dev_keep_failed_worktrees.py
```

- When `dev_keep_failed_worktrees=false`, rejected run invokes terminal cleanup as before.
- When `dev_keep_failed_worktrees=true`, rejected run does not invoke terminal cleanup.
- Test should monkeypatch cleanup service; do not require real deletion.

### Failed run metadata

```text
tests/grace_control/adapters/test_dev_replay_metadata.py
```

- Acceptance failure still persists `agent_commit_sha` when an agent commit exists.
- `PacketRun.result_json.dev_replay` includes worktree path, branch, base sha, run dir, changed files, and failed stage.
- `agent.patch` is created when base sha and worktree exist.

### Replay API disabled

```text
tests/grace_control/api/test_dev_replay_disabled.py
```

- `/api/dev/runs/{run_id}/replay-acceptance` returns disabled error when `GRACE_DEV_TOOLS_ENABLED=false`.
- Same for verifier/reviewer endpoints.

### Replay acceptance

```text
tests/grace_control/api/test_dev_replay_acceptance.py
```

- With dev tools enabled, replaying `t1` runs only T1 commands, not T0/T2 and not coder backend.
- Replaying `t2` runs only T2 commands.
- Replaying `full_acceptance` calls canonical acceptance path.
- Replay appends entry to `PacketRun.result_json.dev_replays[]`.

### Rerun verifier/reviewer

```text
tests/grace_control/api/test_dev_rerun_verifier_reviewer.py
```

- Rerun verifier uses existing run metadata and does not call coder backend.
- Rerun reviewer uses existing acceptance/verifier data and does not call coder backend.
- Missing acceptance/verifier reports produce explicit errors.

### OpenAPI

Update existing OpenAPI path tests or add:

```text
tests/grace_control/api/test_dev_replay_openapi.py
```

- OpenAPI contains the dev replay endpoints.
- Request/response bodies are schema-documented if the project uses Pydantic models for routers.

## 13. Manual smoke scenario

After implementation, verify manually on a real failed packet:

```bash
export GRACE_DEV_TOOLS_ENABLED=1
export GRACE_DEV_KEEP_FAILED_WORKTREES=1

# Run a real packet until it fails in T1/T2/verifier.
# Then inspect trace:
curl -s http://127.0.0.1:8042/api/trace/runs/<run_id> | jq .

# Rerun only T2:
curl -s -X POST \
  http://127.0.0.1:8042/api/dev/runs/<run_id>/replay-acceptance \
  -H 'Content-Type: application/json' \
  -d '{"stage":"t2"}' | jq .

# Rerun only verifier:
curl -s -X POST \
  http://127.0.0.1:8042/api/dev/runs/<run_id>/rerun-verifier \
  -H 'Content-Type: application/json' \
  -d '{}' | jq .
```

Expected:

- No context builder call.
- No architect call.
- No coder backend call.
- Same worktree is used.
- Replay artifacts are written under the original run directory.
- `Packet.state` is unchanged by replay.

## 14. Acceptance criteria

Implementation is accepted only if all are true:

1. Default production behavior is unchanged.
2. Dev replay endpoints are disabled by default.
3. Failed worktree cleanup is skipped only when `GRACE_DEV_KEEP_FAILED_WORKTREES=true`.
4. Failed runs preserve enough metadata to replay acceptance/verifier/reviewer.
5. A failed T2 can be rerun without context builder, architect, or coder.
6. A failed evidence verifier can be rerun without context builder, architect, or coder.
7. Replay never mutates `Packet.state`.
8. Replay appends audit data to `PacketRun.result_json.dev_replays[]`.
9. Tests cover disabled default, metadata persistence, worktree retention, acceptance replay, verifier/reviewer replay, and OpenAPI presence.
10. No direct `os.environ` reads are added outside the existing config/settings boundary.
11. No runtime business logic is added to CLI scripts.
12. No duplicated acceptance command-running logic is introduced.

## 15. Suggested implementation order

1. Add settings and tests for settings.
2. Add cleanup guard and tests.
3. Persist `dev_replay` metadata and patch artifact.
4. Add acceptance replay helper for T0/T1/T2/full acceptance.
5. Add `DevRunReplayService`.
6. Add `/api/dev/runs` router.
7. Add API tests.
8. Run `make lint`, targeted tests, then full `pytest tests/grace_control/ -q`.

## 16. Notes for coder model

Keep the implementation small. This TZ is not asking for a new workflow engine.

When in doubt, prefer a boring dev-only tool that makes the current real-loop debuggable.

Do not make optimistic assumptions about missing worktrees or missing artifacts. Return explicit errors.

Do not call the coder backend from any replay endpoint.

Do not change packet state from any replay endpoint.

Do not hide failures behind mocks. Add tests that would fail if replay accidentally invokes the agent backend again.
