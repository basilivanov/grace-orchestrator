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

import os
import re
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from grace_control.core.contracts import CommandResult
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("command_runner")

_SHELL_OPS = re.compile(r'(&&|\|\||[|<>])')


# START_BLOCK_FREE_FUNCTION
# START_FUNCTION_CONTRACT
# name: run_command
# purpose: Run a CLI command string safely (no shell=True), capture stdout/stderr/exit_code.
# inputs: command (str), cwd (Path), output_dir (Path), timeout_seconds (int), env (optional dict).
# returns: CommandResult with exit_code, stdout, stderr, duration_ms.
# side_effects: Spawns subprocess; writes stdout/stderr to output_dir files.
# emitted_logs: None.
# error_behavior: Never raises; returns CommandResult with non-zero exit_code + stderr on failure.
# END_FUNCTION_CONTRACT
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

    # Ensure .venv/bin is in PATH so ruff/pytest are found
    proc_env = (env or os.environ).copy()
    for parent in [cwd.resolve(), cwd.resolve().parent, cwd.resolve().parent.parent]:
        pv = parent / ".venv" / "bin"
        if pv.is_dir() and str(pv) not in proc_env.get("PATH", ""):
            proc_env["PATH"] = f"{pv}:{proc_env.get('PATH', '')}"

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
                stdout=out_f, stderr=err_f, env=proc_env,
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

# END_BLOCK_FREE_FUNCTION

