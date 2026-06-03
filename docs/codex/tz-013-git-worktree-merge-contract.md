# TZ 013 — Git/worktree/merge contract for golden, external projects, and self-improvement

Audience: Flash coder / literal executor.

Goal: make the git/worktree/merge pipeline deterministic and portable. The same contract must work for:

1. GRACE golden smoke inside this repo.
2. External target projects connected to GRACE Control Plane.
3. Future self-improvement tasks that modify GRACE itself, including admin UI changes.

Do not redesign agents. Do not remove legacy runner in this task. This TZ is specifically about git roots, worktree roots, diff scope, verification cwd, merge protocol, retries, and self-improvement changed-file detection.

---

## 0. Current observed failures

Golden failures have mostly been git/worktree related, not model-quality related:

1. Scope guard saw main repo artifacts instead of only agent changes.
2. T1 verification ran from project root instead of agent worktree.
3. Merge failures are frequent and hard to diagnose.
4. Self-improvement guard currently checks the wrong root.
5. Current merge endpoint uses `Path.cwd()` instead of an explicit target repo root.
6. Attempts/worktrees are partly hardcoded to attempt `0001`, which is unsafe for retries.

---

## 1. Canonical concepts

Introduce clear names and keep them consistent everywhere.

```text
control_plane_root
  The repo/process running GRACE Control Plane.
  Example: /opt/grace-orchestrator or current grace-orchestrator checkout.

target_repo_root
  The repo being modified by agents.
  For golden/self-improvement this may be the same as control_plane_root.
  For external projects this is a different repository.

runtime_state_root
  GRACE runtime state directory, not part of target repo diff.
  Example: /tmp/grace-runs/<run-id>/state or <target>/.grace_state.

worktree_root
  Parent directory where packet worktrees are created.
  Should preferably be outside target_repo_root.
  Example: /tmp/grace-runs/<run-id>/worktrees.

packet_worktree_path
  The actual git worktree for one packet attempt.
  All coder writes happen here.

base_ref
  The git ref used to create packet branch/worktree.
  Usually origin/main or HEAD, but must be explicit.

branch_name
  The agent branch created for the packet attempt.
```

Important invariant:

```text
All packet code execution, verification, scope validation, expected evidence, and merge source must be based on packet_worktree_path / branch_name.
```

---

## 2. Required configuration

Add a small runtime config model or helper. Keep it simple.

Suggested file:

```text
src/grace_control/core/git_context.py
```

Add:

```python
from pathlib import Path
from pydantic import BaseModel

class GitExecutionContext(BaseModel):
    control_plane_root: Path
    target_repo_root: Path
    runtime_state_root: Path
    worktree_root: Path
    base_ref: str = "HEAD"
```

Add helper:

```python
def resolve_git_execution_context(
    *,
    control_plane_root: Path | None = None,
    target_repo_root: Path | None = None,
    runtime_state_root: Path | None = None,
    worktree_root: Path | None = None,
    base_ref: str | None = None,
) -> GitExecutionContext:
    ...
```

Environment fallbacks:

```text
GRACE_CONTROL_PLANE_ROOT
GRACE_TARGET_REPO_ROOT
GRACE_STATE_ROOT
GRACE_WORKTREE_ROOT
GRACE_BASE_REF
```

Default behavior:

```text
control_plane_root = Path.cwd()
target_repo_root = GRACE_TARGET_REPO_ROOT or control_plane_root
runtime_state_root = GRACE_STATE_ROOT or target_repo_root / ".grace_state"
worktree_root = GRACE_WORKTREE_ROOT or target_repo_root / ".grace_worktrees"
base_ref = GRACE_BASE_REF or "HEAD"
```

But for golden runbook, prefer `/tmp` state/worktrees to avoid polluting target repo.

---

## 3. Worker must use explicit target repo root

File:

```text
src/grace_control/worker/worker.py
```

Current worker defaults to:

```python
self._base_project_root = project_root or Path.cwd()
self._base_state_root = state_root or Path.cwd() / ".grace"
self._base_worktree_root = worktree_root or Path.cwd() / ".grace/worktrees"
```

Required:

1. Use `GitExecutionContext`.
2. `PacketExecutionAdapter.project_root` must mean `target_repo_root`, not random cwd.
3. Worker log should include:

```text
target_repo_root
runtime_state_root
worktree_root
base_ref
```

4. Eval runner and API docs must pass explicit roots.

---

## 4. Eval runner must not write runtime artifacts into target repo by default

File:

```text
src/grace_control/cli/main.py
```

Current eval uses:

```python
state_root=Path("{project_root}/.grace_state")
worktree_root=Path("{project_root}/.grace_worktrees")
```

For golden this has already caused scope pollution and dirty repo confusion.

Required behavior:

Default eval runtime should be outside repo:

```text
/tmp/grace-eval/<feature-slug-or-run-id>/state
/tmp/grace-eval/<feature-slug-or-run-id>/worktrees
/tmp/grace-eval/<feature-slug-or-run-id>/reports
```

Add CLI options:

```text
--target-repo-root PATH
--state-root PATH
--worktree-root PATH
--base-ref REF
```

Default:

```text
--target-repo-root = Path.cwd()
--state-root = /tmp/grace-eval/<feature-file-stem>/state
--worktree-root = /tmp/grace-eval/<feature-file-stem>/worktrees
--base-ref = HEAD
```

Report path can still be user-supplied, but recommend `/tmp/...` in runbook.

Acceptance test:

```text
eval_run spawns Worker with explicit target_repo_root, state_root, worktree_root.
```

---

## 5. Attempt number must be real, not hardcoded 0001

Files:

```text
src/grace_control/adapters/packet_executor.py
src/prefect_grace/platform/e2e_packet_runner.py
src/prefect_grace/platform/managed_packet_runner.py
```

Current adapter has hardcoded cleanup paths/branches:

```python
wt_path = self.worktree_root / f"{packet_id}-attempt-0001"
branch = f"agent/default/{packet_id}/attempt-0001"
```

And `_call_legacy_runner(...)` calls `run_e2e_packet(...)` without passing `attempt`, so it defaults to attempt `1`.

Required:

1. Use `run_number = packet.attempt_count` everywhere.
2. Pass `attempt=run_number` into `_call_legacy_runner(...)`.
3. Pass `attempt=run_number` into `run_e2e_packet(...)`.
4. Cleanup must target the actual attempt:

```python
attempt_slug = f"attempt-{run_number:04d}"
```

5. Branch naming must match WorktreeManager’s `_sanitize_branch_name(...)` exactly.

Do not manually reconstruct branch names in multiple places. Add helper if needed.

Suggested helper:

```python
def expected_worktree_path(worktree_root: Path, packet_id: str, attempt: int) -> Path: ...
def expected_branch_name(project_key: str, packet_id: str, attempt: int) -> str: ...
```

or reuse `WorktreeManager.status(...)`.

Tests:

```text
test_adapter_passes_real_attempt_to_legacy_runner
test_attempt_2_uses_attempt_0002_worktree_and_branch
test_retry_does_not_delete_attempt_0001_when_running_attempt_0002
```

---

## 6. Acceptance commands and evidence must use packet worktree

This overlaps TZ-012 but is part of the canonical git contract.

Required invariant:

```text
T0 command cwd = packet_worktree_path
T1 command cwd = packet_worktree_path
T2 command cwd = packet_worktree_path
expected_evidence file checks root = packet_worktree_path
changed_files source = git diff inside packet_worktree_path
```

Never run packet verification from `target_repo_root` unless `target_repo_root == packet_worktree_path`, which should not be true for normal managed execution.

Tests from TZ-012 remain required.

---

## 7. Self-improvement guard must inspect packet worktree only

File:

```text
src/grace_control/adapters/packet_executor.py
```

Current code:

```python
changed = _collect_changed_files(worktree_root)
guard_result = guard.check(changed, session_id=...)
```

This is wrong because `worktree_root` is the parent directory of all worktrees, not the current packet worktree.

Required:

```python
changed = _collect_changed_files(wt_path)
```

or better:

```python
changed = get_changed_files(wt_path, base_ref=base_ref)
```

Self-improvement guard must only see files changed by the current packet attempt.

Tests:

```text
test_self_evolution_guard_uses_packet_worktree_not_worktree_root
test_self_evolution_guard_ignores_other_packet_worktrees
test_self_evolution_guard_blocks_forbidden_admin_or_core_change_when_current_packet_changes_it
```

For future admin UI self-improvement, make sure allowed subsystems/scopes are explicit:

```text
admin_ui change should pass only if packet scope allows admin/UI files
core/runtime change should be strict or blocked unless explicitly allowed
```

---

## 8. Merge endpoint must use target_repo_root, not Path.cwd()

File:

```text
src/grace_control/api/routers/packets.py
```

Current merge code:

```python
repo = Path.cwd()
git stash ... cwd=repo
git merge branch_name ... cwd=repo
```

This breaks external projects and is dangerous for self-improvement because API cwd may be the control-plane repo or some shell cwd, not the target repo.

Required request shape:

```json
{
  "worktree_path": "...",
  "branch_name": "...",
  "target_repo_root": "...",
  "base_ref": "HEAD"
}
```

Backwards compatibility:

```python
target_repo_root = request.get("target_repo_root") or os.environ.get("GRACE_TARGET_REPO_ROOT") or Path.cwd()
```

But worker must always send it explicitly.

Validation:

1. `target_repo_root` must exist.
2. `target_repo_root/.git` or `git -C target_repo_root rev-parse --is-inside-work-tree` must pass.
3. `worktree_path` must exist and be registered as a worktree for `target_repo_root`:

```bash
git -C target_repo_root worktree list --porcelain
```

4. `branch_name` must exist:

```bash
git -C target_repo_root rev-parse --verify branch_name
```

If any validation fails, return 400/409 and do not change packet state.

Tests:

```text
test_merge_uses_target_repo_root_not_cwd
test_merge_rejects_missing_target_repo_root_for_external_mode
test_merge_rejects_unknown_worktree_path
test_merge_rejects_unknown_branch_name
```

---

## 9. Merge must be explicit two-phase and recoverable

Current worker flow:

```text
release accepted
→ call merge endpoint
```

If merge fails, packet may remain ACCEPTED and the worker exception path may not represent the merge failure cleanly.

Required states or metadata:

Minimum without adding states:

```text
ACCEPTED = ready to merge
MERGED = merge succeeded
ACCEPTED + last_merge_error = merge failed but packet remains retryable for merge
```

Preferred explicit states:

```text
MERGING
MERGE_FAILED
MERGED
```

If adding states is too large, implement minimum:

1. `/merge` fails closed and leaves state `ACCEPTED`.
2. Record event `packet_merge_failed` with stderr/stdout and branch/worktree/target_repo_root.
3. Worker catches merge failure separately and logs `merge_failed`, but does not call `/release failed` after an accepted release.
4. Add CLI/API endpoint to retry merge for accepted packet:

```text
POST /api/packets/{packet_id}/merge
```

with same payload.

5. Eval must report accepted-but-not-merged as failed, but include `merge_error` details.

Tests:

```text
test_merge_failure_leaves_packet_accepted
test_merge_failure_records_event
test_worker_merge_failure_does_not_release_failed_after_accepted
test_merge_retry_can_merge_accepted_packet_after_conflict_resolved
```

---

## 10. Do not use git stash in target repo as the normal merge strategy

Current merge stashes local changes in target repo:

```bash
git stash push -m pre-merge-...
git merge ...
git stash pop
```

This is risky because:

1. It mutates developer/operator working tree.
2. It can fail on stash pop.
3. It hides dirty repo problems.
4. It is bad for external projects.

Required behavior:

Before merge, require clean target repo unless explicitly allowed:

```bash
git -C target_repo_root status --porcelain
```

If dirty:

```text
return 409 DIRTY_TARGET_REPO
record event
leave packet ACCEPTED
```

Optional escape hatch:

```text
GRACE_ALLOW_DIRTY_TARGET_MERGE=true
```

But default must be fail-closed, no stash.

Tests:

```text
test_merge_dirty_target_repo_returns_409_no_stash
test_merge_clean_target_repo_does_not_call_stash
```

---

## 11. Commit creation in worktree must be verified

Current adapter runs:

```python
git add -A
git commit -m ...
```

but ignores non-zero return code. If there is nothing to commit or commit fails, merge may later fail or do nothing.

Required:

After agent execution and before acceptance:

1. Run `git status --porcelain` in `packet_worktree_path`.
2. If no changes:
   - if packet objective expected changes, return rejected: `no_changes_produced`.
   - for no-op packets, only allow if spec has explicit `allow_noop: true`.
3. Run `git add -A`.
4. Run `git commit -m ...`.
5. If commit fails, return rejected with stderr.
6. Capture commit SHA:

```bash
git rev-parse HEAD
```

7. Store in `ExecutionResult` and `PacketRun.result_json`:

```json
"agent_commit_sha": "..."
```

Add `commit_sha` to merge request and event.

Tests:

```text
test_no_changes_rejected_unless_allow_noop
test_commit_failure_rejected
test_agent_commit_sha_stored
test_merge_request_includes_commit_sha
```

---

## 12. Worker must pass target_repo_root and commit_sha to merge

File:

```text
src/grace_control/worker/worker.py
```

Current:

```python
await self.api.merge_packet(packet_id,
    worktree_path=result.worktree_path,
    branch_name=result.branch_name)
```

Required:

```python
await self.api.merge_packet(packet_id,
    target_repo_root=str(self._git_context.target_repo_root),
    worktree_path=result.worktree_path,
    branch_name=result.branch_name,
    commit_sha=result.commit_sha or "")
```

Add `commit_sha` to `ExecutionResult` model.

Tests:

```text
test_worker_merge_payload_includes_target_repo_root
test_worker_merge_payload_includes_commit_sha
```

---

## 13. External project compatibility

Add one integration-style test with two repos:

```text
control_repo = temp dir with GRACE code imported from current test environment
target_repo = temp git repo with simple file
worktree_root = temp outside target_repo
state_root = temp outside target_repo
```

Run enough of the pipeline or lower-level functions to prove:

