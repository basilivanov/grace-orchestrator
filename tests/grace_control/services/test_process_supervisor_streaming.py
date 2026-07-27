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


@pytest.mark.asyncio
async def test_log_content_visible_mid_run(tmp_path: Path) -> None:
    """Log file has content before the process finishes (mid-run streaming)."""
    sup = ProcessSupervisor()
    stdout_log = tmp_path / "stdout.log"

    # Write 5 lines over 0.5s, check during execution
    script = """
import sys, time
for i in range(5):
    print(f"MID-RUN-{i}", flush=True)
    time.sleep(0.15)
"""
    # Start but don't await yet
    task = asyncio.create_task(sup.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        timeout_seconds=10,
        stdout_log_path=stdout_log,
    ))

    # Wait for first line to appear, then check partial content
    for _ in range(30):
        if stdout_log.exists() and stdout_log.read_text().strip():
            break
        await asyncio.sleep(0.05)

    partial = stdout_log.read_text()
    assert "MID-RUN-0" in partial, "First line should appear before process ends"

    # Wait for at least 3 lines to appear
    for _ in range(30):
        content = stdout_log.read_text()
        if content.count("MID-RUN") >= 3:
            break
        await asyncio.sleep(0.05)

    mid_content = stdout_log.read_text()
    assert mid_content.count("MID-RUN") >= 3, (
        f"Expected >=3 mid-run lines, got: {mid_content.strip()!r}"
    )

    result = await task
    assert result.exit_code == 0
    final = stdout_log.read_text()
    assert final.count("MID-RUN") == 5


@pytest.mark.asyncio
async def test_progress_artifact_extends_inactivity_timeout(tmp_path: Path) -> None:
    """Artifact growth keeps a long-running command alive past idle timeout."""
    sup = ProcessSupervisor()
    progress = tmp_path / "progress.marker"
    script = """
from pathlib import Path
import time
p = Path('progress.marker')
for i in range(4):
    p.write_text(str(i))
    time.sleep(0.35)
"""
    result = await sup.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        timeout_seconds=1,
        hard_timeout_seconds=5,
        progress_paths=[progress],
    )

    assert result.exit_code == 0
    assert not result.timed_out


@pytest.mark.asyncio
async def test_stdout_growth_extends_inactivity_timeout(tmp_path: Path) -> None:
    """Regular stdout proves liveness beyond the inactivity window."""
    sup = ProcessSupervisor()
    script = """
import time
for i in range(4):
    print(i, flush=True)
    time.sleep(0.35)
"""
    result = await sup.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        timeout_seconds=1,
        hard_timeout_seconds=5,
    )

    assert result.exit_code == 0
    assert not result.timed_out
    assert result.stdout.strip().splitlines() == ["0", "1", "2", "3"]


@pytest.mark.asyncio
async def test_hard_timeout_wins_despite_continuous_stdout(tmp_path: Path) -> None:
    """Continuous progress cannot bypass the absolute runtime cap."""
    sup = ProcessSupervisor()
    script = """
import time
while True:
    print("alive", flush=True)
    time.sleep(0.2)
"""
    result = await sup.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        timeout_seconds=1,
        hard_timeout_seconds=2,
    )

    assert result.timed_out
    assert "hard timeout" in result.timeout_reason
    assert "alive" in result.stdout


@pytest.mark.asyncio
async def test_inactivity_timeout_reports_reason(tmp_path: Path) -> None:
    """A silent command is stopped after the inactivity window."""
    sup = ProcessSupervisor()
    result = await sup.run(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        timeout_seconds=1,
        hard_timeout_seconds=5,
    )

    assert result.timed_out
    assert "inactivity timeout" in result.timeout_reason
