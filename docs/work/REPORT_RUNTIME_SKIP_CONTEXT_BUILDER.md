# Report: Runtime Skip Context Builder

Date: 2026-06-10
Verdict: PASS

## 1. Commit and Command
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

## 2. Profile and Run Details
- **Executor Profile:** `coder-opencode-fixture`
- **Packet ID / Run ID:** `pkt_6MRwrzAsdp / pkt_6MRwrzAsdp-R01`
- **Context Builder Invoked:** **No** (skipped at runtime due to `skip_context_builder: true` in the profile).

## 3. Evidence Verification

### 3.1 Context Builder Evidence Snippet
The run `result_json` records the skip decision:
```json
"context_builder": {
  "skipped": true,
  "reason": "executor.skip_context_builder=true",
  "executor_id": "coder-opencode-fixture"
}
```

### 3.2 Workspace Evidence Snippet
The worktree was successfully isolated:
```json
"workspace": {
  "workspace_path": "/tmp/grace-orchestrator-export/.grace/worktrees/pkt_6MRwrzAsdp-attempt-0001",
  "workspace_mode": "scoped_copy",
  "target_repo_root": "/tmp/grace-live-test",
  "copied_files": [
    {"original": "backend_fastapi_todo/main.py", "workspace": "backend_fastapi_todo/main.py"},
    {"original": "backend_fastapi_todo/tests/test_api.py", "workspace": "backend_fastapi_todo/tests/test_api.py"}
  ],
  "omitted_files": [],
  "base_sha": "a9b57387d251b065cd44c68a7bafd9524be5efc3",
  "commit_semantics": "workspace_only"
}
```

## 4. Observations
- **OOM / Process Memory:** Minimal memory footprint, no kernel OOM events.
- **API Status:** API stayed alive throughout the run.
- **Watchdog:** No restarts occurred.
