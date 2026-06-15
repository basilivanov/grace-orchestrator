---
feature_id: Feat_1
wave_id: W06
submission_attempt: 1
status: READY_FOR_REVIEW
created_at: 2026-06-16T15:00:00Z
---

# W06 Submission: Process Supervisor and Command Runner Hardening

## Changes

### 1. `ProcessResult` — new diagnostics fields

**File:** `src/grace_control/services/process_supervisor.py`

- Added `killed_pgid: int | None` — process group ID killed on timeout
- Added `wait_after_kill_timed_out: bool` — True if `proc.wait()` after SIGKILL exceeded the bounded kill-wait timeout (5s)
- Added `command_preview: str` — first 200 chars of the command for diagnostics

### 2. `ProcessSupervisor` — hardened timeout and partial output

**File:** `src/grace_control/services/process_supervisor.py`

- **Always use incremental stream reading** — previously, the no-log-path branch used `proc.communicate()` which loses all output on timeout. Now both branches use `_read_stream_to_buf()` so partial output is always captured in `_stdout_buf`/`_stderr_buf` before the timeout fires.
- **Bounded `proc.wait()` after stream reads** — after streams close, `proc.wait()` is called with `_KILL_WAIT_TIMEOUT_S` (5s) timeout to prevent infinite hangs.
- **Process group kill on timeout** — kills the entire process group (via `os.killpg`) and records `killed_pgid`.
- **Bounded wait after kill** — `proc.wait()` after SIGKILL is bounded by `_KILL_WAIT_TIMEOUT_S`; if it still doesn't exit, `wait_after_kill_timed_out=True`.
- **Partial output capture** — on timeout, partial stdout/stderr from incremental buffers is preserved. Also attempts to read remaining data from streams and log files.

### 3. `CommandResult` — new diagnostics fields

**File:** `src/grace_control/core/contracts.py`

- Added `killed_pgid: int | None` — process group ID killed on timeout
- Added `wait_after_kill_timed_out: bool` — True if wait after kill timed out
- Added `command_preview: str` — first 200 chars of the command
- Added `shell_mode: bool` — whether the command was run with `shell=True`

### 4. `CommandRunner` — no-shell by default, explicit shell mode

**File:** `src/grace_control/core/command_runner.py`

- **`run_command()` never uses shell=True** — the free function always runs without shell. Shell operators (`&&`, `||`, `|`, `>`, `<`) are rejected with an error.
- **`CommandRunner.run(shell=False)` by default** — string commands are parsed via `shlex.split()` and run without shell unless `shell=True` is explicitly requested.
- **`_run_shell_command()` — explicit shell mode** — new method for when `shell=True` is explicitly requested. Uses `start_new_session=True` so the entire process tree can be killed on timeout.
- **Process-group kill on timeout** — new `_kill_process_group()` helper kills the process group (children included) with SIGKILL, waits with bounded timeout.
- **Partial output capture on timeout** — reads partial stdout/stderr from log files before returning the timeout result.
- **Diagnostics** — all results include `command_preview`, `shell_mode`, `killed_pgid`, `wait_after_kill_timed_out`.

### 5. `acceptance_pipeline.py` — shell detection

**File:** `src/grace_control/core/acceptance_pipeline.py`

- Added `_SHELL_OPS_PATTERN` regex for detecting shell operators
- Added `AcceptancePipeline._needs_shell(cmd)` static method
- All three call sites (`_run_t0`, `_run_t1`, `_run_t2`) now pass `shell=self._needs_shell(cmd)` to `CommandRunner.run()`
- This ensures architect-provided commands with shell operators (`&&`, `||`, `|`) are run with explicit shell=True, while simple commands remain no-shell.

### 6. Tests

**File:** `tests/test_w06_process_command_hardening.py` — 11 tests:

| Test | Description |
|------|-------------|
| `test_process_supervisor_wait_after_stream_has_timeout` | proc.wait() after stream reads has bounded timeout |
| `test_process_supervisor_kills_process_group_on_timeout` | kills process group on timeout, reports killed_pgid |
| `test_process_supervisor_returns_partial_output_on_timeout` | captures partial stdout/stderr before timeout |
| `test_command_runner_no_shell_by_default_or_explicit_shell_only` | default is no-shell, shell is explicit opt-in |
| `test_shell_command_timeout_kills_child_process` | shell command timeout kills process group (shell + children) |
| `test_process_result_has_diagnostics_fields` | ProcessResult has killed_pgid, wait_after_kill_timed_out, command_preview |
| `test_command_result_has_diagnostics_fields` | CommandResult has killed_pgid, wait_after_kill_timed_out, command_preview, shell_mode |
| `test_kill_process_group_terminates_process` | _kill_process_group helper kills process group |
| `test_kill_process_group_handles_already_dead_process` | _kill_process_group handles dead processes gracefully |
| `test_run_command_timeout_captures_partial_output` | run_command captures partial output on timeout |
| `test_run_command_never_uses_shell` | run_command() never uses shell=True |

## Acceptance Checklist

- [x] Process supervisor cannot hang forever — bounded `proc.wait()` and bounded kill-wait
- [x] Timeout kills the whole process group — `os.killpg()` + `start_new_session=True`
- [x] Partial logs are preserved — incremental stream reading captures output before timeout
- [x] Command runner behavior matches its contract — no-shell default, explicit shell opt-in
- [x] Shell mode is explicit and tested — `shell=True` parameter, `shell_mode` field in result
