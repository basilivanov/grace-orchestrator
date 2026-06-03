# TZ 012 — Acceptance verification commands must run in agent worktree

Audience: Flash coder / literal executor.

## Problem

Golden smoke now reaches the correct FAST sandbox packet, but fails because T1 verification runs from the wrong working directory.

Observed result:

```text
FAILED in 420s
rejected ... ADD-SANDBOX-DATE
Root cause: T1 runs from project root, not worktree. Agent files are in worktree.
```

The agent creates files inside the managed agent worktree, for example:

```text
.grace_worktrees/.../sandbox/golden/live_001/date_util.py
.grace_worktrees/.../sandbox/golden/live_001/test_date_util.py
```

But verification command is executed as if files were in the main repo root:

```bash
python3 -m pytest sandbox/golden/live_001/test_date_util.py -q
```

So pytest cannot see the files created by the agent.

## Required behavior

All deterministic verification commands must run with cwd equal to the agent worktree root:

```text
T0 commands → cwd = worktree_path
T1 commands → cwd = worktree_path
T2 commands → cwd = worktree_path
expected_evidence file/diff checks → worktree_path
scope_guard changed files → worktree_path
```

The main project root may be used for loading orchestration code/config, but never as the cwd for packet verification commands.

## Files to inspect/change

```text
src/grace_control/core/acceptance_pipeline.py
src/grace_control/core/command_runner.py
tests/grace_control/core/test_acceptance_pipeline.py
```

Do not change golden YAML for this bug.
Do not move sandbox paths.
Do not weaken scope guard.
Do not run commands in the main repo root.

## Specific implementation requirement

In `run_acceptance_pipeline(...)`, ensure `AcceptancePipeline` is created so its command runner and scope guard both point at `worktree_path`:

```python
pipe = AcceptancePipeline(
    repo_root=worktree_path,
    command_runner=CommandRunner(worktree_path),
    scope_guard=ScopeGuard(worktree_path),
)
```

If `repo_root=project_root` is still needed for metadata, do not let that affect command cwd.

Current/failing shape to avoid:

```python
AcceptancePipeline(repo_root=project_root, ...)
```

unless every command runner/scope guard call is explicitly forced to worktree cwd.

## Stronger design if needed

If keeping both roots is cleaner, make names explicit:

```python
AcceptancePipeline(
    project_root=project_root,
    worktree_path=worktree_path,
    command_runner=CommandRunner(worktree_path),
    scope_guard=ScopeGuard(worktree_path),
)
```

But keep changes small. The important invariant is:

```text
verification commands execute inside worktree_path
```

## Tests required

### Test 1 — T1 command cwd is worktree

Add test in:

```text
tests/grace_control/core/test_acceptance_pipeline.py
```

Create a temp fake worktree:

```text
<tmp>/worktree/sandbox/golden/live_001/test_date_util.py
```

Run packet with:

```python
verification={
  "t0": [],
  "t1": [["python3", "-m", "pytest", "sandbox/golden/live_001/test_date_util.py", "-q"]],
  "t2": [],
}
allowed_write_scope=["sandbox/golden/live_001/"]
acceptance_profile=FAST or NORMAL
```

Use a fake runner that records the cwd it receives, or a real command if test environment supports python3.

Assert:

```text
T1 command cwd == worktree_path
not project_root
```

### Test 2 — T2 command cwd is worktree

Same idea for `verification.t2` with STRICT profile.

Assert:

```text
T2 command cwd == worktree_path
```

### Test 3 — expected evidence file check uses worktree

Use expected evidence:

```python
expected_evidence=[
  EvidenceRequirement(
    id="sandbox_test_file",
    kind="file",
    required=True,
    pattern="sandbox/golden/live_001/test_date_util.py",
  )
]
```

Create file only inside worktree, not main project root.

Assert acceptance can find it.

### Test 4 — project root artifact pollution does not affect scope guard

Create files in main project root or output path, for example:

```text
artifacts/golden-live-001.json
.grace_state/...
```

But set changed_files from worktree to only:

```text
sandbox/golden/live_001/date_util.py
sandbox/golden/live_001/test_date_util.py
```

Assert scope guard does not report main project root artifacts.

## Acceptance criteria

Done only if:

1. T1/T2 verification commands run with cwd = worktree_path.
2. Expected evidence file checks look inside worktree_path.
3. Scope guard validates changed files from worktree diff, not main repo artifacts.
4. Existing TZ-010/TZ-011 tests still pass.
5. Golden smoke can be rerun without pytest missing sandbox files.

## Commands to run

```bash
pytest tests/grace_control/core/test_acceptance_pipeline.py -q
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests -q
```

Then rerun golden smoke:

```bash
rm -rf .grace_state .grace_worktrees
rm -f /tmp/grace-golden-live.db /tmp/golden-live-001.json

export GRACE_DB_URL=sqlite:////tmp/grace-golden-live.db
export GRACE_AGENT_TIMEOUT=1200
export GRACE_CONTEXT_DISABLED=true

grace api start
```

Second terminal:

```bash
grace eval run grace/features/golden-smoke-live-001.yaml \
  --workers 1 \
  --timeout 1200 \
  --report /tmp/golden-live-001.json
```
