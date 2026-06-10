# TZ: Target repo worktree integration for real project pilot

Date: 2026-06-10
Status: ready for architect/coder
Priority: P0 bridge from fixture smoke to real project pilot
Scope: GRACE ↔ target repository integration, workspace mode, config/YAML, runner, preflight, evidence

Related:
- `docs/work/TZ_MINIMAL_WORKTREE_AND_CONTEXT_BUILDER.md`
- `docs/work/TZ_MINIMAL_WORKTREE_SAFETY_POLISH.md`
- `docs/work/TZ_LIVE_FIXTURE_SCOPED_COPY_SMOKE.md`
- `docs/work/REPORT_LIVE_FIXTURE_SCOPED_COPY_SMOKE.md`
- `docs/work/TZ_RUNTIME_SKIP_CONTEXT_BUILDER.md`
- `docs/work/REPORT_RUNTIME_SKIP_CONTEXT_BUILDER.md`

## 1. Problem

The fixture path is now proven:

```text
coder-opencode-fixture
→ scoped_copy workspace
→ no GRACE repo leakage
→ skip_context_builder works at runtime
→ evidence contains workspace/context_builder metadata
→ no OOM
→ packet accepted
```

But this is still only fixture mode.

For a real project, for example Solar Sage Astro, `scoped_copy` is not the right first mode because apply-back / target-repo commit semantics are not implemented yet.

The next safe mode is:

```text
target_repo_worktree
```

Meaning:

```text
GRACE runs from grace-orchestrator repo
agent writes in a git worktree of the target project repo
agent sees the full target repo
agent does NOT see the GRACE orchestrator repo
commits/diffs/tests are real target-repo artifacts
```

This task must connect the two projects properly.

## 2. Goal

Implement and validate `target_repo_worktree` mode.

When configured, the agent workspace must be created from:

```text
execution.target_repo_root / GRACE_TARGET_REPO_ROOT
```

not from the GRACE orchestrator repo.

The first real-project pilot should be able to run with:

```text
GRACE_PROJECT_ROOT=/opt/grace-orchestrator or /tmp/grace-orchestrator-export
GRACE_TARGET_REPO_ROOT=/opt/solarsage-astro
GRACE_WORKSPACE_MODE=target_repo_worktree
GRACE_WORKTREE_ROOT=/tmp/grace-agent-worktrees
```

The agent must receive:

```text
--dir <target-repo-worktree>
cwd=<target-repo-worktree>
```

and must not receive:

```text
--dir <GRACE repo>
cwd=<GRACE repo>
```

## 3. Non-goals

Do not implement `scoped_copy` apply-back in this task.
Do not use `scoped_copy` for Solar Sage yet.
Do not implement full bounded `agent_context_builder` in this task.
Do not redesign the admin UI.
Do not change packet lifecycle semantics.
Do not make Solar Sage-specific code hardcoded in core runtime.
Do not require Docker/systemd/cgroup hardening in this task.
Do not turn `minimal_repo: true` on for normal real-project coder profile.

## 4. Current code facts to respect

`project_config.py` already has `execution.target_repo_root` and `execution.worktree_root` fields, but no explicit `workspace_mode` yet:

```python
class ExecutionSection(BaseModel):
    backend: str = "cli"
    state_root: str = ".grace/state"
    worktree_root: str = ".grace/worktrees"
    timeout_seconds: int = 600
    target_repo_root: str = ""
```

`settings.py` already has env-backed settings:

```python
target_repo_root: str = ""
worktree_root: str = ".grace/worktrees"
```

The executor currently has two behaviors:

```text
normal path: git.worktree_add(self.project_root, wt_path, branch, base_ref=base_ref)
minimal path: AgentWorkspaceBuilder.build_scoped_copy(...)
```

This task must add a third explicit behavior:

```text
target_repo_worktree: git.worktree_add(target_repo_root, wt_path, branch, base_ref=target_base_ref)
```

## 5. Required configuration model

### 5.1 Add `workspace_mode`

Add to both config layers:

```yaml
execution:
  workspace_mode: target_repo_worktree
  target_repo_root: /opt/solarsage-astro
  worktree_root: /tmp/grace-agent-worktrees
```

