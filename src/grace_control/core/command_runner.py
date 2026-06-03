# ############################################################################
# AI_HEADER: command_runner
# ROLE: Safe deterministic subprocess runner for acceptance pipeline commands.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run CLI commands as str (no shell=True), capture stdout/stderr/exit_code.
#          Public function run_command() is the spec-facing API.
# inputs: command (str), cwd (Path), output_dir (Path), timeout_seconds (int).
# returns: CommandResult dataclass.
# side_effects: Spawns subprocess; writes stdout/stderr to files.
# emitted_logs: None.
# error_behavior: Never raises; returns CommandResult with exit_code and stderr on failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: CommandRunner
#   - function: run_command
# END_MODULE_MAP

from __future__ import annotations

import re
import shlex
import subprocess
import time
from pathlib import Path

from grace_control.core.contracts import CommandResult

_SHELL_OPS = re.compile(r'(&&|\|\||[|<>])')


def run_command(
    command: str,
    cwd: Path,
    output_dir: Path,
    timeout_seconds: int = 120,
    env: dict[str, str] | None = None,
) -> CommandResult:
    if _SHELL_OPS.search(command):
        return CommandResult(
            command=command, cwd=str(cwd.resolve()), exit_code=1,
            stderr=f"unsupported shell syntax in command: {command[:200]}",
            stdout_path="", stderr_path="",
            timed_out=False, duration_ms=0,
        )

    try:
        cmd_list = shlex.split(command)
    except ValueError:
        return CommandResult(
            command=command, cwd=str(cwd.resolve()), exit_code=1,
            stderr=f"cannot parse command string: {command[:200]}",
            stdout_path="", stderr_path="",
            timed_out=False, duration_ms=0,
        )

    if not cmd_list:
        return CommandResult(
            command=command, cwd=str(cwd.resolve()), exit_code=1,
            stderr="command is empty after shlex.split",
            stdout_path="", stderr_path="",
            timed_out=False, duration_ms=0,
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_files = list(output_dir.glob("*_stdout.log"))
    cmd_id = (int(stdout_files[-1].stem.split("_")[1]) if stdout_files else 0) + 1
    stdout_path = output_dir / f"cmd_{cmd_id:03d}_stdout.log"
    stderr_path = output_dir / f"cmd_{cmd_id:03d}_stderr.log"

    started = time.time()
    try:
        with open(stdout_path, "w") as out_f, open(stderr_path, "w") as err_f:
            proc = subprocess.run(
                cmd_list, cwd=str(cwd), timeout=timeout_seconds,
                stdout=out_f, stderr=err_f, env=env,
            )
        stdout_text = stdout_path.read_text()
        stderr_text = stderr_path.read_text()
        duration = int((time.time() - started) * 1000)
        return CommandResult(
            command=command, cwd=str(cwd.resolve()), exit_code=proc.returncode,
            stdout=stdout_text, stderr=stderr_text,
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            timed_out=False, duration_ms=duration,
        )
    except subprocess.TimeoutExpired:
        duration = int((time.time() - started) * 1000)
        return CommandResult(
            command=command, cwd=str(cwd.resolve()), exit_code=-1,
            stderr=f"timeout after {timeout_seconds}s",
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            timed_out=True, duration_ms=duration,
        )
    except FileNotFoundError:
        return CommandResult(
            command=command, cwd=str(cwd.resolve()), exit_code=127,
            stderr=f"command not found: {cmd_list[0]}",
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            timed_out=False, duration_ms=int((time.time() - started) * 1000),
        )
    except Exception as e:
        return CommandResult(
            command=command, cwd=str(cwd.resolve()), exit_code=1,
            stderr=str(e)[:500],
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            timed_out=False, duration_ms=int((time.time() - started) * 1000),
        )


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
            if _SHELL_OPS.search(command):
                return CommandResult(
                    command=command, cwd=str((cwd or self._root).resolve()), exit_code=1,
                    stderr=f"unsupported shell syntax in command: {command[:200]}",
                    stdout_path="", stderr_path="",
                    timed_out=False, duration_ms=0,
                )
            try:
                cmd_list = shlex.split(command)
            except ValueError:
                return CommandResult(
                    command=command, cwd=str((cwd or self._root).resolve()), exit_code=1,
                    stderr=f"cannot parse command string: {command[:200]}",
                    stdout_path="", stderr_path="",
                    timed_out=False, duration_ms=0,
                )
        else:
            cmd_list = list(command)
        cwd_resolved = (cwd or self._root).resolve()
        try:
            cwd_resolved.relative_to(self._root)
        except ValueError:
            return CommandResult(
                command=" ".join(cmd_list) if isinstance(cmd_list, list) else cmd_list,
                cwd=str(cwd_resolved), exit_code=1,
                stderr=f"cwd {cwd_resolved} is outside repo root {self._root}",
                stdout_path="", stderr_path="",
                timed_out=False, duration_ms=0,
            )

        if not cmd_list:
            return CommandResult(
                command="", cwd=str(cwd_resolved), exit_code=1,
                stderr="command must be non-empty list[str]",
                stdout_path="", stderr_path="",
                timed_out=False, duration_ms=0,
            )

        for arg in cmd_list:
            if not isinstance(arg, str):
                return CommandResult(
                    command=" ".join(str(a) for a in cmd_list), cwd=str(cwd_resolved), exit_code=1,
                    stderr=f"command arg must be str, got {type(arg).__name__}",
                    stdout_path="", stderr_path="",
                    timed_out=False, duration_ms=0,
                )

        timeout = timeout_s or self._default_timeout
        started = time.time()
        stdout_path = ""
        stderr_path = ""
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            existing = sorted(output_dir.glob("*_stdout.log"))
            cmd_id = (int(existing[-1].stem.split("_")[1]) if existing else 0) + 1
            stdout_path = str(output_dir / f"cmd_{cmd_id:03d}_stdout.log")
            stderr_path = str(output_dir / f"cmd_{cmd_id:03d}_stderr.log")

        try:
            if output_dir:
                with open(stdout_path, "w") as out_f, open(stderr_path, "w") as err_f:
                    proc = subprocess.run(
                        cmd_list, cwd=str(cwd_resolved), timeout=timeout,
                        stdout=out_f, stderr=err_f,
                    )
                stdout_text = open(stdout_path).read()
                stderr_text = open(stderr_path).read()
            else:
                proc = subprocess.run(
                    cmd_list, cwd=str(cwd_resolved), capture_output=True, text=True, timeout=timeout,
                )
                stdout_text = proc.stdout or ""
                stderr_text = proc.stderr or ""

            duration = int((time.time() - started) * 1000)
            cmd_str = " ".join(cmd_list) if isinstance(cmd_list, list) else cmd_list
            return CommandResult(
                command=cmd_str, cwd=str(cwd_resolved), exit_code=proc.returncode,
                stdout=stdout_text, stderr=stderr_text,
                stdout_path=stdout_path, stderr_path=stderr_path,
                timed_out=False, duration_ms=duration,
            )
        except subprocess.TimeoutExpired:
            duration = int((time.time() - started) * 1000)
            cmd_str = " ".join(cmd_list) if isinstance(cmd_list, list) else cmd_list
            return CommandResult(
                command=cmd_str, cwd=str(cwd_resolved), exit_code=-1,
                stderr=f"timeout after {timeout}s",
                stdout_path=stdout_path, stderr_path=stderr_path,
                timed_out=True, duration_ms=duration,
            )
        except FileNotFoundError:
            cmd_str = " ".join(cmd_list) if isinstance(cmd_list, list) else cmd_list
            return CommandResult(
                command=cmd_str, cwd=str(cwd_resolved), exit_code=127,
                stderr=f"command not found: {cmd_list[0]}",
            )
        except Exception as e:
            cmd_str = " ".join(cmd_list) if isinstance(cmd_list, list) else cmd_list
            return CommandResult(
                command=cmd_str, cwd=str(cwd_resolved), exit_code=1,
                stderr=str(e)[:500],
            )
