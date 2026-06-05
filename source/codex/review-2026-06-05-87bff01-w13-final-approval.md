# Review: `87bff01` W13 final approval

Date: 2026-06-05
Reviewed commit: `87bff01175817c452d2131e84c2e8ee60a778c21`
Previous review: `source/codex/review-2026-06-05-72a0e5e-w13-final-followup.md`

## Verdict

Approved.

This closes the last W13 cleanup blocker from the previous review. The generated `agents/llm_*` artifacts are no longer present in the repository tree, `.gitignore` now ignores `agents/`, and UniversalCliAgentBackend no longer falls back to repository root for `state_root` when `session_dir` is absent.

The W0-W13 cleanup/refactor/audit program can now be considered complete.

---

## Checked items

### 1. Generated `agents/llm_*` artifacts are no longer tracked

Accepted.

A direct fetch for a previously committed artifact path such as:

```text
agents/llm_architect_1eb971/EXECUTION_PACKET.md
```

now returns `404 Not Found`. This confirms the generated runtime artifact is no longer present in the repository tree.

### 2. `.gitignore` prevents re-adding agent runtime artifacts

Accepted.

`.gitignore` now contains:

```gitignore
agents/
```

This prevents local UniversalCliAgentBackend fallback artifacts from being accidentally committed again.

### 3. UniversalCliAgentBackend fallback state root no longer defaults to repo cwd

Accepted.

`UniversalCliAgentBackend.run()` now calls `AgentRunService.run(...)` with:

```python
state_root=request.session_dir or (Path(request.worktree_path) if request.worktree_path else Path("."))
```

Instead of the previous:

```python
state_root=request.session_dir or Path(".")
```

So when direct `run_llm()` tests pass `cwd=tmp_path`, generated fallback artifacts are created under that temporary worktree path, not under the repository root.

### 4. W13 tests now use `monkeypatch` for PATH

Accepted.

`tests/grace_control/core/test_llm_runner.py` now uses:

```python
monkeypatch.setenv("PATH", ...)
```

rather than mutating `os.environ` directly. This avoids cross-test leakage.

### 5. `llm_runner.py` remains profile-backed

Accepted from the previous follow-up state.

The W13 path now has the intended shape:

```text
run_llm()
  -> get_agent_profile(cli/executor_id)
  -> UniversalCliAgentBackend
  -> AgentRunService
  -> ProcessSupervisor
```

No hardcoded `opencode` / `agy` command construction remains in `llm_runner.py`.

---

## Final status

```text
W0-W13: accepted
Test suite: reported 405 passed, 0 failed
Runtime artifacts: not tracked
GRACE API/OpenAPI: control plane
UniversalCliAgentBackend: execution adapter
Legacy Prefect: removed from runtime package
Public GRACE CLI: removed as control plane
GraceLint/canon/docs: aligned enough for this phase
```

## Remaining future work, not part of W0-W13

Potential next phase items:

```text
- security/auth for remote API use
- UI polish for executor/profile/stage/artifacts visibility
- further readability split for packet_executor/evidence_service if desired
- operational runbooks for local CLI agent profiles
- CI job to run full pytest + GraceLint + docs-check on main
```

No blocker remains for closing the W0-W13 refactor/audit loop.