Allowed values:

```text
full_git_worktree      # legacy/self-evolution: worktree from GRACE repo
scoped_copy            # fixture/minimal copy mode, workspace_only semantics
target_repo_worktree   # real target repo git worktree
```

Required defaults:

```text
workspace_mode=full_git_worktree
```

unless explicitly configured.

Rationale: preserve old behavior unless configured.

### 5.2 Env vars

Support env variables:

```text
GRACE_WORKSPACE_MODE=target_repo_worktree
GRACE_TARGET_REPO_ROOT=/opt/solarsage-astro
GRACE_WORKTREE_ROOT=/tmp/grace-agent-worktrees
```

If env var naming already follows settings conventions, use that convention.

### 5.3 Config precedence

Respect current precedence:

```text
env GRACE_* > .grace/config.yaml > defaults
```

Do not silently ignore env overrides.

## 6. Required preflight gates

Before creating a `target_repo_worktree`, GRACE must run target repo preflight.

This is mandatory because agent execution from a dirty source repo is ambiguous and unsafe.

### 6.1 Validate target repo root

If:

```text
workspace_mode=target_repo_worktree
```

then `target_repo_root` is required and must be:

```text
existing directory
git repository
not equal to GRACE project root, unless explicitly self-evolution override is enabled
```

Required checks:

```bash
test -d "$GRACE_TARGET_REPO_ROOT"
git -C "$GRACE_TARGET_REPO_ROOT" rev-parse --is-inside-work-tree
git -C "$GRACE_TARGET_REPO_ROOT" rev-parse --show-toplevel
```

If validation fails, fail fast before starting agent.

Error should be clear:

```text
target_repo_worktree requires execution.target_repo_root / GRACE_TARGET_REPO_ROOT to point to a git repo
```

### 6.2 Target repo working tree must be clean

Before target-worktree run, target repo must have no uncommitted changes.

Required check:

```bash
git -C "$GRACE_TARGET_REPO_ROOT" status --porcelain
```

Acceptance:

```text
empty output => pass
non-empty output => fail fast
```

Error must be clear:

```text
target repo has uncommitted changes; commit or stash before running target_repo_worktree
```

Do not auto-stash and do not auto-commit.

Reason:

```text
A git worktree is created from committed refs.
Dirty files in the source checkout may not be present in the agent worktree.
Running agent while source repo is dirty creates misleading evidence and confusing diffs.
```

### 6.3 Branch and remote sync preflight

Before Solar Sage / real target pilot, check that local base branch matches remote.

Required checks when `require_remote_sync=true` or for real-project smoke:

```bash
git -C "$GRACE_TARGET_REPO_ROOT" branch --show-current
git -C "$GRACE_TARGET_REPO_ROOT" rev-parse HEAD
git -C "$GRACE_TARGET_REPO_ROOT" rev-parse origin/main
```

Expected for initial pilot:

```text
current branch: main or configured base_branch
local HEAD == origin/main
```

If local differs from remote, fail fast unless an explicit override is provided.

Error:

```text
target repo local HEAD differs from origin/main; sync or set explicit override before running
```

Do not silently run from a stale or ahead/behind branch.

### 6.4 Existing worktrees / stale branches

Multiple branches are fine.

Existing worktrees are fine only if they do not conflict with the new attempt branch/worktree path.

Required check:

```bash
git -C "$GRACE_TARGET_REPO_ROOT" worktree list --porcelain
```

If an old GRACE worktree or attempt branch conflicts with the intended branch/path:

```text
clean up that exact stale worktree/branch from target repo only
```

Do not delete branches from GRACE repo while operating in `target_repo_worktree` mode.

### 6.5 Preflight evidence

Persist preflight result in run evidence / result JSON:

```json
"target_repo_preflight": {
  "target_repo_root": "/opt/solarsage-astro",
  "is_git_repo": true,
  "working_tree_clean": true,
  "current_branch": "main",
  "local_head": "5fcc2c9...",
  "remote_head": "5fcc2c9...",
  "remote_sync": true,
  "worktree_conflict": false
}
```

