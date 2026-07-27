# AI_HEADER: process_supervisor — spawn subprocess, capture I/O, enforce timeout, kill process group.
#           Supports stdin input mode for W7.
# W06: Hardened — bounded wait after kill, partial output capture on timeout,
#      diagnostics fields (killed_pgid, wait_after_kill_timed_out, command_preview).
# START_MODULE_CONTRACT
# purpose: Run a CLI command as a subprocess with inactivity timeout and
#          process-group cleanup. Captures stdout/stderr/exit_code.
#          Optionally sends stdin_text to process stdin.
#          Never leaves orphan processes.
# inputs: command list, cwd, env, timeout_seconds (inactivity window),
#         stdin_text (optional), progress_paths (optional), hard_timeout_seconds.
# returns: ProcessResult with stdout, stderr, exit_code, duration_ms, timed_out,
#          killed_pgid, wait_after_kill_timed_out, command_preview, timeout_reason.
# side_effects: Spawns and kills subprocess.
# error_behavior: Timeout kills process group; FileNotFoundError captured.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - class: ProcessSupervisor   - class: ProcessResult
# END_MODULE_MAP

from __future__ import annotations
import asyncio, os, signal, subprocess, time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


# W06: Maximum time to wait for process to exit after SIGKILL.
# If the process still hasn't exited after this, we report
# wait_after_kill_timed_out=True and return partial results.
_KILL_WAIT_TIMEOUT_S = 5


@dataclass
class ProcessResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    duration_ms: int = 0
    timed_out: bool = False
    # W06: Diagnostics
    killed_pgid: int | None = None
    wait_after_kill_timed_out: bool = False
    command_preview: str = ""
    timeout_reason: str = ""


def playwright_install_browsers(cwd: Path | str | None = None) -> bool:
    """Idempotent: install Playwright Chromium for headless tests.

    TZ_FRONTEND_ACCEPTANCE P1/3.4 — called before browser stages.
    Skips if already installed. Returns True if ready, False on failure.
    """
    import shutil
    if shutil.which("npx") is None:
        return False
    try:
        # Check if already installed
        r = subprocess.run(
            ["npx", "playwright", "chromium", "--version"],
            capture_output=True, text=True, timeout=10,
            cwd=str(cwd) if cwd else None,
        )
        if r.returncode == 0:
            return True  # already installed
    except Exception:
        pass
    # Install
    try:
        r = subprocess.run(
            ["npx", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=120,
            cwd=str(cwd) if cwd else None,
        )
        return r.returncode == 0
    except Exception:
        return False


async def _read_stream_to_buf(
    stream,
    buf: list[bytes],
    log_path: Path | None = None,
    on_progress: Callable[[], None] | None = None,
):
    """Read stream chunks, preserving partial output and reporting progress."""
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        buf.append(chunk)
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "ab") as f:
                f.write(chunk)
        if on_progress:
            on_progress()


def _progress_signature(paths: Iterable[Path | str]) -> tuple[tuple[str, int, int], ...]:
    """Return a cheap mtime/size snapshot for explicit progress paths.

    Directory paths are scanned one level deep.  Agent output and trajectory
    files live directly in the run directory, while recursive scans of a
    whole checkout would add needless load during long test runs.
    """
    signature: list[tuple[str, int, int]] = []
    for raw_path in paths:
        path = Path(raw_path)
        try:
            if path.is_file():
                stat = path.stat()
                signature.append((str(path), stat.st_mtime_ns, stat.st_size))
            elif path.is_dir():
                for child in path.iterdir():
                    try:
                        stat = child.stat()
                    except OSError:
                        continue
                    signature.append((str(child), stat.st_mtime_ns, stat.st_size))
        except OSError:
            continue
    return tuple(sorted(signature))


