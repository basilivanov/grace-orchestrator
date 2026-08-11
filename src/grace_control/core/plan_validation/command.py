# ############################################################################
# AI_HEADER: plan_validation_command — command and interpreter validation
# ROLE: Own deterministic validation of packet verification commands. The
#       compiler facade supplies the shared result, environment, and packet context.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate shell commands, interpreters, modules, scripts, and shell syntax.
# inputs: Command text, ExecutionEnvironment, packet context, and target repository root.
# returns: None; appends stable errors and warnings to CompileResult.
# side_effects: Reads repository paths and runtime-discovered facts; does not execute commands.
# emitted_logs: None.
# error_behavior: Invalid command facts are reported as compiler diagnostics.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: validate_command
#   - function: _validate_script_path
#   - function: _command_segments
#   - function: _python_module_exists
# END_MODULE_MAP

from __future__ import annotations

import importlib.util
import os
import re
import shlex
import sys
from pathlib import Path

from grace_control.core.execution_environment import ExecutionEnvironment
from grace_control.core.plan_validation.models import CompileResult, _add_error, _add_warning
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("plan_validation.command")


# START_BLOCK_CONSTANTS
_INVALID_PY_PATTERNS = [
    re.compile(r"\bfor\s+\w+\s+in\s+[^:]+:\s*$"),
    re.compile(r"\bwhile\s+[^:]+:\s*$"),
    re.compile(r"\bif\s+[^:]+:\s*$"),
    re.compile(r"\b(class|def)\s+\w+[^(]*:\s*$"),
]

_BASH_ONLY_PATTERNS = [
    (re.compile(r"\bsource\s"), "source", "use . (dot) instead of source"),
    (re.compile(r"\[\[\s+"), "[[", "use [ instead of [[ for POSIX sh"),
    (re.compile(r"\$\{(\w+)[/#]"), "${VAR//x/y}", "bash-only parameter expansion, use sed/tr instead"),
]

_SHELL_OPS_IN_CMDS = re.compile(r"&&|\|\||[;|><]|\$\(|2>&1")
_COMMAND_SEPARATORS = frozenset({"&&", "||", ";", "|"})
_SCRIPT_SUFFIXES = (".py", ".sh")
_SYSTEM_ABSOLUTE_PATHS = frozenset({"/bin/sh", "/bin/bash", "/usr/bin/env", "/dev/null"})
_SEARCH_PROGRAMS = frozenset({"grep", "egrep", "rg"})
# END_BLOCK_CONSTANTS


# START_BLOCK_PARSING
def _contains_unquoted_shell_word(command: str, word: str) -> bool:
    """Return whether *word* occurs outside single/double quoted data."""
    quote: str | None = None
    escaped = False
    unquoted: list[str] = []
    for char in command:
        if escaped:
            escaped = False
            unquoted.append(" ")
            continue
        if quote is not None:
            if char == quote:
                quote = None
            elif char == "\\" and quote == '"':
                escaped = True
            unquoted.append(" ")
            continue
        if char in {"'", '"'}:
            quote = char
            unquoted.append(" ")
            continue
        if char == "\\":
            escaped = True
            unquoted.append(" ")
            continue
        unquoted.append(char)
    return re.search(rf"\b{re.escape(word)}\b", "".join(unquoted)) is not None


def _command_segments(command: str) -> list[list[str]]:
    """Split a command into simple invocations without interpreting shell syntax."""
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return []
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _COMMAND_SEPARATORS:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _first_program_index(tokens: list[str]) -> int | None:
    """Return the executable index after shell negation and NAME=value prefixes."""
    index = 0
    while index < len(tokens) and tokens[index] == "!":
        index += 1
    while index < len(tokens) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[index]):
        index += 1
    return index if index < len(tokens) else None


def _negative_search_test_targets(command: str) -> list[str]:
    """Return test paths scanned by a shell-negated text search."""
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return []
    if len(tokens) < 4 or tokens[0] != "!" or Path(tokens[1]).name not in _SEARCH_PROGRAMS:
        return []

    pattern_seen = False
    targets: list[str] = []
    for token in tokens[2:]:
        if token.startswith("-"):
            continue
        if not pattern_seen:
            pattern_seen = True
            continue
        normalized = token.removeprefix("./").rstrip("/")
        if normalized in {"test", "tests"} or normalized.startswith(("test/", "tests/")):
            targets.append(token)
    return targets


