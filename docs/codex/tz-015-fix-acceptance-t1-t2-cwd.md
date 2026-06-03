# TZ 015 — Fix acceptance T1/T2 command cwd: run verification in packet worktree

Audience: Flash coder / literal executor.

## Problem

Golden smoke now proves the agent works, but deterministic acceptance rejects the packet.

Observed flow:

```text
YAML: FAST, sandbox/golden/live_001/, t0: [], t1: pytest
Agent: ok=true, domain_status=accepted
Agent created files in packet worktree
T0: passed
T1: failed 3/3 attempts
Result: rejected
```

Root cause:

```text
T1 verification command runs from project root / wrong cwd,
while agent-created files exist in packet worktree.
```

The command:

```bash
python3 -m pytest sandbox/golden/live_001/test_date_util.py -q
```

must run from:

```text
packet_worktree_path
```

not from the main project root or control-plane cwd.

This is a pipeline bug, not an agent bug and not a golden YAML bug.

---

## Current failing shape

`run_acceptance_pipeline(...)` receives `worktree_path`.

`AcceptancePipeline.run(...)` computes:

```python
worktree_root = Path(worktree_path) if worktree_path else self._root
```

But then T1/T2 call:

```python
t1_result = self._run_t1(packet, run_dir=run_dir_t1)
t2_result = self._run_t2(packet, run_dir=run_dir_t2)
```

And `_run_t1/_run_t2` call:

```python
self._runner.run(cmd, output_dir=run_dir)
```

without passing `cwd=worktree_root`.

Depending on how `CommandRunner` is constructed and how tests are mocked, this can make T1/T2 run from the wrong root.

---

## Required behavior

All deterministic packet verification commands must run from the packet worktree:

```text
T0 commands cwd = packet_worktree_path
T1 commands cwd = packet_worktree_path
T2 commands cwd = packet_worktree_path
```

Scope guard and expected evidence already use `worktree_path`; command execution must follow the same rule.

---

## Files to change

```text
src/grace_control/core/acceptance_pipeline.py
tests/grace_control/core/test_acceptance_pipeline.py
```

Do not change golden YAML.
Do not weaken scope guard.
Do not skip T1.
Do not make FAST skip T1 when T1 commands are present.

---

## Required implementation

### 1. Pass worktree cwd into T1

Change `_run_t1` signature from:

```python
def _run_t1(self, packet: ExecutionPacketContract, *, run_dir: Path | None = None) -> StageResult:
```

to:

```python
def _run_t1(
    self,
    packet: ExecutionPacketContract,
    *,
    run_dir: Path | None = None,
    cwd: Path | None = None,
) -> StageResult:
```

Change command execution from:

```python
commands = [self._runner.run(cmd, output_dir=run_dir) for cmd in cmds]
```

to:

```python
commands = [self._runner.run(cmd, output_dir=run_dir, cwd=cwd) for cmd in cmds]
```

---

### 2. Pass worktree cwd into T2

Change `_run_t2` signature from:

```python
def _run_t2(self, packet: ExecutionPacketContract, *, run_dir: Path | None = None) -> StageResult:
```

to:

```python
def _run_t2(
    self,
    packet: ExecutionPacketContract,
    *,
    run_dir: Path | None = None,
    cwd: Path | None = None,
) -> StageResult:
```

Change command execution from:

```python
commands = [self._runner.run(cmd, output_dir=run_dir) for cmd in cmds]
```

to:

```python
commands = [self._runner.run(cmd, output_dir=run_dir, cwd=cwd) for cmd in cmds]
```

---

### 3. Pass `worktree_root` from `run()`

In `AcceptancePipeline.run(...)`, change:

```python
t1_result = self._run_t1(packet, run_dir=run_dir_t1)
```

to:

```python
t1_result = self._run_t1(packet, run_dir=run_dir_t1, cwd=worktree_root)
```

Change:

```python
t2_result = self._run_t2(packet, run_dir=run_dir_t2)
```

to:

```python
t2_result = self._run_t2(packet, run_dir=run_dir_t2, cwd=worktree_root)
```

T0 should also continue to use worktree root. If T0 currently relies on `CommandRunner(worktree_path)`, that is acceptable, but passing cwd explicitly is also fine:

```python
self._runner.run(cmd, output_dir=output_dir, cwd=worktree_root)
```

Only do this if it stays small and does not break existing tests.

---

## Tests required

Add tests in:

```text
tests/grace_control/core/test_acceptance_pipeline.py
```

### Test 1 — T1 command cwd is worktree

Use a fake command runner that records each call:

```python
class RecordingRunner:
    calls = []
    def run(self, cmd, *, output_dir=None, cwd=None, timeout_s=None):
        self.calls.append({"cmd": cmd, "cwd": cwd, "output_dir": output_dir})
        return CommandResult(command="...", cwd=str(cwd), exit_code=0)
```

Setup:

```text
project_root = tmp/project
worktree_path = tmp/worktree
packet.verification.t0 = []
packet.verification.t1 = ["python3 -m pytest sandbox/golden/live_001/test_date_util.py -q"]
packet.verification.t2 = []
acceptance_profile = FAST or NORMAL
changed_files = ["sandbox/golden/live_001/date_util.py", "sandbox/golden/live_001/test_date_util.py"]
```

Assert:

```text
T1 runner call cwd == worktree_path
T1 runner call cwd != project_root
```

---

### Test 2 — T2 command cwd is worktree

Setup STRICT profile with:

```text
verification.t2 = ["python3 -m pytest tests -q"]
```

Assert:

```text
T2 runner call cwd == worktree_path
```

---

### Test 3 — Golden-style file exists only in worktree and T1 passes

Use real command runner if safe, or fake runner with cwd check.

Create file only here:

```text
<worktree>/sandbox/golden/live_001/test_date_util.py
```

Do not create it in project root.

Run acceptance with golden-style command:

```bash
python3 -m pytest sandbox/golden/live_001/test_date_util.py -q
```

Assert:

```text
acceptance final_verdict == accepted
T1 stage passed
```

If real pytest is too heavy for unit tests, use:

```bash
python3 -c "import pathlib; assert pathlib.Path('sandbox/golden/live_001/test_date_util.py').exists()"
```

but keep one test that proves cwd is worktree.

---

### Test 4 — FAST does not skip configured T1

Ensure FAST still runs T1 when T1 commands are provided.

Setup:

```text
acceptance_profile = FAST
verification.t1 = ["python3 -c 'print(123)'"]
```

Assert:

```text
runner called for T1
T1 stage passed
```

This prevents accidental workaround by skipping T1 for FAST.

---

## Acceptance criteria

Done only if:

1. T1 commands run with cwd = packet worktree.
2. T2 commands run with cwd = packet worktree.
3. FAST still runs T1 if T1 commands are configured.
4. Golden-style test file only in worktree can be found by T1 command.
5. Existing acceptance/profile tests still pass.
6. Golden smoke can be rerun and should no longer fail because pytest cannot find `sandbox/golden/live_001/test_date_util.py`.

---

## Tests to run

```bash
pytest tests/grace_control/core/test_acceptance_pipeline.py -q
pytest tests/grace_control/adapters/test_packet_executor_acceptance.py -q
pytest tests -q
```

Then rerun golden:

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
  --control-plane-root "$PWD" \
  --target-repo-root "$PWD" \
  --state-root /tmp/grace-eval/golden-smoke-live-001/state \
  --worktree-root /tmp/grace-eval/golden-smoke-live-001/worktrees \
  --base-ref HEAD \
  --report /tmp/grace-eval/golden-smoke-live-001/report.json
```