If preflight fails, record enough metadata in the failed result/error for operator diagnosis.

## 7. Required workspace builder changes

### 7.1 Extend AgentWorkspaceBuilder

`AgentWorkspaceBuilder` currently supports `build_scoped_copy`.

Add:

```python
build_target_repo_worktree(
    workspace_root: Path,
    slug: str,
    branch: str,
    base_ref: str,
) -> WorkspaceResult
```

Behavior:

```text
create git worktree from target_root
worktree path = workspace_root / slug
branch = attempt branch
base_ref = target repo base ref
```

Return `WorkspaceResult` with:

```text
workspace_path
workspace_mode="target_repo_worktree"
target_repo_root
base_sha from target repo
copied_files=[]
omitted_files=[]
commit_semantics="target_repo_commit"
```

### 7.2 Do not use minimal repo semantics

In `target_repo_worktree` mode:

```text
commit_semantics != workspace_only
```

Use:

```text
commit_semantics=target_repo_commit
```

or equivalent.

### 7.3 Branch cleanup

Cleanup must target the same repo that created the worktree.

Important:

```text
full_git_worktree cleanup uses GRACE repo root
target_repo_worktree cleanup uses target repo root
scoped_copy cleanup deletes workspace directory only / isolated repo
```

Do not delete branches in the wrong repo.

Required:

```text
WorktreeCleanup.cleanup_attempt(repo_root=effective_repo_root, ...)
```

where:

```text
effective_repo_root = target_repo_root for target_repo_worktree
                 = project_root for full_git_worktree
```

### 7.4 Worktree path isolation

`worktree_root` should be outside the GRACE repo by default for real-project runs.

Recommended:

```text
/tmp/grace-agent-worktrees
```

Reject or warn if target worktree path is inside GRACE repo for real-project mode.

## 8. Packet executor integration

In `PacketExecutionAdapter._call_executor`, resolve effective workspace mode before creating workspace.

Pseudo:

```python
workspace_mode = executor.get("workspace_mode") or settings.workspace_mode or project_config.execution.workspace_mode
if executor.get("minimal_repo"):
    workspace_mode = "scoped_copy"  # fixture compatibility

if workspace_mode == "scoped_copy":
    ws = builder.build_scoped_copy(...)
elif workspace_mode == "target_repo_worktree":
    preflight = run_target_repo_preflight(target_repo_root)
    ws = builder.build_target_repo_worktree(...)
else:
    legacy full_git_worktree path
```

Required evidence:

```python
result.evidence["workspace"] = ws.to_dict()
result.evidence["target_repo_preflight"] = preflight.to_dict()
```

for `target_repo_worktree`.

For both `scoped_copy` and `target_repo_worktree`, `workspace` evidence is mandatory.

For legacy full mode, if easy, record:

```json
{"workspace_mode":"full_git_worktree"}
```

### 8.1 Base SHA semantics

For `target_repo_worktree`, `base_sha` must be resolved from target repo root, not GRACE repo root.

Acceptance/scope checks must use target repo base SHA.

### 8.2 Commit SHA semantics

Agent commit generated in target repo worktree is a real target repo commit.

Evidence should contain:

```json
"commit_semantics": "target_repo_commit"
```

## 9. Runner / scenario integration

### 9.1 CLI/env support

The live runner must be able to set:

```text
--target-repo-root /opt/solarsage-astro
--workspace-mode target_repo_worktree
```

or equivalent env vars:

```text
GRACE_TARGET_REPO_ROOT=/opt/solarsage-astro
GRACE_WORKSPACE_MODE=target_repo_worktree
```

If current runner only has `--target-dir` for fixture generation, do not overload it confusingly.

Add clearly named option if needed:

```text
--target-repo-root
--workspace-mode
--require-remote-sync / --no-require-remote-sync
```

### 9.2 Scenario profile

Add a real-project pilot scenario/profile config, not hardcoded in core.

Example name:

```text
solarsage-target-worktree-smoke
```

This scenario should use:

```text
workspace_mode=target_repo_worktree
executor profile: coder-opencode or dedicated coder-opencode-target-repo
context builder: existing behavior or skip only if explicitly configured
```

