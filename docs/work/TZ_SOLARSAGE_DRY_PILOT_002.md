# TZ: Solar Sage dry pilot 002 — tiny UI-safe change via target_repo_worktree

Date: 2026-06-11
Status: ready for execution
Priority: P0 real-target pilot 002
Scope: Solar Sage tiny UI-safe change through GRACE `target_repo_worktree`

Related:
- `docs/work/TZ_SOLARSAGE_DRY_PILOT_001.md`
- `docs/work/REPORT_SOLARSAGE_DRY_PILOT_001.md`
- `docs/work/REVIEW_SOLARSAGE_DRY_PILOT_001_92BB7C0.md`
- `docs/work/TZ_TARGET_REPO_WORKTREE_INTEGRATION.md`
- `docs/work/REVIEW_TARGET_REPO_WORKTREE_B9B134F.md`

## 1. Context

Solar Sage dry pilot 001 passed.

The bridge is proven:

```text
GRACE orchestrator
→ target_repo_worktree
→ /opt/solarsage-astro
→ coder-opencode
→ Solar Sage worktree
→ acceptance
→ merge into Solar Sage main
```

Pilot 001 was docs-only.

Pilot 002 should be the first tiny real UI-safe change.

This is still not a business feature.

## 2. Goal

Run a second Solar Sage target-repo pilot with a minimal UI-safe change and real Node gates.

The goal is to prove that GRACE can safely modify a real Solar Sage frontend file while:

```text
agent sees full Solar Sage repo
agent does not see GRACE repo
change scope is tiny
acceptance_profile=NORMAL
pnpm lint/typecheck/test:run gates pass
report includes real evidence JSON snippets
```

## 3. Non-goals

Do not touch auth.
Do not touch payments.
Do not touch subscriptions.
Do not touch production deployment/config.
Do not touch API contracts.
Do not touch data model/schema.
Do not refactor large UI areas.
Do not run browser E2E unless the runner already supports it cheaply.
Do not implement bounded context builder.
Do not implement scoped_copy apply-back.

## 4. Target repo

Target repo:

```text
/opt/solarsage-astro
```

Expected GitHub repo:

```text
basilivanov/solarsage-astro
```

Workspace mode:

```text
target_repo_worktree
```

Worktree root:

```text
/tmp/grace-agent-worktrees
```

Executor profile:

```text
coder-opencode
```

Do not use:

```text
coder-opencode-fixture
```

## 5. Required preflight before run

Before starting the pilot:

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

If the repo is dirty:

```text
STOP. Commit or stash first. Do not auto-stash.
```

## 6. Pilot change

Implement one tiny UI-safe, non-business visible change.

Preferred change:

```text
Add a small, non-interactive footer/helper copy to the existing Today/current-day screen, or to the smallest existing public/home screen if Today screen is not found.
```

The copy must be harmless and product-neutral:

```text
Data is shown for guidance only. Check important decisions before acting.
```

Russian alternative if the surrounding UI is Russian:

```text
Данные носят справочный характер. Важные решения лучше перепроверить.
```

Rules:

```text
- Do not add new navigation.
- Do not add new state.
- Do not add API calls.
- Do not add dependencies.
- Do not alter auth/payment/subscription code.
- Do not change business logic.
- Do not change database/schema.
- Keep change to 1–3 files maximum.
```

The agent must inspect the Solar Sage repo and choose the smallest existing UI file that already renders the relevant page.

If Today/current-day screen cannot be identified quickly, fall back to the existing home/main screen.

## 7. Allowed write scope

Preferred allowed scope should be narrow after discovery.

Initial safe scope:

```text
app/**
pages/**
src/**
components/**
tests/**
__tests__/**
```

But final changed files must be limited to:

```text
1 UI file
0–1 unit/component test file if an existing nearby test exists
0–1 snapshot/test fixture update if required
```

Hard forbidden paths:

```text
.env*
package.json
pnpm-lock.yaml
next.config.*
vercel.json
docker*
.github/**
prisma/**
drizzle/**
db/**
supabase/**
auth/**
payment*/**
subscription*/**
```

