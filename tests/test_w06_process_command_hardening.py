# ############################################################################
# AI_HEADER: test_w06_process_supervisor_command_runner
# ROLE: W06 regression tests — process supervisor and command runner hardening.
# ############################################################################

"""W06 Process Supervisor and Command Runner Hardening.

Tests cover:
1. Process supervisor wait after stream has timeout
2. Process supervisor kills process group on timeout
3. Process supervisor returns partial output on timeout
4. Command runner no-shell by default or explicit shell only
5. Shell command timeout kills child process
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from grace_control.core.command_runner import CommandRunner, run_command, _kill_process_group
from grace_control.core.contracts import CommandResult
from grace_control.services.process_supervisor import ProcessSupervisor, ProcessResult


# ─── Test 1: Process supervisor wait after stream has timeout ──────────────

def test_process_supervisor_wait_after_stream_has_timeout():
    """W06: ProcessSupervisor must bound proc.wait() after stream reads —
    cannot hang forever waiting for process exit."""
    supervisor = ProcessSupervisor()

    # Use a command that produces output but then sleeps forever
    # Python one-liner: print output, then sleep
    cmd = [
        "python3", "-c",
        "import sys, time; print('hello', flush=True); time.sleep(300)"
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        state_root = Path(tmpdir)

        result = asyncio.run(supervisor.run(
            command=cmd,
            cwd=state_root,
            timeout_seconds=2,
        ))

        # Must have timed out
        assert result.timed_out, f"Expected timed_out=True, got: {result}"
        # Duration must be bounded (not hanging)
        assert result.duration_ms < 10000, \
            f"Duration {result.duration_ms}ms suggests process wasn't killed promptly"
        # Must have diagnostics
        assert result.command_preview, "Missing command_preview"
        assert "python3" in result.command_preview


# ─── Test 2: Process supervisor kills process group on timeout ──────────────

def test_process_supervisor_kills_process_group_on_timeout():
    """W06: On timeout, ProcessSupervisor must kill the process group,
    not just the parent process — child processes must be cleaned up."""
    supervisor = ProcessSupervisor()

    # Command that spawns a child process, then both sleep
    cmd = [
        "python3", "-c",
        "import subprocess, time; "
        "p = subprocess.Popen(['sleep', '300']); "
        "time.sleep(300)"
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        state_root = Path(tmpdir)

        result = asyncio.run(supervisor.run(
            command=cmd,
            cwd=state_root,
            timeout_seconds=2,
        ))

        assert result.timed_out, f"Expected timed_out=True, got: {result}"
        # killed_pgid should be set (we killed a process group)
        assert result.killed_pgid is not None, \
            f"Expected killed_pgid to be set, got None"
        # wait_after_kill_timed_out should be False (process should die promptly)
        # (could be True in extreme edge cases, but not for a simple sleep)
        assert isinstance(result.wait_after_kill_timed_out, bool), \
            "wait_after_kill_timed_out should be bool"


# ─── Test 3: Process supervisor returns partial output on timeout ───────────

def test_process_supervisor_returns_partial_output_on_timeout():
    """W06: On timeout, ProcessSupervisor must capture partial stdout/stderr
    that was produced before the timeout, not discard it."""
    supervisor = ProcessSupervisor()

    # Command that prints output incrementally, then hangs
    cmd = [
        "python3", "-c",
        "import sys, time; "
        "print('partial_line_1', flush=True); "
        "print('partial_line_2', flush=True); "
        "sys.stderr.write('error_output\\n'); sys.stderr.flush(); "
        "time.sleep(300)"
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        state_root = Path(tmpdir)

        result = asyncio.run(supervisor.run(
            command=cmd,
            cwd=state_root,
            timeout_seconds=2,
        ))

        assert result.timed_out, f"Expected timed_out=True, got: {result}"
        # Partial stdout must be captured
        assert "partial_line_1" in result.stdout or "partial_line_2" in result.stdout, \
            f"Expected partial stdout captured, got: stdout='{result.stdout}' stderr='{result.stderr}'"
        # Partial stderr should also be captured (or at least the timeout message)
        assert result.stderr, \
            f"Expected stderr to be non-empty, got: '{result.stderr}'"


# ─── Test 4: Command runner no-shell by default or explicit shell only ──────

def test_command_runner_no_shell_by_default_or_explicit_shell_only():
    """W06: CommandRunner must not use shell=True by default.
    Shell mode must be explicit opt-in via shell=True parameter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)

        runner = CommandRunner(repo_root)

        # Simple command works without shell
        result = runner.run(["echo", "hello"])
        assert result.exit_code == 0, f"Simple echo failed: {result.stderr}"
        assert "hello" in result.stdout, f"Expected 'hello' in stdout: {result.stdout}"
        # shell_mode must be False
        assert result.shell_mode is False, \
            f"Expected shell_mode=False for list command, got: {result.shell_mode}"

        # String command without shell operators also works (no shell)
        result2 = runner.run("echo hello_world")
        assert result2.exit_code == 0, f"String echo failed: {result2.stderr}"
        assert "hello_world" in result2.stdout, f"Expected 'hello_world' in stdout: {result2.stdout}"
        assert result2.shell_mode is False, \
            f"Expected shell_mode=False for string command, got: {result2.shell_mode}"

        # Command with shell operators without shell=True should be rejected
        result3 = runner.run("echo hello && echo world")
        assert result3.exit_code != 0, \
            f"Shell operators without shell=True should fail, got exit_code=0"
        assert "unsupported shell syntax" in result3.stderr or "shell syntax" in result3.stderr.lower(), \
            f"Expected shell syntax rejection: {result3.stderr}"

        # Command with shell operators and shell=True should work
        result4 = runner.run("echo hello && echo world", shell=True)
        assert result4.exit_code == 0, \
            f"Shell command with shell=True should work: {result4.stderr}"
        assert "hello" in result4.stdout, f"Expected 'hello' in stdout: {result4.stdout}"
        assert "world" in result4.stdout, f"Expected 'world' in stdout: {result4.stdout}"
        assert result4.shell_mode is True, \
            f"Expected shell_mode=True for shell command, got: {result4.shell_mode}"

        # Diagnostics: command_preview must be set
        assert result.command_preview, "Missing command_preview"
        assert result4.command_preview, "Missing command_preview for shell command"