class ProcessSupervisor:
    async def run(self, command: list[str], cwd: Path | str, env: dict[str, str] | None = None,
                  timeout_seconds: int = 600, stdin_text: str | None = None,
                  stdout_log_path: Path | str | None = None,
                  stderr_log_path: Path | str | None = None,
                  progress_paths: Iterable[Path | str] | None = None,
                  hard_timeout_seconds: int | None = None) -> ProcessResult:
        t0 = time.time()
        monotonic_t0 = time.monotonic()
        # W06: Command preview for diagnostics (first 200 chars)
        cmd_preview = " ".join(command)[:200]

        # GRACE_FAST_FAIL: cap all timeouts at 60s for dev/test so failures
        # surface immediately instead of hanging for 10+ minutes.
        _effective_timeout = timeout_seconds
        if os.environ.get("GRACE_FAST_FAIL"):
            _effective_timeout = min(timeout_seconds, 60)
        configured_hard_timeout = hard_timeout_seconds
        if configured_hard_timeout is None:
            configured_hard_timeout = int(os.environ.get(
                "GRACE_AGENT_MAX_TIMEOUT", str(max(3600, _effective_timeout))))
        _effective_hard_timeout = max(_effective_timeout, configured_hard_timeout)
        if os.environ.get("GRACE_FAST_FAIL"):
            _effective_hard_timeout = min(_effective_hard_timeout, 60)
        progress_paths = tuple(progress_paths or ())
        proc_env = dict(os.environ) if env is None else dict(env)
        proc_env["PWD"] = str(cwd)

        # preexec: new session + high oom_score_adj so the OOM killer
        # targets this subprocess, not the API/worker.
        def _preexec():
            os.setsid()
            try:
                with open("/proc/self/oom_score_adj", "w") as f:
                    f.write("1000\n")
            except OSError:
                pass

        try:
            stdin_pipe = asyncio.subprocess.PIPE if stdin_text is not None else None
            proc = await asyncio.create_subprocess_exec(
                *command, cwd=str(cwd), env=proc_env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                stdin=stdin_pipe, preexec_fn=_preexec,
            )

            # W06: Always use incremental stream reading so partial output
            # is available on timeout, regardless of whether log paths are set.
            _stdout_buf: list[bytes] = []
            _stderr_buf: list[bytes] = []
            stdout_log = Path(stdout_log_path) if stdout_log_path else None
            stderr_log = Path(stderr_log_path) if stderr_log_path else None
            last_progress = time.monotonic()
            progress_snapshot = _progress_signature(progress_paths)

            def _mark_progress() -> None:
                nonlocal last_progress
                last_progress = time.monotonic()

            # Write stdin_text before reading stdout/stderr
            if stdin_text and proc.stdin:
                in_data = stdin_text.encode("utf-8", "ignore")
                proc.stdin.write(in_data)
                await proc.stdin.drain()
                proc.stdin.close()

            try:
                readers = []
                if proc.stdout:
                    readers.append(asyncio.create_task(
                        _read_stream_to_buf(proc.stdout, _stdout_buf, stdout_log, _mark_progress)))
                if proc.stderr:
                    readers.append(asyncio.create_task(
                        _read_stream_to_buf(proc.stderr, _stderr_buf, stderr_log, _mark_progress)))

                timeout_reason = ""
                while True:
                    if progress_paths:
                        current_snapshot = _progress_signature(progress_paths)
                        if current_snapshot != progress_snapshot:
                            progress_snapshot = current_snapshot
                            _mark_progress()
                    if proc.returncode is not None and all(task.done() for task in readers):
                        break
                    now = time.monotonic()
                    if now - last_progress >= _effective_timeout:
                        timeout_reason = f"inactivity timeout after {_effective_timeout}s"
                        raise asyncio.TimeoutError
                    if now - monotonic_t0 >= _effective_hard_timeout:
                        timeout_reason = f"hard timeout after {_effective_hard_timeout}s"
                        raise asyncio.TimeoutError
                    await asyncio.sleep(min(1.0, max(0.05, _effective_timeout / 20)))

                # W06: Bounded wait after stream reads — proc should already
                # have exited since streams closed, but bound it anyway.
                await asyncio.wait_for(proc.wait(), timeout=_KILL_WAIT_TIMEOUT_S)
                duration_ms = int((time.time() - t0) * 1000)
                return ProcessResult(
                    stdout=b"".join(_stdout_buf).decode("utf-8", "ignore") if _stdout_buf else "",
                    stderr=b"".join(_stderr_buf).decode("utf-8", "ignore") if _stderr_buf else "",
                    exit_code=proc.returncode or 0, duration_ms=duration_ms,
                    command_preview=cmd_preview,
                )
            except asyncio.TimeoutError:
                # W06: Kill process group and capture partial output
                killed_pgid = None
                wait_after_kill_timed_out = False

                # 1. Kill the process group
                try:
                    pgid = os.getpgid(proc.pid)
                    killed_pgid = pgid
                    os.killpg(pgid, signal.SIGKILL)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

                # 2. Bounded wait after kill — don't hang forever
                try:
                    await asyncio.wait_for(proc.wait(), timeout=_KILL_WAIT_TIMEOUT_S)
                except asyncio.TimeoutError:
                    wait_after_kill_timed_out = True

                # 3. Partial output is already captured in _stdout_buf/_stderr_buf
                #    from the incremental stream reading.
                #    Also try reading any remaining data from the streams.
                try:
                    if proc.stdout:
                        try:
                            remaining = await asyncio.wait_for(proc.stdout.read(), timeout=1.0)
                            if remaining:
                                _stdout_buf.append(remaining)
                        except Exception:
                            pass
                except Exception:
                    pass

                for task in readers:
                    if not task.done():
                        task.cancel()
                if readers:
                    await asyncio.gather(*readers, return_exceptions=True)
                try:
                    if proc.stderr:
                        try:
                            remaining = await asyncio.wait_for(proc.stderr.read(), timeout=1.0)
                            if remaining:
                                _stderr_buf.append(remaining)
                        except Exception:
                            pass
                except Exception:
                    pass

                # Also try reading from log files if they were being written
                partial_stdout = b"".join(_stdout_buf).decode("utf-8", "ignore") if _stdout_buf else ""
                partial_stderr = b"".join(_stderr_buf).decode("utf-8", "ignore") if _stderr_buf else ""

                if not partial_stdout and stdout_log:
                    try:
                        partial_stdout = stdout_log.read_text()[:100000]
                    except Exception:
                        pass
                if not partial_stderr and stderr_log:
                    try:
                        partial_stderr = stderr_log.read_text()[:100000]
                    except Exception:
                        pass

                duration_ms = int((time.time() - t0) * 1000)
                return ProcessResult(
                    timed_out=True,
                    stdout=partial_stdout,
                    stderr=partial_stderr or f"Timed out after {_effective_timeout}s",
                    exit_code=-1,
                    duration_ms=duration_ms,
                    killed_pgid=killed_pgid,
                    wait_after_kill_timed_out=wait_after_kill_timed_out,
                    command_preview=cmd_preview,
                    timeout_reason=timeout_reason or f"inactivity timeout after {_effective_timeout}s",
                )
        except FileNotFoundError:
            return ProcessResult(
                stderr=f"Command not found: {command[0]}",
                duration_ms=int((time.time() - t0) * 1000),
                command_preview=cmd_preview,
            )
