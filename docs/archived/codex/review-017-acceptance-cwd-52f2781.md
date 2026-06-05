# Codex Review 017 — Acceptance T1/T2 cwd fix after `52f2781`

Commit reviewed: `52f2781fa362727c5e30c1501930dd0274ff399a`

Spec: `docs/codex/tz-015-fix-acceptance-t1-t2-cwd.md`

Verdict: **PASS — rerun FAST golden.**

The P0 that broke the golden run is fixed: T0/T1/T2 now receive `cwd=worktree_root`, and command runner calls pass that cwd through.

---

## What changed

`AcceptancePipeline.run(...)` now passes `worktree_root` to all deterministic stages:

```python
t0_result = self._run_t0(..., cwd=worktree_root)
t1_result = self._run_t1(packet, run_dir=run_dir_t1, cwd=worktree_root)
t2_result = self._run_t2(packet, run_dir=run_dir_t2, cwd=worktree_root)
```

`_run_t0(...)`, `_run_t1(...)`, `_run_t2(...)` now accept `cwd` and pass it into:

```python
self._runner.run(cmd, output_dir=..., cwd=cwd)
```

This matches the required invariant:

```text
T0/T1/T2 verification commands run inside packet worktree.
```

---

## Golden failure root cause

Previous failing shape:

```text
agent wrote files under packet_worktree_path/sandbox/golden/live_001/
T1 pytest ran from wrong cwd
pytest could not find sandbox/golden/live_001/test_date_util.py
packet rejected after 3 attempts
```

New expected shape:

```text
agent writes files in packet worktree
T1 pytest runs with cwd = packet worktree
pytest sees sandbox/golden/live_001/test_date_util.py
T1 passes
```

This is the right fix. The agent/golden YAML were not the problem.

---

## Tests

Added/updated tests cover:

- T1 receives worktree cwd;
- T2 receives worktree cwd;
- FAST still runs T1 when configured.

These tests are enough to protect the exact regression at the unit level.

P1 hardening later: add one integration-style acceptance test where the file exists only in the worktree and not in project root, using either real `python3 -c` or pytest. That would prove the exact golden-style file lookup end-to-end.

Suggested test name:

```text
test_t1_finds_file_that_exists_only_in_worktree
```

Not a blocker for golden rerun.

---

## Remaining caveat

`AcceptancePipeline` can still be constructed manually with `repo_root=project_root` and no explicit `CommandRunner(worktree_path)`. In that direct-use case, passing `cwd=worktree_path` to a `CommandRunner(project_root)` would fail its safety check because cwd is outside runner root.

Production `run_acceptance_pipeline(...)` constructs:

```python
CommandRunner(worktree_path)
ScopeGuard(worktree_path)
```

so the current managed pipeline is correct. Later, consider making the public class constructor explicit:

```python
AcceptancePipeline(project_root=..., worktree_path=...)
```

or documenting that callers should use `run_acceptance_pipeline(...)`, not instantiate the class directly for worktree runs.

Not a blocker.

---

## Suggested rerun

From a clean repo:

```bash
git pull --ff-only origin main
git status --short
pkill -f "grace api" || true
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
  --control-plane-root "$PWD" \
  --target-repo-root "$PWD" \
  --state-root /tmp/grace-eval/golden-smoke-live-001/state \
  --worktree-root /tmp/grace-eval/golden-smoke-live-001/worktrees \
  --base-ref HEAD \
  --report /tmp/grace-eval/golden-smoke-live-001/report.json
```

---

## Final verdict

**PASS.**

This should unblock the FAST golden rerun. If the next run still fails, the failure should no longer be “pytest cannot find sandbox file from wrong cwd”; inspect merge cleanliness or actual test content next.