def _relative_command_path(value: str, target_repo_root: Path | None) -> str | None:
    """Normalize a command path to target-repository-relative form when possible."""
    path = Path(value)
    if path.is_absolute():
        if target_repo_root is None:
            return None
        try:
            return path.relative_to(target_repo_root.resolve()).as_posix()
        except ValueError:
            return None
    if ".." in path.parts:
        return None
    normalized = path.as_posix()
    return normalized[2:] if normalized.startswith("./") else normalized


def _known_script_paths(env: ExecutionEnvironment) -> set[str]:
    """Extract script paths from discovered files and verification overrides."""
    known = set(env.executable_scripts)
    for entrypoint in env.verification_entrypoints:
        if entrypoint.endswith(_SCRIPT_SUFFIXES):
            known.add(entrypoint)
            continue
        try:
            tokens = shlex.split(entrypoint, posix=True)
        except ValueError:
            continue
        known.update(token for token in tokens if token.endswith(_SCRIPT_SUFFIXES))
    return known


def _python_module_exists(
    module: str,
    python_program: str,
    target_repo_root: Path | None,
) -> bool:
    """Check repository and venv module paths without executing target code."""
    if not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", module):
        return False
    root = (target_repo_root or Path.cwd()).resolve()
    module_path = Path(*module.split("."))
    if module.split(".", 1)[0] in sys.stdlib_module_names:
        return True
    for base in (root, root / "src"):
        if (base / module_path).with_suffix(".py").is_file():
            return True
        if (base / module_path / "__init__.py").is_file():
            return True
    for site_packages in root.glob(".venv/lib/python*/site-packages"):
        if (site_packages / module_path).with_suffix(".py").is_file():
            return True
        if (site_packages / module_path / "__init__.py").is_file():
            return True

    if "/" not in python_program:
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, AttributeError, ValueError):
            return False
    return False
# END_BLOCK_PARSING