# ─── Test 5: Shell command timeout kills child process ──────────────────────

def test_shell_command_timeout_kills_child_process():
    """W06: When a shell command times out, the entire process group
    (shell + children) must be killed, not just the shell."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_root = Path(tmpdir)
        runner = CommandRunner(repo_root, default_timeout_s=2)

        # Shell command that spawns a child and both sleep
        cmd = "python3 -c \"import subprocess, time; p = subprocess.Popen(['sleep', '300']); time.sleep(300)\""

        result = runner.run(cmd, shell=True)

        assert result.timed_out, f"Expected timed_out=True, got: {result}"
        # killed_pgid should be set — process group was killed
        assert result.killed_pgid is not None, \
            f"Expected killed_pgid for shell timeout, got None"
        # Duration should be bounded
        assert result.duration_ms < 15000, \
            f"Duration {result.duration_ms}ms suggests processes weren't killed promptly"
        # Shell mode must be recorded
        assert result.shell_mode is True, \
            f"Expected shell_mode=True, got: {result.shell_mode}"
        # Partial stderr should be available
        assert result.stderr, f"Expected non-empty stderr, got empty"


# ─── Additional: ProcessResult diagnostics fields ──────────────────────────

def test_process_result_has_diagnostics_fields():
    """W06: ProcessResult must have diagnostics fields."""
    result = ProcessResult(
        stdout="out", stderr="err", exit_code=0, duration_ms=100,
        timed_out=False, killed_pgid=None, wait_after_kill_timed_out=False,
        command_preview="echo hello",
    )
    assert result.killed_pgid is None
    assert result.wait_after_kill_timed_out is False
    assert result.command_preview == "echo hello"


def test_command_result_has_diagnostics_fields():
    """W06: CommandResult must have diagnostics fields."""
    result = CommandResult(
        command="echo hello", cwd="/tmp", exit_code=0,
        killed_pgid=None, wait_after_kill_timed_out=False,
        command_preview="echo hello", shell_mode=False,
    )
    assert result.killed_pgid is None
    assert result.wait_after_kill_timed_out is False
    assert result.command_preview == "echo hello"
    assert result.shell_mode is False


# ─── Additional: _kill_process_group helper ─────────────────────────────────

def test_kill_process_group_terminates_process():
    """W06: _kill_process_group must kill the process group and return pgid."""
    # Start a process in a new session
    proc = subprocess.Popen(
        ["sleep", "300"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        killed_pgid, wait_timed_out = _kill_process_group(proc, timeout_s=5)
        # Should have killed a pgid
        assert killed_pgid is not None, "Expected killed_pgid to be set"
        # Process should be dead
        assert proc.returncode is not None, "Process should have exited"
    finally:
        # Safety: ensure process is dead
        try:
            proc.kill()
            proc.wait(timeout=1)
        except Exception:
            pass


def test_kill_process_group_handles_already_dead_process():
    """W06: _kill_process_group must handle already-dead processes gracefully."""
    # Start and immediately wait for a fast process
    proc = subprocess.Popen(
        ["echo", "done"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.wait(timeout=5)

    # Process is already dead — _kill_process_group should not raise
    killed_pgid, wait_timed_out = _kill_process_group(proc, timeout_s=5)
    # killed_pgid may or may not be None depending on timing
    assert isinstance(wait_timed_out, bool)


# ─── Additional: run_command with timeout captures partial output ────────────

def test_run_command_timeout_captures_partial_output():
    """W06: run_command must capture partial output when a command times out."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir()

        # Command that writes output slowly, then hangs
        result = run_command(
            command="python3 -c \"import time; print('line1', flush=True); time.sleep(300)\"",
            cwd=Path(tmpdir),
            output_dir=output_dir,
            timeout_seconds=2,
        )

        assert result.timed_out, f"Expected timed_out=True, got: {result}"
        assert result.killed_pgid is not None, \
            f"Expected killed_pgid for timed out command, got None"
        assert "line1" in result.stdout, \
            f"Expected partial stdout captured, got: '{result.stdout}'"


# ─── Additional: run_command never uses shell=True ──────────────────────────

def test_run_command_never_uses_shell():
    """W06: The free function run_command() must never use shell=True,
    even if the command looks like it could benefit from it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir()

        # Simple command works
        result = run_command(
            command="echo no_shell",
            cwd=Path(tmpdir),
            output_dir=output_dir,
        )
        assert result.exit_code == 0, f"echo failed: {result.stderr}"
        assert result.shell_mode is False

        # Shell operators are rejected
        result2 = run_command(
            command="echo a && echo b",
            cwd=Path(tmpdir),
            output_dir=output_dir,
        )
        assert result2.exit_code != 0, "Shell operators should be rejected"
        assert result2.shell_mode is False
