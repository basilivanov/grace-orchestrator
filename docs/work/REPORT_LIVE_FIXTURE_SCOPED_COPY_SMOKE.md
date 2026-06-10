# Report: Live Fixture Scoped-Copy Smoke Test

Date: 2026-06-10
Verdict: PASS

## 1. Commit and Command
- **Commit Tested:** `60fd886`
- **Command Used:**
```bash
PYTHONPATH=.:tests_live/fixtures/apps \
GRACE_LIVE_AGENT_TESTS=1 \
GRACE_DEV_TOOLS_ENABLED=1 \
GRACE_DATABASE_URL="sqlite:////tmp/grace-live-test.db" \
GRACE_TARGET_REPO_ROOT="/tmp/grace-live-test" \
python3 -u tests_live/runner/wave_resume_runner.py \
  --scenario backend-1w \
  --agent-profile coder-opencode-fixture \
  --timeout 240
```

## 2. Execution Parameters
- **Executor Profile:** `coder-opencode-fixture`
- **Packet ID / Run ID:** `pkt_FbAOKcZHrA / pkt_FbAOKcZHrA-R01`
- **Workspace Path:** `/tmp/grace-orchestrator-export/.grace/worktrees/pkt_FbAOKcZHrA-attempt-0001`

## 3. Workspace Isolation Analysis
- **Copied Files (2):**
  - `backend_fastapi_todo/main.py`
  - `backend_fastapi_todo/tests/test_api.py`
- **Omitted Files:** `[]`
- **GRACE Repo Leaks:** **None**. The workspace contains only the copied fixture files and the isolated `.git` repository. No `grace_control`, `docs`, `scripts`, or root configuration files leaked.

## 4. DB Record Verification
The `result_json` in the database records the workspace state successfully:
```json
"workspace": {
  "workspace_path": "/tmp/grace-orchestrator-export/.grace/worktrees/pkt_FbAOKcZHrA-attempt-0001",
  "workspace_mode": "scoped_copy",
  "target_repo_root": "/tmp/grace-live-test",
  "copied_files": [
    {"original": "backend_fastapi_todo/main.py", "workspace": "backend_fastapi_todo/main.py"},
    {"original": "backend_fastapi_todo/tests/test_api.py", "workspace": "backend_fastapi_todo/tests/test_api.py"}
  ],
  "omitted_files": [],
  "base_sha": "7e83e34872fa65c8b65fb2f4b424dea3379b27db",
  "commit_semantics": "workspace_only"
}
```

## 5. System and Resource Observations
- **Kernel OOM:** None detected.
- **API Status:** API remained alive throughout the run (PID `1291877` remained stable and healthy).
- **Watchdog Actions:** Watchdog did not restart the API during execution.
- **Process Memory:** Extremely low RSS footprint for `opencode` due to folder isolation.
- **State Transition:** Packet successfully proceeded to the `accepted` state.

## 6. Next Steps
1. Implement runtime handling for `skip_context_builder`.
2. Implement `target_repo_worktree` mode for the first Solar Sage pilot.
