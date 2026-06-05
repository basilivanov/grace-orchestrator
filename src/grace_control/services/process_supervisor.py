# AI_HEADER: process_supervisor — spawn subprocess, capture I/O, enforce timeout, kill process group
# START_MODULE_CONTRACT
# purpose: Run a CLI command as a subprocess with strict timeout and
#          process-group cleanup. Captures stdout/stderr and exit code.
#          Never leaves orphan processes.
# inputs: command list, cwd, env, timeout_seconds.
# returns: dict(stdout, stderr, exit_code, duration_ms, timed_out).
# side_effects: Spawns and kills subprocess.
# error_behavior: Timeout kills process group; non-zero exit is captured, not raised.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - class: ProcessSupervisor
#           - class: ProcessResult
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcessResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    duration_ms: int = 0
    timed_out: bool = False


class ProcessSupervisor:
    async def run(self, command: list[str], cwd: Path | str, env: dict[str, str] | None = None,
                  timeout_seconds: int = 600) -> ProcessResult:
        t0 = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=os.setsid,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout_seconds
                )
                duration_ms = int((time.time() - t0) * 1000)
                return ProcessResult(
                    stdout=stdout_bytes.decode("utf-8", "ignore"),
                    stderr=stderr_bytes.decode("utf-8", "ignore"),
                    exit_code=proc.returncode or 0,
                    duration_ms=duration_ms,
                )
            except asyncio.TimeoutError:
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                except Exception:
                    proc.kill()
                await proc.wait()
                duration_ms = int((time.time() - t0) * 1000)
                return ProcessResult(
                    timed_out=True, duration_ms=duration_ms,
                    stderr=f"Process timed out after {timeout_seconds}s",
                )
        except FileNotFoundError:
            return ProcessResult(stderr=f"Command not found: {command[0]}", duration_ms=int((time.time() - t0) * 1000))
