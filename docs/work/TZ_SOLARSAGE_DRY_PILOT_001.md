# TZ: Solar Sage dry pilot 001 via target_repo_worktree

Date: 2026-06-10
Status: ready for execution
Priority: P0 first real-target smoke
Scope: first Solar Sage pilot through GRACE `target_repo_worktree`

Related:
- `docs/work/TZ_TARGET_REPO_WORKTREE_INTEGRATION.md`
- `docs/work/REVIEW_TARGET_REPO_WORKTREE_B9B134F.md`
- `docs/work/REPORT_TARGET_REPO_WORKTREE_SMOKE.md`

## 1. Goal

Run the first real target-repository pilot against Solar Sage using:

```text
workspace_mode=target_repo_worktree
```

This is not a business-feature implementation yet.

This is a controlled dry pilot proving that:

```text
GRACE runs as the control plane
Solar Sage is the target repo
agent sees full Solar Sage worktree
agent does not see GRACE repo
preflight protects clean target repo state
acceptance runs from Solar Sage worktree
result/evidence proves all of the above
```

## 2. Non-goals

Do not implement a real product feature.
Do not touch payments, auth, subscriptions, production config, deployment, or user data.
Do not use `scoped_copy` for Solar Sage.
Do not give the agent GRACE repo as `--dir`.
Do not implement bounded context builder in this task.
Do not implement scoped-copy apply-back in this task.
Do not run a large UI refactor.

## 3. Target repository

Target repo:

```text
/opt/solarsage-astro
```

Expected GitHub repo:

```text
basilivanov/solarsage-astro
```

GRACE repo must remain separate:

```text
/opt/grace-orchestrator
# or current exported GRACE runtime path, e.g. /tmp/grace-orchestrator-export
```

Agent worktree root:

```text
/tmp/grace-agent-worktrees
```

## 4. Required preflight before running

Before starting GRACE runner, manually verify Solar Sage repo:

```bash
cd /opt/solarsage-astro

git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
git worktree list
```

Required:

```text
git status --short is empty
current branch is main or configured base branch
HEAD == origin/main when GRACE_REQUIRE_REMOTE_SYNC=1
no conflicting GRACE attempt worktree exists
```

If dirty:

```text
STOP. Commit or stash first. Do not auto-stash.
```

## 5. Pilot change type

This first pilot must be deliberately tiny and safe.

Preferred task:

```text
Create or update a documentation-only marker file in Solar Sage:

docs/grace/solar-sage-dry-pilot-001.md
```

The file should contain:

```markdown
# Solar Sage GRACE dry pilot 001

This file was created by the first GRACE target_repo_worktree dry pilot.

Purpose:
- verify target_repo_worktree wiring
- verify agent writes only inside Solar Sage target repo
- verify GRACE repo is not exposed as agent workspace
- verify acceptance/evidence path works on a real target repo
```

Allowed write scope:

```text
docs/grace/solar-sage-dry-pilot-001.md
```

No other files should be changed unless the runner/scenario itself requires a test fixture.

## 6. Execution configuration

Use target repo mode:

```bash
GRACE_TARGET_REPO_ROOT="/opt/solarsage-astro"
GRACE_WORKSPACE_MODE="target_repo_worktree"
GRACE_WORKTREE_ROOT="/tmp/grace-agent-worktrees"
GRACE_REQUIRE_CLEAN_TARGET_REPO=1
GRACE_REQUIRE_REMOTE_SYNC=1
```

Use normal coder profile, not fixture profile:

```text
coder-opencode
```

Do not use:

```text
coder-opencode-fixture
```

because that profile is tied to `scoped_copy` / minimal fixture behavior.

## 7. Runner command

Command template:

```bash
cd /tmp/grace-orchestrator-export

rm -f /tmp/grace-solarsage-pilot.db
fuser -k 8042/tcp 2>/dev/null || true
sleep 1

setsid env \
  GRACE_DATABASE_URL="sqlite:////tmp/grace-solarsage-pilot.db" \
  GRACE_DEV_TOOLS_ENABLED=1 \
  GRACE_FAST_FAIL=1 \
  GRACE_TARGET_REPO_ROOT="/opt/solarsage-astro" \
  GRACE_WORKSPACE_MODE="target_repo_worktree" \
  GRACE_WORKTREE_ROOT="/tmp/grace-agent-worktrees" \
  GRACE_REQUIRE_CLEAN_TARGET_REPO=1 \
  GRACE_REQUIRE_REMOTE_SYNC=1 \
  python3 scripts/api_watchdog.py > /tmp/grace-solarsage-watchdog.log 2>&1 &

sleep 3
curl -s http://127.0.0.1:8042/health
curl -s http://127.0.0.1:8042/health/liveness

PYTHONPATH=. \
GRACE_LIVE_AGENT_TESTS=1 \
GRACE_DEV_TOOLS_ENABLED=1 \
GRACE_FAST_FAIL=1 \
GRACE_DATABASE_URL="sqlite:////tmp/grace-solarsage-pilot.db" \
GRACE_TARGET_REPO_ROOT="/opt/solarsage-astro" \
GRACE_WORKSPACE_MODE="target_repo_worktree" \
GRACE_WORKTREE_ROOT="/tmp/grace-agent-worktrees" \
GRACE_REQUIRE_CLEAN_TARGET_REPO=1 \
GRACE_REQUIRE_REMOTE_SYNC=1 \
python3 -u tests_live/runner/wave_resume_runner.py \
  --scenario solarsage-target-worktree-smoke \
  --api-url http://127.0.0.1:8042 \
  --source-dir . \
  --target-repo-root /opt/solarsage-astro \
  --workspace-mode target_repo_worktree \
  --agent-profile coder-opencode \
  --timeout 900 \
  --keep-artifacts
```

