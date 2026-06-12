# AI_HEADER: process_supervisor — spawn subprocess, capture I/O, enforce timeout, kill process group.
#           Supports stdin input mode for W7.
# START_MODULE_CONTRACT
# purpose: Run a CLI command as a subprocess with strict timeout and
#          process-group cleanup. Captures stdout/stderr/exit_code.
#          Optionally sends stdin_text to process stdin.
#          Never leaves orphan processes.
# inputs: command list, cwd, env, timeout_seconds, stdin_text (optional).
# returns: ProcessResult with stdout, stderr, exit_code, duration_ms, timed_out.
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


@dataclass
class ProcessResult:
    stdout: str = ""; stderr: str = ""; exit_code: int = -1; duration_ms: int = 0; timed_out: bool = False


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


class ProcessSupervisor:
    async def run(self, command: list[str], cwd: Path | str, env: dict[str, str] | None = None,
                  timeout_seconds: int = 600, stdin_text: str | None = None,
                  stdout_log_path: Path | str | None = None,
                  stderr_log_path: Path | str | None = None) -> ProcessResult:
        t0 = time.time()
        # GRACE_FAST_FAIL: cap all timeouts at 60s for dev/test so failures
        # surface immediately instead of hanging for 10+ minutes.
        _effective_timeout = timeout_seconds
        if os.environ.get("GRACE_FAST_FAIL"):
            _effective_timeout = min(timeout_seconds, 60)
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
            try:
                in_data = stdin_text.encode("utf-8", "ignore") if stdin_text else None

                # If log paths provided, write incremental output to files
                if stdout_log_path or stderr_log_path:
                    _stdout_buf: list[bytes] = []
                    _stderr_buf: list[bytes] = []

                    async def _read_stream(stream, buf, log_path=None):
                        while True:
                            line = await stream.readline()
                            if not line:
                                break
                            buf.append(line)
                            if log_path:
                                with open(log_path, "ab") as f:
                                    f.write(line)

                    # Write stdin_text before reading stdout/stderr
                    if stdin_text and proc.stdin:
                        proc.stdin.write(in_data)
                        await proc.stdin.drain()
                        proc.stdin.close()

                    readers = []
                    if proc.stdout:
                        readers.append(_read_stream(proc.stdout, _stdout_buf,
                            Path(stdout_log_path) if stdout_log_path else None))
                    if proc.stderr:
                        readers.append(_read_stream(proc.stderr, _stderr_buf,
                            Path(stderr_log_path) if stderr_log_path else None))

                    await asyncio.wait_for(asyncio.gather(*readers), timeout=_effective_timeout)
                    await proc.wait()
                    duration_ms = int((time.time() - t0) * 1000)
                    return ProcessResult(
                        stdout=b"".join(_stdout_buf).decode("utf-8", "ignore") if _stdout_buf else "",
                        stderr=b"".join(_stderr_buf).decode("utf-8", "ignore") if _stderr_buf else "",
                        exit_code=proc.returncode or 0, duration_ms=duration_ms,
                    )
                else:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(input=in_data), timeout=_effective_timeout
                    )
                    duration_ms = int((time.time() - t0) * 1000)
                    return ProcessResult(
                        stdout=stdout_bytes.decode("utf-8", "ignore") if stdout_bytes else "",
                        stderr=stderr_bytes.decode("utf-8", "ignore") if stderr_bytes else "",
                        exit_code=proc.returncode or 0, duration_ms=duration_ms,
                    )
            except asyncio.TimeoutError:
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                except Exception:
                    proc.kill()
                await proc.wait()
                return ProcessResult(timed_out=True, stderr=f"Timed out after {timeout_seconds}s",
                    duration_ms=int((time.time() - t0) * 1000))
        except FileNotFoundError:
            return ProcessResult(stderr=f"Command not found: {command[0]}", duration_ms=int((time.time() - t0) * 1000))
