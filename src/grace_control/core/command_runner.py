# ############################################################################
# AI_HEADER: command_runner
# ROLE: Safe deterministic subprocess runner for acceptance pipeline commands.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run CLI commands as list[str] (no shell=True), capture stdout/stderr/exit_code.
# inputs: command (list[str]), cwd (Path), timeout_s (int).
# returns: CommandResult dataclass.
# side_effects: Spawns subprocess.
# emitted_logs: None.
# error_behavior: Never raises; returns CommandResult with exit_code and stderr on failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: CommandRunner
# END_MODULE_MAP

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path

from grace_control.core.contracts import CommandResult


class CommandRunner:

    def __init__(self, repo_root: Path, default_timeout_s: int = 300) -> None:
        self._root = repo_root.resolve()
        self._default_timeout = default_timeout_s

    def run(
        self,
        command: list[str] | str,
        *,
        cwd: Path | None = None,
        timeout_s: int | None = None,
        output_dir: Path | None = None,
    ) -> CommandResult:
        # Normalize: string → list via shlex (safe, no shell=True)
        if isinstance(command, str):
            try:
                command = shlex.split(command)
            except ValueError:
                return CommandResult(
                    command=[command], cwd="", exit_code=1,
                    stderr=f"cannot parse command string: {command[:200]}",
                )
        cwd = (cwd or self._root).resolve()
        try:
            cwd.relative_to(self._root)
        except ValueError:
            return CommandResult(
                command=command, cwd=str(cwd), exit_code=1,
                stderr=f"cwd {cwd} is outside repo root {self._root}",
            )

        if not isinstance(command, list) or not command:
            return CommandResult(
                command=list(command), cwd=str(cwd), exit_code=1,
                stderr="command must be non-empty list[str]",
            )

        for arg in command:
            if not isinstance(arg, str):
                return CommandResult(
                    command=[str(a) for a in command], cwd=str(cwd), exit_code=1,
                    stderr=f"command arg must be str, got {type(arg).__name__}",
                )

        timeout = timeout_s or self._default_timeout
        started = time.time()

        # Write stdout/stderr to files if output_dir is specified
        stdout_path = ""
        stderr_path = ""
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            cmd_id = len(list(output_dir.glob("cmd_*"))) + 1
            stdout_path = str(output_dir / f"cmd_{cmd_id:03d}_stdout.log")
            stderr_path = str(output_dir / f"cmd_{cmd_id:03d}_stderr.log")

        try:
            if output_dir:
                with open(stdout_path, "w") as out_f, open(stderr_path, "w") as err_f:
                    proc = subprocess.run(
                        command, cwd=str(cwd), timeout=timeout,
                        stdout=out_f, stderr=err_f,
                    )
                stdout_text = open(stdout_path).read()
                stderr_text = open(stderr_path).read()
            else:
                proc = subprocess.run(
                    command, cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                )
                stdout_text = proc.stdout or ""
                stderr_text = proc.stderr or ""

            duration = int((time.time() - started) * 1000)
            return CommandResult(
                command=command, cwd=str(cwd), exit_code=proc.returncode,
                stdout=stdout_text, stderr=stderr_text,
                stdout_path=stdout_path, stderr_path=stderr_path,
                timed_out=False, duration_ms=duration,
            )
        except subprocess.TimeoutExpired:
            duration = int((time.time() - started) * 1000)
            return CommandResult(
                command=command, cwd=str(cwd), exit_code=-1,
                stderr=f"timeout after {timeout}s",
                stdout_path=stdout_path, stderr_path=stderr_path,
                timed_out=True, duration_ms=duration,
            )
        except FileNotFoundError:
            return CommandResult(
                command=command, cwd=str(cwd), exit_code=127,
                stderr=f"command not found: {command[0]}",
            )
        except Exception as e:
            return CommandResult(
                command=command, cwd=str(cwd), exit_code=1,
                stderr=str(e)[:500],
            )