If the scenario does not exist yet, add the smallest runner scenario named:

```text
solarsage-target-worktree-smoke
```

It must create one packet whose only allowed write scope is:

```text
docs/grace/solar-sage-dry-pilot-001.md
```

## 8. Acceptance gates

For this first pilot, acceptance should be light and safe.

Required minimum gates:

```bash
git status --short
```

Optional if cheap and available in Solar Sage environment:

```bash
pnpm lint
pnpm typecheck
pnpm test:run
```

Do not require Playwright/E2E for this docs-only pilot.

If package dependencies are not installed or the environment is not ready for Node gates, do not convert this pilot into environment setup work. Report that Node gates were skipped/unavailable and keep the pilot focused on target worktree wiring.

## 9. Required evidence

The final run evidence must include:

```json
"workspace": {
  "workspace_mode": "target_repo_worktree",
  "workspace_path": "/tmp/grace-agent-worktrees/<packet>-attempt-0001",
  "target_repo_root": "/opt/solarsage-astro",
  "base_sha": "...",
  "commit_semantics": "target_repo_commit"
}
```

and:

```json
"target_repo_preflight": {
  "success": true,
  "is_git_repo": true,
  "working_tree_clean": true,
  "current_branch": "main",
  "local_head": "...",
  "remote_head": "...",
  "remote_sync": true,
  "worktree_conflict": false
}
```

Also verify from logs/evidence:

```text
agent --dir points to /tmp/grace-agent-worktrees/...
agent cwd points to /tmp/grace-agent-worktrees/...
workspace contains Solar Sage files
workspace does not contain GRACE files
changed file is docs/grace/solar-sage-dry-pilot-001.md
```

## 10. Post-run manual checks

After run:

```bash
cd /opt/solarsage-astro

git status --short
git branch --list 'agent/*'
git worktree list
```

Expected:

```text
source checkout still clean unless merge/apply step intentionally changed it
no unexpected dirty files in source checkout
no stale failed attempt worktree if run was rejected and cleanup policy applies
agent branch exists only if expected by accepted flow
```

Check GRACE repo did not get target changes:

```bash
cd /tmp/grace-orchestrator-export
git status --short
```

Expected:

```text
no Solar Sage file changes inside GRACE repo
```

## 11. Output report

Create report in GRACE repo:

```text
docs/work/REPORT_SOLARSAGE_DRY_PILOT_001.md
```

Report must include:

```text
commit tested in GRACE
Solar Sage base SHA
Solar Sage resulting agent commit SHA if created
command used
executor profile
workspace_mode
workspace_path
target_repo_root
preflight JSON snippet
workspace JSON snippet
changed files
acceptance/gates result
whether GRACE files leaked into workspace
whether target source checkout remained clean
watchdog/API/OOM observation
pass/fail verdict
next recommended step
```

## 12. Pass criteria

This pilot passes only if:

1. Solar Sage target repo preflight passes.
2. Agent workspace is created under `/tmp/grace-agent-worktrees`.
3. Agent workspace is a git worktree from Solar Sage repo.
4. Agent does not receive GRACE repo as `--dir` or cwd.
5. Agent changes only `docs/grace/solar-sage-dry-pilot-001.md`.
6. Evidence records `workspace_mode=target_repo_worktree`.
7. Evidence records `commit_semantics=target_repo_commit`.
8. Evidence records successful `target_repo_preflight`.
9. No GRACE files leak into target workspace.
10. API/watchdog remain stable.
11. A report is created at `docs/work/REPORT_SOLARSAGE_DRY_PILOT_001.md`.

## 13. Fail criteria

Fail immediately if:

```text
target repo is dirty
local HEAD != origin/main while GRACE_REQUIRE_REMOTE_SYNC=1
agent --dir points to GRACE repo
workspace contains GRACE source files
agent changes anything outside allowed docs/grace marker file
worktree is created inside GRACE repo without explicit override
API/watchdog restarts unexpectedly
OOM occurs
```

## 14. Next step after pass

If this dry pilot passes, the next stage is:

```text
Solar Sage pilot 002: tiny real UI-safe change
```

Candidate:

```text
Add a tiny non-business visible copy/test fixture change with pnpm lint/typecheck/test:run gates.
```

Do not start large business-feature work until pilot 001 proves target repo wiring end-to-end.
