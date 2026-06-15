# W06 — Process Supervisor and Command Runner Hardening

Status: READY

Parent TZ: `docs/work/TZ_GRACE_ORCHESTRATOR_RUNTIME_SCOPE_CONTEXT_HARDENING.md`

## Goal

Prevent infinite subprocess hangs and remove unsafe or misleading shell execution behavior.

## Scope

- `src/grace_control/core/process_supervisor.py`
- `src/grace_control/core/command_runner.py`
- `src/grace_control/services/acceptance_pipeline.py`
- `tests/`

## Tasks

1. Enforce one timeout budget for process execution.
2. Bound `proc.wait()` after stream reads.
3. On timeout, kill process group and wait with bounded timeout.
4. Capture partial stdout/stderr on timeout.
5. Add diagnostics: `timed_out`, `killed_pgid`, `wait_after_kill_timed_out`, `duration_ms`, command preview.
6. Make `CommandRunner` no-shell by default, or make shell use explicit and documented.
7. Ensure shell commands cannot leave child processes running after timeout.

## Acceptance

- Process supervisor cannot hang forever.
- Timeout kills the whole process group.
- Partial logs are preserved.
- Command runner behavior matches its contract.
- Shell mode is explicit and tested.

## Required tests

- `test_process_supervisor_wait_after_stream_has_timeout`
- `test_process_supervisor_kills_process_group_on_timeout`
- `test_process_supervisor_returns_partial_output_on_timeout`
- `test_command_runner_no_shell_by_default_or_explicit_shell_only`
- `test_shell_command_timeout_kills_child_process`

## Submission

Create `docs/work/Feat_1/exchange/inbox/W06_001_SUBMISSION.md` when done.
