# Codex Review 012 — Git/worktree/merge contract after `2c308ac`

Commit reviewed: `2c308ac44fb3912a98de279caa23c803a3b06bd6`

Spec: `docs/codex/tz-013-git-worktree-merge-contract.md`

Verdict: **REWORK_REQUIRED**.

The implementation is directionally good and closes several earlier P0 issues, but it introduced/left a few critical runtime breaks. Do not run the next golden/self-improvement task until the P0 items below are fixed.

---

## What is fixed well

### GitExecutionContext exists

`src/grace_control/core/git_context.py` adds:

```python
GitExecutionContext
resolve_git_execution_context(...)
```

with:

```text
control_plane_root
target_repo_root
runtime_state_root
worktree_root
base_ref
```

This is the right abstraction.

### Worker uses GitExecutionContext

Worker now builds `PacketExecutionAdapter` with:

```python
project_root=self._git_context.target_repo_root
state_root=self._git_context.runtime_state_root
worktree_root=self._git_context.worktree_root
```

This moves the system toward external-project compatibility.

### Attempt number is no longer always hardcoded to 0001

Adapter now passes `attempt=run_number` to `_call_legacy_runner(...)`, and `_call_legacy_runner(...)` passes it into `run_e2e_packet(...)`.

This closes a major retry/worktree collision risk.

### Self-evolution guard now inspects `wt_path`

The guard changed from:

```python
_collect_changed_files(worktree_root)
```

to:

```python
_collect_changed_files(wt_path)
```

This is the correct direction for future self-improvement/admin UI tasks.

### Merge endpoint no longer stashes by default

The merge endpoint now checks dirty target repo and returns `409 DIRTY_TARGET_REPO` instead of doing implicit stash/pop. This is safer.

---

## P0-1 — Worker calls `merge_packet(target_repo_root=...)`, but API client does not accept/send it

This is the immediate runtime blocker.

Worker now calls:

```python
await self.api.merge_packet(
    packet_id,
    target_repo_root=target_repo,
    worktree_path=result.worktree_path,
    branch_name=result.branch_name,
    commit_sha=result.commit_sha,
)
```

But `WorkerAPIClient.merge_packet(...)` is still:

```python
async def merge_packet(self, packet_id: str, commit_sha: str = "", worktree_path: str = "", branch_name: str = "") -> dict:
    r = await self.client.post(f"/api/packets/{packet_id}/merge", json={
        "commit_sha": commit_sha, "worktree_path": worktree_path, "branch_name": branch_name,
    })
```

So accepted packets will crash at runtime with:

```text
TypeError: merge_packet() got an unexpected keyword argument 'target_repo_root'
```

### Required fix

Update `WorkerAPIClient.merge_packet(...)`:

```python
async def merge_packet(
    self,
    packet_id: str,
    *,
    target_repo_root: str = "",
    commit_sha: str = "",
    worktree_path: str = "",
    branch_name: str = "",
) -> dict:
    r = await self.client.post(f"/api/packets/{packet_id}/merge", json={
        "target_repo_root": target_repo_root,
        "commit_sha": commit_sha,
        "worktree_path": worktree_path,
        "branch_name": branch_name,
    })
    r.raise_for_status()
    return r.json()
```

Add tests:

```text
test_worker_api_client_merge_sends_target_repo_root
test_worker_accepted_result_calls_merge_with_target_repo_root
```

---

## P0-2 — Eval external-project mode imports GRACE from target repo, not control-plane repo

Current eval runner sets:

```python
"PYTHONPATH": f"{target_repo}/src"
sys.path.insert(0, "{target_repo}/src")
```

This works only when target repo is the GRACE repo itself. It fails for external target projects because the target project usually does not contain `src/grace_control`.

This violates TZ-013 external project compatibility.

### Required fix

Eval runner must separate:

```text
control_plane_root = repo containing grace_control code
target_repo_root = repo being modified
```

Add CLI option:

```text
--control-plane-root PATH
```

Default:

```python
control_plane_root = Path(__file__).resolve().parents[...] or Path.cwd()
target_repo_root = --target-repo-root or Path.cwd()
```

Worker subprocess should use:

```python
PYTHONPATH = f"{control_plane_root}/src"
sys.path.insert(0, f"{control_plane_root}/src")
GRACE_TARGET_REPO_ROOT = target_repo_root
```

Do **not** import GRACE from `target_repo_root` unless target repo is actually the GRACE repo.

Add test:

```text
test_eval_external_target_uses_control_plane_pythonpath
```

---

## P0-3 — Early git rejection branches return without updating PacketRun

New commit verification branches return `ExecutionResult` directly:

```python
return ExecutionResult(
    accepted=False,
    domain_status="rejected",
    reason="Agent produced no changes",
    ...
)
```

Same pattern exists for:

```text
worktree missing
worktree cleaned before acceptance
git add failed
git commit failed
agent commit exception
```

These branches happen after `PacketRun` was created/marked running, but before `_update_packet_run_result(...)` is called.

Impact:

```text
worker releases packet as rejected
PacketRun may remain status=running
result_json lacks legacy/acceptance/verifier/reviewer reports
observability and retry diagnostics break
```

### Required fix

Create a helper for early failures, for example:

```python
def _finish_early_rejected_run(
    self,
    *,
    run_id: str,
    reason: str,
    duration_ms: int,
    executor_id: str,
    legacy_result: dict | None = None,
) -> ExecutionResult:
    ...
```

It must:

1. Set PacketRun.status = `rejected`.
2. Set `finished_at` and `duration_ms`.
3. Store result_json with all four keys.
4. Include an acceptance report object like:

```json
{"error": "pre-acceptance git failure", "summary": "..."}
```

5. Return the `ExecutionResult`.

Add tests:

```text
test_no_changes_updates_packet_run_result
test_git_add_failure_updates_packet_run_result
test_git_commit_failure_updates_packet_run_result
test_worktree_missing_updates_packet_run_result
```

---

## P0-4 — Commit verification incorrectly rejects already-committed agent changes

Current commit check uses:

```bash
git status --porcelain
```

If it is empty, adapter returns:

```text
Agent produced no changes
```

But an agent may legitimately commit its changes inside the worktree before returning. In that case:

```text
git status --porcelain == empty
git diff base_ref...HEAD != empty
```

Current logic would reject a valid already-committed worktree.

### Required fix

Before rejecting no changes, check committed delta versus base ref:

```bash
git diff --name-only <base_ref>...HEAD
```

or use the existing worktree changed-files helper.

Correct logic:

```text
if working tree dirty:
    git add/commit and capture HEAD
elif HEAD differs from base_ref:
    capture existing HEAD as agent_commit_sha
else:
    no changes produced → reject unless allow_noop=true
```

Add tests:

```text
test_already_committed_agent_changes_are_not_rejected
test_no_changes_rejected_only_when_no_worktree_diff_and_no_status
```

---

## P1-1 — Merge endpoint does not reject missing/unregistered worktree

TZ-013 required merge validation to reject unknown worktree paths. Current code only logs if `worktree_path` does not exist:

```python
if not wt.exists():
    _log.warn("merge_worktree_not_found", ...)
```

Then it still proceeds to merge branch if branch exists.

This is risky because the merge payload can claim any worktree path while only branch validation is enforced.

### Required fix

Fail closed:

```python
if not wt.exists():
    raise HTTPException(status_code=400, detail="worktree_path does not exist")
```

Also verify it is registered for the target repo:

```bash
git -C target_repo_root worktree list --porcelain
```

Add tests:

```text
test_merge_rejects_missing_worktree_path
test_merge_rejects_unregistered_worktree_path
```

---

## P1-2 — `commit_sha` is not stored in PacketRun.result_json

`ExecutionResult` now has `commit_sha`, and worker sends it to merge. But `_update_packet_run_result(...)` still writes only:

```json
legacy_result
acceptance_report
evidence_verifier_report
reviewer_report
```

Store:

```json
"agent_commit_sha": "..."
```

or:

```json
"git": {"agent_commit_sha": "...", "branch_name": "...", "worktree_path": "..."}
```

Add test:

```text
test_agent_commit_sha_stored_in_packet_run_result_json
```

---

## P1-3 — Eval loop does not treat `blocked` as terminal

Current eval wait loop stops when all states are in:

```python
("merged", "failed", "cancelled", "rejected")
```

But `blocked` is now terminal too. Eval can wait until timeout if a packet is blocked.

### Required fix

Include:

```python
"blocked"
```

Add test:

```text
test_eval_wait_loop_treats_blocked_as_terminal
```

---

## P1-4 — Defaults still can write DB into target repo

Eval worker env uses:

```python
"GRACE_DB_URL": os.environ.get("GRACE_DB_URL", f"sqlite:///{target_repo}/grace.db")
```

TZ-013 wanted runtime artifacts under `/tmp/grace-eval/...` by default.

### Required fix

Default DB should be:

```python
sqlite:///{state_rt}/grace.db
```

not target repo.

Add test:

```text
test_eval_default_db_url_uses_state_root_not_target_repo
```

---

## P1-5 — Merge failure event exists, but worker behavior should be tested

Merge endpoint leaves packet ACCEPTED on 409, which is correct. But worker currently catches the exception in the broad execution try/except after accepted release. This can log `execution_failed` even though execution already accepted and only merge failed.

Required behavior:

```text
accepted release succeeded
merge failed
→ log merge_failed
→ do not release failed/rejected
→ packet remains ACCEPTED
```

Add test:

```text
test_worker_merge_failure_does_not_release_failed_after_accepted
```

This may already be behavior by accident, but it needs a regression test.

---

## Required rework checklist

1. Fix `WorkerAPIClient.merge_packet(...)` signature and JSON payload.
2. Fix eval Python path: import GRACE from control-plane root, not target repo.
3. Add/update early-failure helper so all pre-acceptance git failures finish PacketRun.
4. Fix commit verification to accept already-committed worktree changes.
5. Reject missing/unregistered worktree in merge endpoint.
6. Store `agent_commit_sha` in PacketRun.result_json.
7. Add `blocked` to eval terminal states.
8. Default eval DB to `state_root/grace.db`, not target repo.
9. Add worker merge failure regression test.

---

## Suggested focused tests

Run/add:

```bash
pytest tests/grace_control/core/test_git_context.py -q
pytest tests/grace_control/adapters/test_git_contract.py -q
pytest tests/api/test_packet_merge_git_contract.py -q
pytest tests/test_worker_merge_payload.py -q
pytest tests/test_self_improvement_git_contract.py -q
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests -q
```

---

## Final verdict

**REWORK_REQUIRED.**

Do not run the next golden/self-improvement admin UI task until P0-1 through P0-4 are fixed. The most immediate blocker is the worker/API-client merge signature mismatch: accepted packets will fail at merge time before even reaching the new merge endpoint behavior.
