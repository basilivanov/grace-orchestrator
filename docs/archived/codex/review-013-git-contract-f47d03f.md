# Codex Review 013 — Git contract fixes after `f47d03f`

Commit reviewed: `f47d03fd23355d5b6bb00fd145f2795cffa589f4`

Previous review: `docs/codex/review-012-git-contract-2c308ac.md`

Verdict: **PASS FOR GOLDEN, REWORK_REQUIRED BEFORE EXTERNAL/SELF-IMPROVEMENT HARDENING.**

The immediate runtime blocker from review-012 is fixed: `WorkerAPIClient.merge_packet(...)` now accepts and sends `target_repo_root`. The simple FAST golden can proceed after local tests, assuming the agent does not create its own commit before returning.

However, one important git-contract issue remains: the “already committed agent changes” case is still not truly fixed because the code compares against dynamic `HEAD`, not the original base ref used to create the worktree.

---

## Fixed from review-012

### P0-1 — WorkerAPIClient merge payload

Status: **fixed.**

`WorkerAPIClient.merge_packet(...)` now accepts keyword-only `target_repo_root` and sends it to `/merge`:

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
    ...
```

This closes the immediate `TypeError: unexpected keyword argument 'target_repo_root'` runtime failure.

---

### P0-2 — Eval PYTHONPATH control-plane root

Status: **fixed enough.**

`grace eval run` now has:

```text
--control-plane-root
--target-repo-root
--state-root
--worktree-root
--base-ref
```

Worker subprocess imports GRACE from:

```python
PYTHONPATH = f"{ctrl_root}/src"
sys.path.insert(0, f"{ctrl_root}/src")
```

not from the target repo. This is the right direction for external-project compatibility.

P1 note: if the CLI is invoked from an external target repo without `--control-plane-root`, default `ctrl_root = Path.cwd()` will still be wrong. That is acceptable if documented, but the external-project runbook must explicitly pass `--control-plane-root`.

---

### P0-3 — Early git failures update PacketRun

Status: **fixed.**

`_finish_early_rejected_run(...)` now updates `PacketRun` via `_update_packet_run_result(...)` and returns a rejected `ExecutionResult`.

This covers early branches like:

```text
worktree missing
worktree cleaned before acceptance
no changes produced
git add failed
git commit failed
agent commit exception
```

So these branches should no longer leave `PacketRun.status = running`.

P1 note: the generated `acceptance_report` placeholder is still generic:

```json
{"error": "acceptance pipeline failed"}
```

for pre-acceptance git failures. Better later:

```json
{"error": "pre-acceptance git failure", "summary": "..."}
```

Not a golden blocker.

---

### P1-1 — Missing/unregistered worktree rejected

Status: **mostly fixed.**

Merge now fails if `worktree_path` does not exist.

It also checks `git worktree list --porcelain` and rejects if `worktree_path` is not in stdout.

P1 note: this currently uses raw substring matching:

```python
if worktree_path not in wt_list.stdout:
```

A more robust version should parse `worktree <path>` lines and compare resolved paths.

Not a golden blocker.

---

### P1-2 — agent_commit_sha stored

Status: **fixed.**

`_update_packet_run_result(...)` now stores:

```json
"agent_commit_sha": "..."
```

---

### P1-3 — blocked terminal in eval

Status: **fixed.**

Eval loop now treats `blocked` as terminal.

---

### P1-4 — eval DB defaults to state root

Status: **fixed.**

Worker env now defaults DB to:

```python
sqlite:///{state_rt}/grace.db
```

instead of writing `grace.db` into target repo.

---

## Remaining blocker before external/self-improvement hardening

### P0-4 — already-committed agent changes are still not reliably detected

Status: **not fully fixed.**

The new code checks:

```python
base = os.environ.get("GRACE_BASE_REF", "HEAD")
diff_cmd = ["git", "diff", "--name-only", f"{base}...HEAD"]
```

If `GRACE_BASE_REF` is not explicitly set to the original base ref, this defaults to `HEAD`.

In a worktree where the agent already committed changes before returning, current `HEAD` is the agent commit. Therefore:

```bash
git diff --name-only HEAD...HEAD
```

is empty.

If the working tree is also clean, the adapter still rejects:

```text
Agent produced no changes
```

So the intended review-012 fix only works when `GRACE_BASE_REF` is explicitly set to a stable base ref such as `origin/main` or the original base SHA.

### Required fix

Store and use the actual worktree base ref/SHA.

Preferred minimal approach:

1. Before calling the agent, resolve base SHA in target repo:

```bash
git -C target_repo_root rev-parse <base_ref>
```

2. Pass it through adapter/legacy result metadata, or store locally as `base_sha`.

3. In commit verification, compare:

```bash
git -C packet_worktree diff --name-only <base_sha>...HEAD
```

not dynamic `HEAD...HEAD`.

4. If no uncommitted files and `<base_sha>...HEAD` has files, accept existing HEAD as `agent_commit_sha`.

5. If no uncommitted files and `<base_sha>...HEAD` is empty, reject no changes.

Add tests:

```text
test_already_committed_agent_changes_are_not_rejected_when_base_sha_is_used
test_default_head_does_not_compare_head_to_itself_after_agent_commit
test_base_ref_env_origin_main_detects_committed_changes
```

This is not likely to block the current golden if the coder leaves uncommitted files, because the adapter will commit them itself. But it matters for agents that self-commit and for robust external/self-improvement runs.

---

## New P1 — base_ref is not consistently wired into legacy worktree creation

`GitExecutionContext` has `base_ref`, and eval sets `GRACE_BASE_REF`, but `_call_legacy_runner(...)` still calls `run_e2e_packet(...)` without passing `base_ref`, so `run_e2e_packet` defaults to `HEAD`.

Required later:

```python
run_e2e_packet(..., base_ref=os.environ.get("GRACE_BASE_REF", "HEAD"), ...)
```

or pass `base_ref` through `PacketExecutionAdapter` from `GitExecutionContext`.

This matters when external project runs want `origin/main` or a pinned SHA instead of current local HEAD.

---

## New P1 — external runbook must require `--control-plane-root`

Because eval defaults:

```python
ctrl_root = control_plane_root or Path.cwd()
```

external-project execution from the target repo will still fail imports unless the operator passes:

```bash
grace eval run ... --control-plane-root /path/to/grace-orchestrator --target-repo-root /path/to/target
```

Document this before using external projects.

---

## Suggested next action

For the current FAST golden, it is reasonable to rerun after local tests because the immediate merge TypeError is fixed.

For self-improvement/admin UI work, fix P0-4/base SHA first or ensure the coder never commits manually. Since self-improvement is high-risk, prefer fixing it before the admin UI task.

---

## Suggested tests

Run:

```bash
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests/api/test_packets_api.py -q
pytest tests/test_worker_merge_payload.py -q
pytest tests -q
```

No CI statuses were attached to `f47d03f`, so I could not independently verify the claimed `181 tests pass` from GitHub.

---

## Final verdict

**PASS FOR GOLDEN. REWORK_REQUIRED BEFORE SELF-IMPROVEMENT/EXTERNAL HARDENING.**

The immediate merge payload runtime break is fixed. The remaining issue is base-ref correctness for already-committed worktree changes and fully portable external/self-improvement runs.
