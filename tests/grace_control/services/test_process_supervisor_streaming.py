"""Live streaming tests for ProcessSupervisor."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from grace_control.services.process_supervisor import ProcessSupervisor


@pytest.mark.asyncio
async def test_streaming_writes_log_file_during_run(tmp_path: Path) -> None:
    """ProcessSupervisor writes to log file incrementally during a slow process."""
    sup = ProcessSupervisor()
    stdout_log = tmp_path / "stdout.log"

    # A script that prints 3 lines with 0.1s delay between each
    script = """
import sys, time
for i in range(3):
    print(f"line {i}", flush=True)
    time.sleep(0.1)
"""
    result = await sup.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        timeout_seconds=10,
        stdout_log_path=stdout_log,
    )

    assert result.stdout.strip() == "line 0\nline 1\nline 2"
    assert stdout_log.exists()
    log_content = stdout_log.read_text()
    assert "line 0" in log_content
    assert "line 1" in log_content
    assert "line 2" in log_content
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_streaming_with_stdin(tmp_path: Path) -> None:
    """Streaming mode handles stdin_text correctly."""
    sup = ProcessSupervisor()
    stdout_log = tmp_path / "stdout.log"

    # Read stdin line by line, uppercase each line, print
    script = """
import sys
for line in sys.stdin:
    print(line.strip().upper(), flush=True)
"""
    result = await sup.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        timeout_seconds=10,
        stdin_text="hello\nworld\n",
        stdout_log_path=stdout_log,
    )

    assert result.stdout.strip() == "HELLO\nWORLD"
    assert stdout_log.exists()
    log_content = stdout_log.read_text()
    assert "HELLO" in log_content
    assert "WORLD" in log_content


@pytest.mark.asyncio
async def test_streaming_both_logs(tmp_path: Path) -> None:
    """Both stdout and stderr are written to separate log files."""
    sup = ProcessSupervisor()
    stdout_log = tmp_path / "stdout.log"
    stderr_log = tmp_path / "stderr.log"

    script = """
import sys
print("stdout line", flush=True)
print("stderr line", file=sys.stderr, flush=True)
"""
    result = await sup.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        timeout_seconds=10,
        stdout_log_path=stdout_log,
        stderr_log_path=stderr_log,
    )

    assert "stdout line" in result.stdout
    assert "stderr line" in result.stderr
    assert stdout_log.read_text().strip() == "stdout line"
    assert stderr_log.read_text().strip() == "stderr line"


@pytest.mark.asyncio
async def test_non_streaming_still_works(tmp_path: Path) -> None:
    """Without log paths, ProcessSupervisor returns stdout/stderr as before."""
    sup = ProcessSupervisor()
    result = await sup.run(
        [sys.executable, "-c", "print('hello')"],
        cwd=tmp_path,
        timeout_seconds=10,
    )
    assert result.stdout.strip() == "hello"
    assert result.exit_code == 0