# START_BLOCK_VALIDATOR
# START_FUNCTION_CONTRACT
# name: validate_command
# purpose: Validate one packet verification command against discovered environment facts.
# inputs: result — CompileResult; cmd — shell command; env — ExecutionEnvironment; title and field_path — packet context; target_repo_root — optional target root.
# returns: None; diagnostics are appended to result.
# side_effects: Reads target paths and runtime-discovered facts without executing commands.
# emitted_logs: None.
# error_behavior: Invalid command assumptions become compiler errors or warnings.
# END_FUNCTION_CONTRACT
def validate_command(
    result: CompileResult,
    cmd: str,
    env: ExecutionEnvironment,
    title: str,
    field_path: str,
    allow_planned_venv: bool = False,
    target_repo_root: Path | None = None,
) -> None:
    shell_is_bash = Path(env.shell).name == "bash"
    python_candidates = set(env.python_candidates)
    known_scripts = _known_script_paths(env)

    if not shell_is_bash and _contains_unquoted_shell_word(cmd, "source"):
        _add_error(
            result, "E_SHELL_SOURCE_UNDER_DASH",
            field_path, f"command uses 'source' but shell is {env.shell} (not bash)",
            title, "use '.' (dot) instead or run under bash",
        )

    if "source .venv" in cmd or "source venv" in cmd:
        _add_warning(
            result, "W_SHELL_SOURCE", field_path,
            "command uses 'source' for venv activation (bash-only)",
            title, "use '. .venv/bin/activate' or run python directly",
        )

    references_venv_activation = ".venv/bin/activate" in cmd
    references_venv_python = ".venv/bin/python" in cmd
    if references_venv_activation or references_venv_python:
        has_discovered_venv = any(
            candidate.endswith(".venv/bin/python")
            for candidate in python_candidates
        )
        if not has_discovered_venv and not allow_planned_venv:
            _add_error(
                result, "E_VENV_MISSING", field_path,
                "command references venv but target repo has no .venv",
                title,
                "use a Python path reported by runtime discovery or create the venv explicitly",
            )
        elif allow_planned_venv and not has_discovered_venv:
            _add_warning(
                result, "W_VENV_PLANNED_BOOTSTRAP", field_path,
                "command references a project venv created by an earlier bootstrap packet",
                title, "keep the bootstrap packet before all packets that use this venv",
            )
        elif references_venv_activation:
            _add_warning(
                result, "W_VENV_ACTIVATE_IN_WORKTREE", field_path,
                "venv exists in target repo but may not exist in worktree; "
                "activation will fail at runtime in worktree",
                title,
                "run the discovered repository-relative Python directly instead of activation: "
                f"{next(iter(env.python_candidates), '.venv/bin/python')} -m pytest ...",
            )

    for segment in _command_segments(cmd):
        program_index = _first_program_index(segment)
        if program_index is None:
            continue
        program = segment[program_index]
        program_name = Path(program).name

        for token in segment:
            if not token.startswith("/") or token in _SYSTEM_ABSOLUTE_PATHS:
                continue
            relative = _relative_command_path(token, target_repo_root)
            if relative is not None:
                allowed_paths = python_candidates | known_scripts | set(env.config_sources)
                if relative not in allowed_paths:
                    _add_error(
                        result, "E_TARGET_ABSOLUTE_PATH_UNDISCOVERED", field_path,
                        f"absolute target path '{token}' was not reported by runtime discovery",
                        title, "use a repository-relative path reported in deterministic environment facts",
                    )
            elif token.startswith(("/opt/", "/home/", "/workspace/")):
                _add_error(
                    result, "E_TARGET_ABSOLUTE_PATH_UNDISCOVERED", field_path,
                    f"absolute target-specific path '{token}' does not belong to the probed repository",
                    title, "use repository-relative paths from deterministic environment facts",
                )

        is_python = bool(re.fullmatch(r"python\d*(?:\.\d+)?", program_name))
        if is_python:
            normalized_program = _relative_command_path(program, target_repo_root)
            program_is_known = (
                program in python_candidates
                or normalized_program in python_candidates
            )
            if not program_is_known and not allow_planned_venv:
                _add_error(
                    result, "E_EXECUTABLE_NOT_DISCOVERED", field_path,
                    f"Python executable '{program}' was not reported by runtime discovery",
                    title, "use one of ExecutionEnvironment.python_candidates",
                )
                continue
            if program_is_known and "/" in program and not allow_planned_venv:
                executable_relative = _relative_command_path(program, target_repo_root)
                executable_path = (
                    target_repo_root / executable_relative
                    if target_repo_root is not None and executable_relative is not None
                    else None
                )
                if (
                    executable_path is None
                    or not executable_path.is_file()
                    or not os.access(executable_path, os.X_OK)
                ):
                    _add_error(
                        result, "E_EXECUTABLE_PATH_MISSING", field_path,
                        f"Python executable path '{program}' does not exist or is not executable",
                        title, "fix the grace/project.yaml override or use a discovered executable",
                    )
                    continue

            arguments = segment[program_index + 1:]
            if "-m" in arguments:
                module_index = arguments.index("-m") + 1
                if module_index < len(arguments):
                    module = arguments[module_index]
                    if not allow_planned_venv and not _python_module_exists(
                        module, program, target_repo_root,
                    ):
                        _add_error(
                            result, "E_PYTHON_MODULE_MISSING", field_path,
                            f"Python module '{module}' does not exist in the probed environment",
                            title, "use an existing module or a discovered verification script path",
                        )
                continue

            script = next(
                (
                    argument for argument in arguments
                    if not argument.startswith("-") and argument.endswith(_SCRIPT_SUFFIXES)
                ),
                None,
            )
            if script is not None:
                _validate_script_path(
                    result, script, known_scripts, title, field_path, target_repo_root,
                )
            continue

        script: str | None = None
        if program.endswith(_SCRIPT_SUFFIXES):
            script = program
        elif program_name in {"sh", "bash"}:
            script = next(
                (
                    argument for argument in segment[program_index + 1:]
                    if not argument.startswith("-") and argument.endswith(_SCRIPT_SUFFIXES)
                ),
                None,
            )
        if script is not None:
            _validate_script_path(
                result, script, known_scripts, title, field_path, target_repo_root,
                require_executable=script == program,
                executable_scripts=set(env.executable_scripts),
            )
        elif "/" in program:
            relative_program = _relative_command_path(program, target_repo_root)
            executable_path = (
                target_repo_root / relative_program
                if target_repo_root is not None and relative_program is not None
                else None
            )
            if (
                executable_path is None
                or not executable_path.is_file()
                or not os.access(executable_path, os.X_OK)
            ):
                _add_error(
                    result, "E_EXECUTABLE_PATH_MISSING", field_path,
                    f"executable path '{program}' does not exist or is not executable",
                    title, "use a discovered executable script or a command available on PATH",
                )

    test_targets = _negative_search_test_targets(cmd)
    if test_targets:
        _add_error(
            result, "E_NEGATIVE_SEARCH_SCANS_TESTS", field_path,
            "shell-negated absence search scans test paths and can match its own regression assertion: "
            + ", ".join(test_targets),
            title, "scan implementation/configuration paths only; prove the same absence separately in tests",
        )

    if cmd.startswith("grep ") or cmd.startswith("egrep "):
        words = cmd.split()
        if len(words) >= 4:
            idx = 1
            while idx < len(words) and words[idx].startswith("-"):
                idx += 1
            if idx + 2 < len(words):
                next_word = words[idx + 1]
                if (
                    not ("/" in next_word or next_word.endswith((".py", ".yml", ".yaml", ".json", ".md", ".sh")))
                    and not (next_word.startswith("'") or next_word.startswith('"'))
                ):
                    pattern_combined = " ".join(words[idx:idx + 2])
                    _add_warning(
                        result, "W_GREP_UNQUOTED_SPACE", field_path,
                        f"grep pattern '{pattern_combined}' has spaces without quotes "
                        f"— '{words[idx + 1]}' will be treated as a filename argument",
                        title, f"use single quotes: '...{pattern_combined}...'",
                    )

    if cmd.startswith("python3 -c ") or cmd.startswith("python -c "):
        code = cmd.split("-c ", 1)[1] if "-c " in cmd else ""
        if code.startswith("'") and "'" in code[1:]:
            code = code.split("'")[1]
        elif code.startswith('"') and '"' in code[1:]:
            code = code.split('"')[1]
        for pat in _INVALID_PY_PATTERNS:
            if pat.search(code):
                _add_error(
                    result, "E_PYTHON_INVALID_ONELINER", field_path,
                    f"inline Python has invalid one-liner syntax: {pat.pattern[:40]}...",
                    title, "for/while/if/class/def cannot be one-liners; use comprehensions or wrap in exec()",
                )
                break

        non_quoted = cmd.split("-c ", 1)[1] if "-c " in cmd else ""
        if not (non_quoted.startswith("'") or non_quoted.startswith('"')):
            _add_warning(
                result, "W_PYTHON_C_UNQUOTED", field_path,
                "python3 -c argument is not quoted; only first word will be executed",
                title, f"use single quotes: python3 -c '{non_quoted[:50]}...'",
            )

    if not shell_is_bash:
        for pattern, feature, fix in _BASH_ONLY_PATTERNS:
            matched = (
                _contains_unquoted_shell_word(cmd, "source")
                if feature == "source"
                else pattern.search(cmd) is not None
            )
            if matched:
                if feature == "source" and ("venv" in cmd.lower() or "activate" in cmd.lower()):
                    continue
                _add_error(
                    result, "E_BASH_SYNTAX_UNDER_SH", field_path,
                    f"command uses bash-only feature '{feature}' but shell is {env.shell}",
                    title, fix,
                )

    if _SHELL_OPS_IN_CMDS.search(cmd):
        pass
# END_BLOCK_VALIDATOR


# START_BLOCK_SCRIPT_PATH
def _validate_script_path(
    result: CompileResult,
    script: str,
    known_scripts: set[str],
    title: str,
    field_path: str,
    target_repo_root: Path | None,
    *,
    require_executable: bool = False,
    executable_scripts: set[str] | None = None,
) -> None:
    relative = _relative_command_path(script, target_repo_root)
    script_path = (
        target_repo_root / relative
        if target_repo_root is not None and relative is not None
        else None
    )
    is_known = relative in known_scripts if relative is not None else False
    exists = script_path.is_file() if script_path is not None else is_known
    executable = (
        relative in (executable_scripts or set())
        if require_executable
        else True
    )
    if is_known and exists and executable:
        return
    _add_error(
        result, "E_SCRIPT_PATH_UNKNOWN", field_path,
        f"script path '{script}' is missing, unknown, or not executable",
        title, "use a script listed in ExecutionEnvironment.verification_entrypoints",
    )
# END_BLOCK_SCRIPT_PATH
