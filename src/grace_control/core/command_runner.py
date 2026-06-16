# ############################################################################
# AI_HEADER: command_runner
# ROLE: Safe deterministic subprocess runner for acceptance pipeline commands.
# W06: No-shell by default, explicit shell mode, process-group kill on timeout,
#      partial output capture, diagnostics (killed_pgid, command_preview, shell_mode).
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run CLI commands as str (no shell=True by default), capture stdout/stderr/exit_code.
#          Public function run_command() is the spec-facing API.
#          W06: Shell mode is explicit opt-in; shell commands use process-group kill.
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
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from grace_control.core.contracts import CommandResult
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("command_runner")

_SHELL_OPS = re.compile(r'(&&|\|\||[|<>])')

# W06: Maximum time to wait for process to exit after SIGKILL
_KILL_WAIT_TIMEOUT_S = 5


def _kill_process_group(proc: subprocess.Popen, timeout_s: float = _KILL_WAIT_TIMEOUT_S) -> tuple[int | None, bool]:
    """W06: Kill the process group and wait with bounded timeout.

    Returns (killed_pgid, wait_after_kill_timed_out).
    """
    killed_pgid = None
    wait_after_kill_timed_out = False

    # Kill the process group (children too)
    try:
        pgid = os.getpgid(proc.pid)
        killed_pgid = pgid
        os.killpg(pgid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

    # Bounded wait — don't hang forever
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        wait_after_kill_timed_out = True

    return killed_pgid, wait_after_kill_timed_out


# START_BLOCK_FREE_FUNCTION
# START_FUNCTION_CONTRACT
# name: run_command
# purpose: Run a CLI command string safely (no shell=True), capture stdout/stderr/exit_code.
#          W06: Shell mode is never used in the free function — always no-shell.
# inputs: command (str), cwd (Path), output_dir (Path), timeout_seconds (int), env (optional dict).
# returns: CommandResult with exit_code, stdout, stderr, duration_ms, diagnostics.
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
    """Run a CLI command string safely without shell=True.

    W06: This function NEVER uses shell=True. If the command contains
    shell operators (&& || | etc.), it returns an error instead of
    silently using a shell.
    """
    cmd_preview = command[:200]

    if _SHELL_OPS.search(command):
        return CommandResult(
            command=command, cwd=str(cwd.resolve()), exit_code=1,
            stderr=f"unsupported shell syntax in command: {command[:200]}",
            stdout_path="", stderr_path="",
            timed_out=False, duration_ms=0,
            command_preview=cmd_preview, shell_mode=False,
        )

    try:
        cmd_list = shlex.split(command)
    except ValueError:
        return CommandResult(
            command=command, cwd=str(cwd.resolve()), exit_code=1,
            stderr=f"cannot parse command string: {command[:200]}",
            stdout_path="", stderr_path="",
            timed_out=False, duration_ms=0,
            command_preview=cmd_preview, shell_mode=False,
        )

    if not cmd_list:
        return CommandResult(
            command=command, cwd=str(cwd.resolve()), exit_code=1,
            stderr="command is empty after shlex.split",
            stdout_path="", stderr_path="",
            timed_out=False, duration_ms=0,
            command_preview=cmd_preview, shell_mode=False,
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
        # W06: Use subprocess.Popen with start_new_session=True so we can
        # kill the process group on timeout. Never use shell=True.
        with open(stdout_path, "w") as out_f, open(stderr_path, "w") as err_f:
            proc = subprocess.Popen(
                cmd_list, cwd=str(cwd), env=proc_env,
                stdout=out_f, stderr=err_f,
                start_new_session=True,
            )

        try:
            proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            # W06: Kill process group, capture partial output
            killed_pgid, wait_after_kill_timed_out = _kill_process_group(proc)
            duration = int((time.time() - started) * 1000)

            # Capture partial output from log files
            partial_stdout = ""
            partial_stderr = f"timeout after {timeout_seconds}s"
            try:
                partial_stdout = stdout_path.read_text()
            except Exception:
                pass
            try:
                partial_stderr = stderr_path.read_text() or f"timeout after {timeout_seconds}s"
            except Exception:
                pass

            return CommandResult(
                command=command, cwd=str(cwd.resolve()), exit_code=-1,
                stdout=partial_stdout, stderr=partial_stderr,
                stdout_path=str(stdout_path), stderr_path=str(stderr_path),
                timed_out=True, duration_ms=duration,
                killed_pgid=killed_pgid,
                wait_after_kill_timed_out=wait_after_kill_timed_out,
                command_preview=cmd_preview, shell_mode=False,
            )

        stdout_text = stdout_path.read_text()
        stderr_text = stderr_path.read_text()
        duration = int((time.time() - started) * 1000)
        return CommandResult(
            command=command, cwd=str(cwd.resolve()), exit_code=proc.returncode,
            stdout=stdout_text, stderr=stderr_text,
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            timed_out=False, duration_ms=duration,
            command_preview=cmd_preview, shell_mode=False,
        )
    except FileNotFoundError:
        return CommandResult(
            command=command, cwd=str(cwd.resolve()), exit_code=127,
            stderr=f"command not found: {cmd_list[0]}",
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            timed_out=False, duration_ms=int((time.time() - started) * 1000),
            command_preview=cmd_preview, shell_mode=False,
        )
    except Exception as e:
        return CommandResult(
            command=command, cwd=str(cwd.resolve()), exit_code=1,
            stderr=str(e)[:500],
            stdout_path=str(stdout_path), stderr_path=str(stderr_path),
            timed_out=False, duration_ms=int((time.time() - started) * 1000),
            command_preview=cmd_preview, shell_mode=False,
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
    #          W06: Shell mode is explicit opt-in. Default is no-shell.
    #          Shell commands are killed via process group on timeout.
    # inputs: command (list[str] | str), cwd, timeout_s, output_dir, shell (bool, default False).
    # returns: CommandResult with exit_code, stdout, stderr, duration_ms, diagnostics.
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
        shell: bool = False,
    ) -> CommandResult:
        if isinstance(command, str):
            resolved_cwd = (cwd or self._root).resolve()
            try:
                resolved_cwd.relative_to(self._root)
            except ValueError:
                return CommandResult(
                    command=command, cwd=str(resolved_cwd), exit_code=1,
                    stderr=f"cwd {resolved_cwd} is outside repo root {self._root}",
                    command_preview=command[:200], shell_mode=False,
                )

            # W06: String commands are parsed via shlex and run without shell
            # unless shell=True is explicitly requested.
            if shell:
                effective_outdir = output_dir or Path(tempfile.mkdtemp(prefix="cmd_output_"))
                return self._run_shell_command(
                    command_str=command,
                    cwd=resolved_cwd,
                    timeout=timeout_s or self._default_timeout,
                    output_dir=effective_outdir,
                )
            else:
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
                command_preview=" ".join(cmd_list)[:200], shell_mode=False,
            )
        if not cmd_list:
            return CommandResult(
                command="", cwd=str(resolved_cwd), exit_code=1,
                stderr="command must be non-empty",
                command_preview="", shell_mode=False,
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

        # W06: Re-quote -c argument after shlex.split — the code string
        # may contain shell metacharacters (quotes, semicolons) that were
        # protected by single quotes. shlex.split removes the outer quotes,
        # so we must re-quote with shlex.quote() before reconstructing.
        if len(cmd_list) >= 3 and cmd_list[0] == "python3" and cmd_list[1] == "-c":
            cmd_list = cmd_list[:2] + [shlex.quote(cmd_list[2])] + cmd_list[3:]

        cmd_str = " ".join(cmd_list)
        # Replace 'source' with '.' for dash/sh compatibility (source is bash-only)
        if cmd_str.startswith('source ') or ' && source ' in cmd_str or '; source ' in cmd_str:
            cmd_str = cmd_str.replace('source ', '. ')
        # Strip .venv activation — worktree has no venv, system python3 has pytest
        cmd_str = cmd_str.replace('&& . .venv/bin/activate &&', '&&')
        cmd_str = cmd_str.replace('&& source .venv/bin/activate &&', '&&')
        if cmd_str.startswith('. .venv/bin/activate && '):
            cmd_str = cmd_str[len('. .venv/bin/activate && '):]
        # Strip any leading '. <path>/.venv/bin/activate &&' (architect uses relative paths)
        import re as _re2
        cmd_str = _re2.sub(r'^\.\s+\S*\.venv/bin/activate\s*&&\s*', '', cmd_str)
        cmd_str = _re2.sub(r'\s*&&\s*\.\s+\S*\.venv/bin/activate\s*&&', ' &&', cmd_str)
        # Replace bare 'python' with 'python3' after venv strip (worktree has no venv)
        cmd_str = _re2.sub(r'(^|\s)python(\s|$)', r'\1python3\2', cmd_str)
        timeout = timeout_s or self._default_timeout
        started = time.time()
        cmd_preview = cmd_str[:200]

        # W06: If shell=True was explicitly requested, use shell mode
        if shell:
            return self._run_shell_command(
                command_str=cmd_str,
                cwd=resolved_cwd,
                timeout=timeout,
                output_dir=output_dir or Path(tempfile.mkdtemp(prefix="cmd_output_")),
            )

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
            # W06: No-shell mode — use Popen with start_new_session
            # for process-group kill on timeout
            with open(stdout_path, "w") as out_f, open(stderr_path, "w") as err_f:
                proc = subprocess.Popen(
                    cmd_list, cwd=str(resolved_cwd), env=os.environ.copy(),
                    stdout=out_f, stderr=err_f,
                    start_new_session=True,
                )

            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # W06: Kill process group, capture partial output
                killed_pgid, wait_after_kill_timed_out = _kill_process_group(proc)
                duration = int((time.time() - started) * 1000)

                partial_stdout = ""
                partial_stderr = f"timeout after {timeout}s"
                try:
                    partial_stdout = Path(stdout_path).read_text()
                except Exception:
                    pass
                try:
                    partial_stderr = Path(stderr_path).read_text() or f"timeout after {timeout}s"
                except Exception:
                    pass

                return CommandResult(
                    command=cmd_str, cwd=str(resolved_cwd), exit_code=-1,
                    stdout=partial_stdout, stderr=partial_stderr,
                    stdout_path=stdout_path, stderr_path=stderr_path,
                    timed_out=True, duration_ms=duration,
                    killed_pgid=killed_pgid,
                    wait_after_kill_timed_out=wait_after_kill_timed_out,
                    command_preview=cmd_preview, shell_mode=False,
                )

            stdout_text = Path(stdout_path).read_text()
            stderr_text = Path(stderr_path).read_text()
            duration = int((time.time() - started) * 1000)
            return CommandResult(
                command=cmd_str, cwd=str(resolved_cwd), exit_code=proc.returncode,
                stdout=stdout_text, stderr=stderr_text,
                stdout_path=stdout_path, stderr_path=stderr_path,
                timed_out=False, duration_ms=duration,
                command_preview=cmd_preview, shell_mode=False,
            )
        except FileNotFoundError:
            return CommandResult(
                command=cmd_str, cwd=str(resolved_cwd), exit_code=127,
                stderr=f"command not found: {cmd_list[0]}",
                stdout_path=stdout_path, stderr_path=stderr_path,
                timed_out=False, duration_ms=int((time.time() - started) * 1000),
                command_preview=cmd_preview, shell_mode=False,
            )
        except Exception as e:
            return CommandResult(
                command=cmd_str, cwd=str(resolved_cwd), exit_code=1,
                stderr=str(e)[:500],
                stdout_path=stdout_path, stderr_path=stderr_path,
                timed_out=False, duration_ms=int((time.time() - started) * 1000),
                command_preview=cmd_preview, shell_mode=False,
            )

    def _run_shell_command(
        self,
        command_str: str,
        cwd: Path,
        timeout: int,
        output_dir: Path,
    ) -> CommandResult:
        """W06: Run a command with shell=True, using process-group kill on timeout.

        Shell mode is explicit opt-in. Uses setsid/start_new_session so
        the entire process tree can be killed on timeout, preventing
        orphan child processes.
        """
        cmd_preview = command_str[:200]
        started = time.time()

        output_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(output_dir.glob("*_stdout.log"))
        cmd_id = (int(existing[-1].stem.split("_")[1]) if existing else 0) + 1
        stdout_path = str(output_dir / f"cmd_{cmd_id:03d}_stdout.log")
        stderr_path = str(output_dir / f"cmd_{cmd_id:03d}_stderr.log")

        try:
            with open(stdout_path, "w") as out_f, open(stderr_path, "w") as err_f:
                # W06: start_new_session=True so we can kill the process group
                proc = subprocess.Popen(
                    command_str, cwd=str(cwd), shell=True,
                    stdout=out_f, stderr=err_f,
                    start_new_session=True,
                )

            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # W06: Kill the whole process group (shell + children)
                killed_pgid, wait_after_kill_timed_out = _kill_process_group(proc)
                duration = int((time.time() - started) * 1000)

                # Capture partial output
                partial_stdout = ""
                partial_stderr = f"timeout after {timeout}s (shell mode)"
                try:
                    partial_stdout = Path(stdout_path).read_text()
                except Exception:
                    pass
                try:
                    partial_stderr = Path(stderr_path).read_text() or f"timeout after {timeout}s (shell mode)"
                except Exception:
                    pass

                return CommandResult(
                    command=command_str, cwd=str(cwd.resolve()), exit_code=-1,
                    stdout=partial_stdout, stderr=partial_stderr,
                    stdout_path=stdout_path, stderr_path=stderr_path,
                    timed_out=True, duration_ms=duration,
                    killed_pgid=killed_pgid,
                    wait_after_kill_timed_out=wait_after_kill_timed_out,
                    command_preview=cmd_preview, shell_mode=True,
                )

            stdout_text = Path(stdout_path).read_text()
            stderr_text = Path(stderr_path).read_text()
            duration = int((time.time() - started) * 1000)
            return CommandResult(
                command=command_str, cwd=str(cwd.resolve()), exit_code=proc.returncode,
                stdout=stdout_text, stderr=stderr_text,
                stdout_path=stdout_path, stderr_path=stderr_path,
                timed_out=False, duration_ms=duration,
                command_preview=cmd_preview, shell_mode=True,
            )
        except FileNotFoundError:
            return CommandResult(
                command=command_str, cwd=str(cwd.resolve()), exit_code=127,
                stderr=f"command not found: {command_str[:100]}",
                stdout_path=stdout_path, stderr_path=stderr_path,
                timed_out=False, duration_ms=int((time.time() - started) * 1000),
                command_preview=cmd_preview, shell_mode=True,
            )
        except Exception as e:
            return CommandResult(
                command=command_str, cwd=str(cwd.resolve()), exit_code=1,
                stderr=str(e)[:500],
                stdout_path=stdout_path, stderr_path=stderr_path,
                timed_out=False, duration_ms=int((time.time() - started) * 1000),
                command_preview=cmd_preview, shell_mode=True,
            )

# END_BLOCK_CLASS