For first pilot, prefer a small safe packet that changes one low-risk file.

### 9.3 Do not use fixture profile for real repo

Do not use:

```text
coder-opencode-fixture
```

for Solar Sage target repo worktree unless explicitly justified.

Fixture profile is for:

```text
minimal_repo=true / scoped_copy
```

Real project profile should not use `minimal_repo`.

## 10. YAML examples required

Add documentation examples.

### 10.1 GRACE orchestrator `.grace/config.yaml`

Example:

```yaml
project:
  name: grace-orchestrator
  key: grace

execution:
  backend: cli
  workspace_mode: target_repo_worktree
  target_repo_root: /opt/solarsage-astro
  worktree_root: /tmp/grace-agent-worktrees
  timeout_seconds: 900
  require_clean_target_repo: true
  require_remote_sync: true

git:
  base_branch: main
  target_branch: main
```

### 10.2 Env-only startup

Example:

```bash
GRACE_PROJECT_ROOT=/opt/grace-orchestrator \
GRACE_TARGET_REPO_ROOT=/opt/solarsage-astro \
GRACE_WORKSPACE_MODE=target_repo_worktree \
GRACE_WORKTREE_ROOT=/tmp/grace-agent-worktrees \
GRACE_REQUIRE_CLEAN_TARGET_REPO=1 \
GRACE_REQUIRE_REMOTE_SYNC=1 \
GRACE_DATABASE_URL=sqlite:////tmp/grace-solarsage-pilot.db \
python3 scripts/api_watchdog.py
```

### 10.3 Agent evidence expected

Example:

```json
"workspace": {
  "workspace_mode": "target_repo_worktree",
  "workspace_path": "/tmp/grace-agent-worktrees/pkt_xxx-attempt-0001",
  "target_repo_root": "/opt/solarsage-astro",
  "base_sha": "...",
  "commit_semantics": "target_repo_commit"
},
"target_repo_preflight": {
  "working_tree_clean": true,
  "remote_sync": true
}
```

## 11. Acceptance pipeline behavior

For `target_repo_worktree`, acceptance should run in the target worktree:

```text
worktree_path=<target repo worktree>
project_root=<target repo root or target worktree, depending current acceptance API>
base_sha=<target repo base sha>
```

Important:

Do not run Solar Sage tests from GRACE repo cwd.

Acceptance commands must execute in target worktree.

## 12. Solar Sage pilot constraints

The first Solar Sage pilot should be deliberately tiny.

Recommended first task:

```text
Add or edit a small documentation/test-only marker file, or a low-risk UI copy test fixture.
```

Do not start with:

```text
large UI refactor
payment/subscription code
auth/session code
production deployment
large prompt/context builder work
```

Suggested gates for Solar Sage once target worktree mode works:

```bash
pnpm lint
pnpm typecheck
pnpm test:run
```

If the changed area touches Today screen:

```bash
pnpm test:e2e:today
```

But this TZ only needs to make the worktree mode possible and do a tiny smoke.

## 13. Tests required

### 13.1 Config tests

Add tests for:

```text
ProjectConfig.execution.workspace_mode parses target_repo_worktree
settings/env GRACE_WORKSPACE_MODE works
invalid workspace_mode fails or is rejected clearly
require_clean_target_repo parses from YAML/env
require_remote_sync parses from YAML/env
```

### 13.2 Target repo preflight tests

Add tests for:

```text
valid clean git repo passes
dirty working tree fails
local HEAD equal origin/main passes when require_remote_sync=true
local HEAD differs from origin/main fails when require_remote_sync=true
missing target repo fails
non-git target repo fails
```

### 13.3 Workspace builder tests

Add tests for `build_target_repo_worktree`:

```text
creates git worktree from target repo
worktree contains target repo files
worktree does not contain GRACE repo files
base_sha belongs to target repo
commit_semantics=target_repo_commit
workspace report to_dict contains target_repo_root
```

### 13.4 Packet executor tests

Add tests that mock executor run and verify:

```text
workspace_mode=target_repo_worktree calls GitService.worktree_add with target_repo_root
not self.project_root
ExecutionRequest.worktree_path points to target worktree
result.evidence.workspace.workspace_mode=target_repo_worktree
result.evidence.target_repo_preflight.working_tree_clean=true
```

### 13.5 Cleanup tests

Verify cleanup does not delete branches from the wrong repo.

```text
full_git_worktree cleanup -> GRACE repo
target_repo_worktree cleanup -> target repo
```

### 13.6 Live smoke test

Create/update report:

```text
docs/work/REPORT_TARGET_REPO_WORKTREE_SMOKE.md
```

Report must include:

```text
commit tested
command used
target_repo_root
workspace_mode
workspace_path
whether target repo was clean
local HEAD / remote HEAD
whether workspace contains target project files
whether workspace contains GRACE files
base_sha repo check
packet/run id
acceptance result
memory/OOM/API/watchdog observations
pass/fail verdict
```

## 14. Manual smoke commands

### 14.1 Preflight manual check

Before target-worktree smoke:

```bash
cd /opt/solarsage-astro

git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
git worktree list
```

Required for first pilot:

```text
git status --short is empty
current branch is main or configured base_branch
HEAD == origin/main
no conflicting GRACE attempt worktree exists
```

### 14.2 Fixture target_repo_worktree smoke first

Before Solar Sage, test with a local fixture git repo:

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
  --workspace-mode target_repo_worktree \
  --target-repo-root /tmp/grace-live-test/backend_fastapi_todo \
  --timeout 240
```

### 14.3 Solar Sage dry pilot after fixture pass

Only after fixture target-worktree smoke passes:

```bash
GRACE_TARGET_REPO_ROOT="/opt/solarsage-astro" \
GRACE_WORKSPACE_MODE="target_repo_worktree" \
GRACE_WORKTREE_ROOT="/tmp/grace-agent-worktrees" \
GRACE_REQUIRE_CLEAN_TARGET_REPO=1 \
GRACE_REQUIRE_REMOTE_SYNC=1 \
GRACE_DATABASE_URL="sqlite:////tmp/grace-solarsage-pilot.db" \
python3 -u tests_live/runner/wave_resume_runner.py \
  --scenario solarsage-target-worktree-smoke \
  --workspace-mode target_repo_worktree \
  --target-repo-root /opt/solarsage-astro \
  --timeout 900 \
  --keep-artifacts
```

## 15. Pass criteria

This TZ passes only if:

1. `workspace_mode=target_repo_worktree` is configurable from YAML/env/runner.
2. Target repo root is validated as a git repo.
3. Target repo dirty working tree fails fast.
4. Target repo local/remote mismatch fails fast when `require_remote_sync=true`.
5. Agent worktree is created from target repo, not GRACE repo.
6. Agent `cwd` and `--dir` point to target repo worktree.
7. Evidence records `workspace_mode=target_repo_worktree`.
8. Evidence records `commit_semantics=target_repo_commit`.
9. Evidence records `target_repo_preflight`.
10. Changed files and commits are target repo artifacts.
11. Cleanup uses target repo root for target worktree mode.
12. Fixture target-worktree smoke passes.
13. Solar Sage dry pilot can be run without agent seeing GRACE repo.
14. Existing fixture `scoped_copy` smoke still passes.
15. Full tests pass.

## 16. Fail criteria

Fail if:

```text
agent --dir points to GRACE repo during target_repo_worktree mode
target_repo_root is ignored
workspace path contains GRACE repo source files
base_sha belongs to GRACE repo instead of target repo
dirty target repo is allowed without explicit override
local/remote mismatch is allowed while require_remote_sync=true
cleanup deletes branch from wrong repo
normal coder profile is made minimal by accident
scoped_copy behavior regresses
context_builder skip evidence regresses
```

## 17. What remains after this TZ

After `target_repo_worktree` works, next work items are:

```text
1. first Solar Sage pilot packet
2. bounded agent_context_builder
3. GRACE Canon digest / prompt minimization
4. project profile support for Solar Sage verification commands
5. scoped_copy apply-back semantics for future large-repo optimization
```

Do not mix those into this patch unless needed for the smallest target-worktree smoke.
