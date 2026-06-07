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
                  timeout_seconds: int = 600, stdin_text: str | None = None) -> ProcessResult:
        t0 = time.time()
        # GRACE_FAST_FAIL: cap all timeouts at 60s for dev/test so failures
        # surface immediately instead of hanging for 10+ minutes.
        _effective_timeout = timeout_seconds
        if os.environ.get("GRACE_FAST_FAIL"):
            _effective_timeout = min(timeout_seconds, 60)
        # Override PWD so the child process sees the requested cwd as its
        # working directory. Without this, many CLIs (e.g. `opencode run`)
        # use $PWD from the inherited parent env instead of getcwd() and
        # end up writing files to the project root instead of the per-packet
        # worktree. Setting PWD explicitly fixes the cwd/agent-mismatch bug.
        # We always pass an explicit env (copy of os.environ when env=None)
        # so the override is always applied.
        proc_env = dict(os.environ) if env is None else dict(env)
        proc_env["PWD"] = str(cwd)
        try:
            stdin_pipe = asyncio.subprocess.PIPE if stdin_text is not None else None
            proc = await asyncio.create_subprocess_exec(
                *command, cwd=str(cwd), env=proc_env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                stdin=stdin_pipe, preexec_fn=os.setsid,
            )
            try:
                in_data = stdin_text.encode("utf-8", "ignore") if stdin_text else None
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