# START_BLOCK_CLASS
# START_FUNCTION_CONTRACT
# name: CommandRunner.__init__
# purpose: Initialize command runner with repo root and default timeout.
# inputs: repo_root — project root Path; default_timeout_s — timeout in seconds (default 300).
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
class CommandRunner:

    def __init__(self, repo_root: Path, default_timeout_s: int = 300) -> None:
        self._root = repo_root.resolve()
        self._default_timeout = default_timeout_s

    # START_FUNCTION_CONTRACT
    # name: CommandRunner.run
    # purpose: Run a command (list or str) safely inside the repo root.
    # inputs: command (list[str] | str), cwd (optional Path), timeout_s (optional int), output_dir (optional Path).
    # returns: CommandResult with exit_code, stdout, stderr, duration_ms.
    # side_effects: Spawns subprocess; writes stdout/stderr to output_dir files.
    # emitted_logs: None.
    # error_behavior: Never raises; returns CommandResult with non-zero exit_code on failure.
    # END_FUNCTION_CONTRACT
    def run(
        self,
        command: list[str] | str,
        *,
        cwd: Path | None = None,
        timeout_s: int | None = None,
        output_dir: Path | None = None,
    ) -> CommandResult:
        if isinstance(command, str):
            resolved_cwd = (cwd or self._root).resolve()
            try:
                resolved_cwd.relative_to(self._root)
            except ValueError:
                return CommandResult(
                    command=command, cwd=str(resolved_cwd), exit_code=1,
                    stderr=f"cwd {resolved_cwd} is outside repo root {self._root}",
                )
            effective_outdir = output_dir or Path(tempfile.mkdtemp(prefix="cmd_output_"))
            return run_command(
                command=command,
                cwd=resolved_cwd,
                output_dir=effective_outdir,
                timeout_seconds=timeout_s or self._default_timeout,
            )

        cmd_list = list(command)
        resolved_cwd = (cwd or self._root).resolve()
        try:
            resolved_cwd.relative_to(self._root)
        except ValueError:
            return CommandResult(
                command=" ".join(cmd_list), cwd=str(resolved_cwd), exit_code=1,
                stderr=f"cwd {resolved_cwd} is outside repo root {self._root}",
            )
        if not cmd_list:
            return CommandResult(
                command="", cwd=str(resolved_cwd), exit_code=1,
                stderr="command must be non-empty",
            )

        # Fix bare python3 -c arguments: if -c value is not quoted, re-quote it.
        # The architect often generates python3 -c import sys; ... file.yml
        # without quotes around the code. shlex.split splits each word, but
        # -c only takes the next token. Detect this by checking if there are
        # extra tokens before a file path, and re-quote them together.
        if len(cmd_list) >= 4 and cmd_list[0] == "python3" and cmd_list[1] == "-c" and not cmd_list[2].startswith("'"):
            # Re-quote: python3 -c 'all tokens up to the file path'
            code_tokens = []
            file_tokens = []
            in_code = True
            for t in cmd_list[2:]:
                if in_code and ("/" in t or t.startswith(".")):
                    in_code = False
                if in_code:
                    code_tokens.append(t)
                else:
                    file_tokens.append(t)
            requoted = "python3 -c '" + " ".join(code_tokens) + "'"
            if file_tokens:
                requoted += " " + " ".join(file_tokens)
            cmd_list = shlex.split(requoted)

        cmd_str = " ".join(cmd_list)
        # Replace 'source' with '.' for dash/sh compatibility (source is bash-only)
        if cmd_str.startswith('source ') or ' && source ' in cmd_str or '; source ' in cmd_str:
            cmd_str = cmd_str.replace('source ', '. ')
        # Strip .venv activation — worktree has no venv, system python3 has pytest
        # cd apps/api && . .venv/bin/activate && python3 ... → cd apps/api && python3 ...
        while '.venv/bin/activate' in cmd_str:
            idx = cmd_str.index('.venv/bin/activate')
            start = cmd_str.rfind('.', 0, idx) if '. ' in cmd_str[:idx] else cmd_str.rfind('&& ', 0, idx) if '&& ' in cmd_str[:idx] else idx
            if start > 0 and cmd_str[start:start+2] in ('. ', '&&'):
                end = idx + len('.venv/bin/activate')
                if end < len(cmd_str) and cmd_str[end:end+3] == ' &&':
                    end += 4  # strip ' && ' after activate too
                cmd_str = cmd_str[:start] + cmd_str[end:]
            else:
                break
        timeout = timeout_s or self._default_timeout
        started = time.time()

        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            existing = sorted(output_dir.glob("*_stdout.log"))
            cmd_id = (int(existing[-1].stem.split("_")[1]) if existing else 0) + 1
            stdout_path = str(output_dir / f"cmd_{cmd_id:03d}_stdout.log")
            stderr_path = str(output_dir / f"cmd_{cmd_id:03d}_stderr.log")
        else:
            out_dir = Path(tempfile.mkdtemp(prefix="cmd_output_"))
            stdout_path = str(out_dir / "cmd_001_stdout.log")
            stderr_path = str(out_dir / "cmd_001_stderr.log")

        try:
            with open(stdout_path, "w") as out_f, open(stderr_path, "w") as err_f:
                # Shell=True for non-python3 commands (so shell operators like
                # || && ; $() 2>&1 work). For python3 -c, use list form to
                # avoid shell metacharacter issues in inline Python code.
                is_python3 = cmd_str.startswith('python3 -c')
                if is_python3:
                    proc = subprocess.run(
                        cmd_list, cwd=str(resolved_cwd), timeout=timeout,
                        stdout=out_f, stderr=err_f,
                    )
                else:
                    proc = subprocess.run(
                        cmd_str, cwd=str(resolved_cwd), timeout=timeout, shell=True,
                        stdout=out_f, stderr=err_f,
                    )
            stdout_text = open(stdout_path).read()
            stderr_text = open(stderr_path).read()
            duration = int((time.time() - started) * 1000)
            return CommandResult(
                command=cmd_str, cwd=str(resolved_cwd), exit_code=proc.returncode,
                stdout=stdout_text, stderr=stderr_text,
                stdout_path=stdout_path, stderr_path=stderr_path,
                timed_out=False, duration_ms=duration,
            )
        except subprocess.TimeoutExpired:
            duration = int((time.time() - started) * 1000)
            return CommandResult(
                command=cmd_str, cwd=str(resolved_cwd), exit_code=-1,
                stderr=f"timeout after {timeout}s",
                stdout_path=stdout_path, stderr_path=stderr_path,
                timed_out=True, duration_ms=duration,
            )
        except FileNotFoundError:
            return CommandResult(
                command=cmd_str, cwd=str(resolved_cwd), exit_code=127,
                stderr=f"command not found: {cmd_list[0]}",
                stdout_path=stdout_path, stderr_path=stderr_path,
                timed_out=False, duration_ms=int((time.time() - started) * 1000),
            )
        except Exception as e:
            return CommandResult(
                command=cmd_str, cwd=str(resolved_cwd), exit_code=1,
                stderr=str(e)[:500],
                stdout_path=stdout_path, stderr_path=stderr_path,
                timed_out=False, duration_ms=int((time.time() - started) * 1000),
            )

# END_BLOCK_CLASS
