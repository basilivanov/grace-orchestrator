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
import asyncio, os, signal, time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcessResult:
    stdout: str = ""; stderr: str = ""; exit_code: int = -1; duration_ms: int = 0; timed_out: bool = False


class ProcessSupervisor:
    async def run(self, command: list[str], cwd: Path | str, env: dict[str, str] | None = None,
                  timeout_seconds: int = 600, stdin_text: str | None = None) -> ProcessResult:
        t0 = time.time()
        try:
            stdin_pipe = asyncio.subprocess.PIPE if stdin_text is not None else None
            proc = await asyncio.create_subprocess_exec(
                *command, cwd=str(cwd), env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                stdin=stdin_pipe, preexec_fn=os.setsid,
            )
            try:
                in_data = stdin_text.encode("utf-8", "ignore") if stdin_text else None
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=in_data), timeout=timeout_seconds
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