1. Worktree is created from target repo.
2. Verification cwd is worktree.
3. Merge happens into target repo, not control repo cwd.
4. Control repo files are not included in scope diff.

Test name:

```text
test_external_target_repo_git_contract
```

If full pipeline is too heavy, test WorktreeManager + merge endpoint + acceptance runner separately.

---

## 14. Golden compatibility

Golden should run with:

```text
target_repo_root = current repo
state_root = /tmp/grace-eval/golden-smoke-live-001/state
worktree_root = /tmp/grace-eval/golden-smoke-live-001/worktrees
report = /tmp/grace-eval/golden-smoke-live-001/report.json
base_ref = HEAD or origin/main
```

The golden packet is FAST and sandboxed, so it should not need `agy` or `opencode`.

Expected changed files after successful merge:

```text
sandbox/golden/live_001/date_util.py
sandbox/golden/live_001/test_date_util.py
```

No changes should be detected from:

```text
.grace_state/
.grace_worktrees/
artifacts/
docs/codex/
src/grace_control/
```

---

## 15. Self-improvement compatibility

For self-improvement/admin UI changes:

1. `target_repo_root` is the GRACE repo itself.
2. `worktree_root` must still be outside target repo by default to avoid dirty root pollution.
3. self-evolution guard must inspect only current packet worktree diff.
4. Admin UI packets must explicitly scope admin/template/static files.
5. Core/runtime files must require STRICT or explicit self-improvement approval metadata.

Add tests:

```text
test_self_improvement_admin_ui_scope_passes_when_allowed
test_self_improvement_core_change_requires_strict_or_approval
test_self_improvement_ignores_runtime_state_and_other_worktrees
```

Do not implement full admin UI changes in this TZ. Only make the pipeline safe enough for that next task.

---

## 16. Tests to run

Run focused tests:

```bash
pytest tests/grace_control/core/test_acceptance_pipeline.py -q
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests/api/test_packets_api.py -q
pytest tests/test_worker_retry.py -q
pytest tests/test_worker_blocked_routing.py -q
pytest tests -q
```

Add new tests for this TZ:

```text
tests/grace_control/core/test_git_context.py
tests/grace_control/adapters/test_git_contract.py
tests/api/test_packet_merge_git_contract.py
tests/test_worker_merge_payload.py
tests/test_self_improvement_git_contract.py
```

---

## 17. Acceptance criteria

Done only if:

1. There is one explicit git execution context with target repo/state/worktree/base ref.
2. Worker and adapter use target repo root, not arbitrary cwd.
3. Eval uses /tmp state/worktree by default.
4. Attempt number is passed to legacy runner and worktree cleanup; no hardcoded attempt 0001 except in tests explicitly for attempt 1.
5. Acceptance commands run in packet worktree.
6. Self-improvement guard checks current packet worktree only.
7. Merge endpoint uses target_repo_root and validates branch/worktree.
8. Merge fails on dirty target repo by default, without stash.
9. Merge failure leaves packet accepted and records merge failure event.
10. Agent commit SHA is captured and sent to merge.
11. External target repo test proves merge affects target repo, not control plane cwd.
12. Golden smoke still works.
13. Self-improvement admin UI task can safely run next.

---

## 18. Do not do in this task

Do not rewrite the whole orchestrator.
Do not remove legacy runner.
Do not implement admin UI changes.
Do not implement complex architect profile routing.
Do not add auto-push to remote.
Do not use shell=True.
Do not use stash as default merge strategy.
Do not make dirty target repo merge by default.

---

## 19. After this TZ

Rerun golden smoke with explicit /tmp roots:

```bash
rm -rf /tmp/grace-eval/golden-smoke-live-001
mkdir -p /tmp/grace-eval/golden-smoke-live-001

export GRACE_TARGET_REPO_ROOT="$PWD"
export GRACE_STATE_ROOT="/tmp/grace-eval/golden-smoke-live-001/state"
export GRACE_WORKTREE_ROOT="/tmp/grace-eval/golden-smoke-live-001/worktrees"
export GRACE_BASE_REF="HEAD"
export GRACE_DB_URL="sqlite:////tmp/grace-eval/golden-smoke-live-001/grace.db"
export GRACE_AGENT_TIMEOUT=1200
export GRACE_CONTEXT_DISABLED=true
```

Terminal 1:

```bash
grace api start
```

Terminal 2:

```bash
grace eval run grace/features/golden-smoke-live-001.yaml \
  --workers 1 \
  --timeout 1200 \
  --report /tmp/grace-eval/golden-smoke-live-001/report.json
```

Verify:

```bash
cat /tmp/grace-eval/golden-smoke-live-001/report.json
git status --short
git log --oneline -5
find sandbox/golden/live_001 -maxdepth 2 -type f -print
```