If implementation requires touching forbidden paths, stop and report blocker.

## 8. Scenario

Create or update live scenario:

```text
tests_live/scenarios/solarsage-ui-safe-pilot-002.yaml
```

The scenario should use:

```yaml
id: solarsage-ui-safe-pilot-002
target_repo_worktree: true
waves:
  - id: W1
    title: Solar Sage UI-safe pilot 002
    packets:
      - id: P1
        role: coder
        acceptance_profile: NORMAL
        prompt: >-
          Make one tiny UI-safe copy-only change in Solar Sage using the existing UI structure.
          Prefer the Today/current-day screen. If it cannot be identified quickly, use the home/main screen.
          Add a small non-interactive helper copy: "Data is shown for guidance only. Check important decisions before acting."
          Use Russian equivalent only if the surrounding UI is Russian.
          Do not add dependencies, API calls, state, navigation, auth/payment/subscription changes, schema changes, or production config changes.
          Keep final changes to 1 UI file and optionally 1 nearby test file.
        verification:
          t0:
            commands:
              - git status --short
          t1:
            commands:
              - pnpm lint
              - pnpm typecheck
          t2:
            commands:
              - pnpm test:run
        scope:
          - app/**
          - pages/**
          - src/**
          - components/**
          - tests/**
          - __tests__/**
expected:
  final_state: accepted
  min_real_agent_runs: 1
```

If `pnpm test:run` is too broad but exists and is standard for the repo, keep it.

If `pnpm test:run` fails because of unrelated pre-existing tests, the agent must not hide it. Report exact failing tests and mark pilot failed or blocked.

## 9. Runner command

Command template:

```bash
cd /tmp/grace-orchestrator-export

rm -f /tmp/grace-solarsage-pilot-002.db
fuser -k 8042/tcp 2>/dev/null || true
sleep 1

setsid env \
  GRACE_DATABASE_URL="sqlite:////tmp/grace-solarsage-pilot-002.db" \
  GRACE_DEV_TOOLS_ENABLED=1 \
  GRACE_FAST_FAIL=1 \
  GRACE_TARGET_REPO_ROOT="/opt/solarsage-astro" \
  GRACE_WORKSPACE_MODE="target_repo_worktree" \
  GRACE_WORKTREE_ROOT="/tmp/grace-agent-worktrees" \
  GRACE_REQUIRE_CLEAN_TARGET_REPO=1 \
  GRACE_REQUIRE_REMOTE_SYNC=1 \
  python3 scripts/api_watchdog.py > /tmp/grace-solarsage-pilot-002-watchdog.log 2>&1 &

sleep 3
curl -s http://127.0.0.1:8042/health
curl -s http://127.0.0.1:8042/health/liveness

PYTHONPATH=. \
GRACE_LIVE_AGENT_TESTS=1 \
GRACE_DEV_TOOLS_ENABLED=1 \
GRACE_FAST_FAIL=1 \
GRACE_DATABASE_URL="sqlite:////tmp/grace-solarsage-pilot-002.db" \
GRACE_TARGET_REPO_ROOT="/opt/solarsage-astro" \
GRACE_WORKSPACE_MODE="target_repo_worktree" \
GRACE_WORKTREE_ROOT="/tmp/grace-agent-worktrees" \
GRACE_REQUIRE_CLEAN_TARGET_REPO=1 \
GRACE_REQUIRE_REMOTE_SYNC=1 \
python3 -u tests_live/runner/wave_resume_runner.py \
  --scenario solarsage-ui-safe-pilot-002 \
  --api-url http://127.0.0.1:8042 \
  --source-dir . \
  --target-repo-root /opt/solarsage-astro \
  --workspace-mode target_repo_worktree \
  --agent-profile coder-opencode \
  --timeout 1200 \
  --keep-artifacts
```

## 10. Required evidence

Pilot 002 report must include real `packet_runs.result_json` snippets, not only textual assertions.

