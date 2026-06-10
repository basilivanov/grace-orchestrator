# Report: Target Repo Worktree Smoke

Date: 2026-06-10
Verdict: PASS

## 1. Commit and Command
- **Command Used:**
```bash
PYTHONPATH=.:tests_live/fixtures/apps \
GRACE_LIVE_AGENT_TESTS=1 \
GRACE_DEV_TOOLS_ENABLED=1 \
GRACE_DATABASE_URL="sqlite:////tmp/grace-target-worktree-test.db" \
GRACE_TARGET_REPO_ROOT="/tmp/grace-live-test/backend_fastapi_todo" \
GRACE_WORKSPACE_MODE="target_repo_worktree" \
GRACE_WORKTREE_ROOT="/tmp/grace-agent-worktrees" \
GRACE_REQUIRE_CLEAN_TARGET_REPO=1 \
python3 -u tests_live/runner/wave_resume_runner.py \
  --scenario backend-1w \
  --agent-profile coder-opencode \
  --workspace-mode target_repo_worktree \
  --target-repo-root /tmp/grace-live-test/backend_fastapi_todo \
  --timeout 240
```

## 2. Environment Details
- **Target Repo Root:** `/tmp/grace-live-test/backend_fastapi_todo`
- **Workspace Mode:** `target_repo_worktree`
- **Workspace Path:** `/tmp/grace-agent-worktrees/pkt_DxoQ7ruiCy-attempt-0001`
- **Target Repo Clean:** **Yes** (verified via `git status --porcelain` in preflight).
- **Local HEAD / Remote HEAD:** `84e407413823f2f2bbef9b589cb69496ffe3ad64`
- **Base SHA Repo Check:** `84e407413823f2f2bbef9b589cb69496ffe3ad64` (belongs to target repo, not GRACE).

## 3. Workspace Isolation Analysis
- **Target Files Present:** **Yes**. Contains `main.py`, `tests/test_api.py`, etc.
- **GRACE Files Leaked:** **None**. Directory contents strictly limited to the target project.

## 4. DB Evidence Snout
```json
"workspace": {
  "workspace_path": "/tmp/grace-agent-worktrees/pkt_DxoQ7ruiCy-attempt-0001",
  "workspace_mode": "target_repo_worktree",
  "target_repo_root": "/tmp/grace-live-test/backend_fastapi_todo",
  "copied_files": [],
  "omitted_files": [],
  "base_sha": "84e407413823f2f2bbef9b589cb69496ffe3ad64",
  "commit_semantics": "target_repo_commit"
},
"target_repo_preflight": {
  "success": true,
  "error": "",
  "target_repo_root": "/tmp/grace-live-test/backend_fastapi_todo",
  "is_git_repo": true,
  "working_tree_clean": true,
  "current_branch": "main",
  "local_head": "84e407413823f2f2bbef9b589cb69496ffe3ad64",
  "remote_head": "",
  "remote_sync": true,
  "worktree_conflict": false
}
```

## 5. Operations Observation
- **OOM / Process Memory:** Stable memory footprint.
- **API Status:** API stayed alive throughout the run (uvicorn PID `1403667`).
- **Watchdog:** No restarts triggered.