Required snippets:

```json
"workspace": {
  "workspace_mode": "target_repo_worktree",
  "workspace_path": "/tmp/grace-agent-worktrees/...",
  "target_repo_root": "/opt/solarsage-astro",
  "commit_semantics": "target_repo_commit"
}
```

```json
"target_repo_preflight": {
  "success": true,
  "is_git_repo": true,
  "working_tree_clean": true,
  "remote_sync": true,
  "worktree_conflict": false
}
```

Also capture:

```text
agent --dir / cwd
changed files list
acceptance profile
T0/T1/T2 command outputs
Solar Sage base SHA
Solar Sage agent commit SHA
Solar Sage merge commit SHA if merged
API/watchdog/OOM observations
```

## 11. Acceptance gates

Required gates:

```bash
pnpm lint
pnpm typecheck
pnpm test:run
```

Acceptance profile:

```text
NORMAL
```

Expected:

```text
T0 PASS
T1 PASS: pnpm lint + pnpm typecheck
T2 PASS: pnpm test:run
```

If `pnpm install` has not been run in Solar Sage environment and gates fail due to missing dependencies, do not silently install packages unless operator approves. Report:

```text
blocked: Solar Sage node dependencies unavailable
```

## 12. Post-run checks

After run:

```bash
cd /opt/solarsage-astro

git status --short
git log --oneline -5
git branch --list 'agent/*'
git worktree list
```

Expected:

```text
source checkout clean after merge
no stale agent/* branch unless intentionally preserved
no stale worktree under /tmp/grace-agent-worktrees for terminal rejected runs
```

Check GRACE repo:

```bash
cd /tmp/grace-orchestrator-export
git status --short
```

Expected:

```text
only intentional scenario/report/TZ files in GRACE
no Solar Sage app files leaked into GRACE
```

## 13. Output report

Create:

```text
docs/work/REPORT_SOLARSAGE_DRY_PILOT_002.md
```

Report must include:

```text
verdict
GRACE commit tested
Solar Sage base SHA
Solar Sage agent commit SHA
Solar Sage merge commit SHA if merged
command used
scenario id
executor profile
acceptance profile
workspace JSON snippet
target_repo_preflight JSON snippet
changed files
T0/T1/T2 command outputs
scope violations if any
GRACE leak check
Solar Sage post-run git status
watchdog/API/OOM observation
issues discovered/fixed
next recommended step
```

## 14. Pass criteria

Pilot 002 passes only if:

1. Solar Sage preflight passes.
2. Agent workspace is under `/tmp/grace-agent-worktrees`.
3. Agent workspace is from `/opt/solarsage-astro`.
4. Agent does not receive GRACE repo as cwd or `--dir`.
5. Changed files are limited to 1 UI file and optionally 1 nearby test file.
6. No forbidden paths are touched.
7. No auth/payment/subscription/schema/config changes are made.
8. `workspace` evidence JSON is present.
9. `target_repo_preflight` evidence JSON is present.
10. `pnpm lint` passes.
11. `pnpm typecheck` passes.
12. `pnpm test:run` passes.
13. API/watchdog remain stable.
14. No OOM.
15. Report exists at `docs/work/REPORT_SOLARSAGE_DRY_PILOT_002.md`.

## 15. Fail criteria

Fail immediately if:

```text
target repo dirty before run
local HEAD != origin/main while remote sync required
agent --dir/cwd points to GRACE repo
workspace contains GRACE source files
agent touches forbidden paths
agent changes auth/payment/subscription/schema/config
pnpm lint fails
pnpm typecheck fails
pnpm test:run fails due to agent change
API/watchdog restarts unexpectedly
OOM occurs
```

## 16. Next step after pass

If pilot 002 passes:

```text
Solar Sage pilot 003: first tiny business-safe UI improvement
```

Candidate for pilot 003:

```text
small Today screen recommendation-card copy/empty-state improvement
```

Still avoid payments/auth/subscriptions until the target-repo pipeline has passed multiple small pilots.
