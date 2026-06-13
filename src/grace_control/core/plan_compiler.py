# ############################################################################
# AI_HEADER: plan_compiler
# ROLE: Deterministic preflight validator — compiles architect plan before
#        coder execution, rejecting invalid packets before runtime.
# ############################################################################

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

from grace_control.core.execution_environment import ExecutionEnvironment
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("plan_compiler")


class CompileError(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    packet_title: str | None = None
    field_path: str
    message: str
    suggestion: str | None = None

    model_config = {"frozen": False}


class CompileResult(BaseModel):
    ok: bool
    errors: list[CompileError] = []
    warnings: list[CompileError] = []
    normalized_plan: dict | None = None

    model_config = {"frozen": False}


# ── Grep pattern with unquoted spaces ──────────────────────────────────
_GREP_SPACE_PATTERN = re.compile(
    r'\bgrep\s+(?:-[A-Za-z]+\s+)*([^-\'\"][\w\s]+?)\s+\S+'
)


# ── Invalid Python one-liner patterns ─────────────────────────────────
_INVALID_PY_PATTERNS = [
    # for/while at end of line with colon (no body possible)
    re.compile(r'\bfor\s+\w+\s+in\s+[^:]+:\s*$'),
    re.compile(r'\bwhile\s+[^:]+:\s*$'),
    re.compile(r'\bif\s+[^:]+:\s*$'),
    # class/def at end of file (no body possible)
    re.compile(r'\b(class|def)\s+\w+[^(]*:\s*$'),
]


# ── Bash-only syntax patterns ──────────────────────────────────────────
_BASH_ONLY_PATTERNS = [
    (re.compile(r'\bsource\s'), "source", "use . (dot) instead of source"),
    (re.compile(r'\[\[\s+'), "[[", "use [ instead of [[ for POSIX sh"),
    (re.compile(r'\$\{(\w+)[/#]'), "${VAR//x/y}", "bash-only parameter expansion, use sed/tr instead"),
]


# ── Shell operators in argv list (require shell=True) ──────────────────
_SHELL_OPS_IN_CMDS = re.compile(r'&&|\|\||[;|><]|\$\(|2>&1')


def _add_error(
    result: CompileResult,
    code: str,
    field_path: str,
    message: str,
    packet_title: str | None = None,
    suggestion: str | None = None,
) -> None:
    result.errors.append(
        CompileError(
            code=code,
            severity="error",
            packet_title=packet_title,
            field_path=field_path,
            message=message,
            suggestion=suggestion,
        )
    )
    result.ok = False


def _add_warning(
    result: CompileResult,
    code: str,
    field_path: str,
    message: str,
    packet_title: str | None = None,
    suggestion: str | None = None,
) -> None:
    result.warnings.append(
        CompileError(
            code=code,
            severity="warning",
            packet_title=packet_title,
            field_path=field_path,
            message=message,
            suggestion=suggestion,
        )
    )


class PlanCompiler:

    def compile_plan(
        self,
        plan: dict,
        env: ExecutionEnvironment | None = None,
    ) -> CompileResult:
        if env is None:
            from grace_control.core.execution_environment import probe_execution_environment
            env = probe_execution_environment()

        result = CompileResult(ok=True)

        waves = plan.get("waves", [])
        if not waves:
            return result  # Empty plan is valid (nothing to do)

        for wi, wave in enumerate(waves):
            for pi, packet in enumerate(wave.get("packets", [])):
                title = packet.get("title", f"wave-{wi}-pkt-{pi}")
                scope = packet.get("scope", [])
                verification = packet.get("verification", {})
                evidence = packet.get("expected_evidence", [])
                role = packet.get("role", "coder")
                description = packet.get("description", "")
                acceptance = packet.get("acceptance_criteria", [])
                coder_instructions = packet.get("coder_instructions", [])

                t0 = verification.get("t0", [])
                t1 = verification.get("t1", [])
                t2 = verification.get("t2", [])

                # ── 1. Command syntax validation ──────────────────
                all_cmds = [(t0, "t0"), (t1, "t1"), (t2, "t2")]
                for cmds, stage_name in all_cmds:
                    for ci, cmd in enumerate(cmds):
                        if isinstance(cmd, str):
                            self._validate_cmd(
                                result, cmd, env, title, f"verification.{stage_name}[{ci}]"
                            )

                # ── 2. Scope vs acceptance ────────────────────────
                self._validate_scope_acceptance(
                    result, title, scope, t1, acceptance, coder_instructions, role
                )

                # ── 3. Evidence contract ──────────────────────────
                self._validate_evidence(
                    result, title, evidence, role, description, scope
                )

                # ── 4. Role/scope consistency ─────────────────────
                self._validate_role_scope(result, title, role, scope, description)

        _log.info("compile_done", ok=result.ok, errors=len(result.errors),
                  warnings=len(result.warnings))
        return result

    def _validate_cmd(
        self,
        result: CompileResult,
        cmd: str,
        env: ExecutionEnvironment,
        title: str,
        field_path: str,
    ) -> None:
        # Shell incompatibility: source under dash
        if not env.shell_is_bash and " source " in cmd:
            _add_error(
                result, "E_SHELL_SOURCE_UNDER_DASH",
                field_path, f"command uses 'source' but shell is {env.shell} (not bash)",
                title, "use '.' (dot) instead or run under bash",
            )

        # Source in general → warn (should use .)
        if "source .venv" in cmd or "source venv" in cmd:
            _add_warning(
                result, "W_SHELL_SOURCE",
                field_path, "command uses 'source' for venv activation (bash-only)",
                title, "use '. .venv/bin/activate' or run python directly",
            )

        # Missing venv reference
        if ".venv/bin/activate" in cmd or ".venv/bin/python" in cmd:
            if not env.has_api_venv:
                _add_error(
                    result, "E_VENV_MISSING",
                    field_path,
                    "command references venv but target repo has no .venv",
                    title,
                    f"system python3 at {env.api_python_path} is available; "
                    "use it directly or install venv in target repo",
                )
            else:
                _add_warning(
                    result, "W_VENV_ACTIVATE_IN_WORKTREE",
                    field_path,
                    "venv exists in target repo but may not exist in worktree; "
                    "activation will fail at runtime in worktree",
                    title,
                    "use the absolute python path instead of activation: "
                    f"{env.api_python_path} -m pytest ...",
                )

        # Unsafe grep splitting
        if cmd.startswith("grep ") or cmd.startswith("egrep "):
            # Check the raw string for unquoted multi-word patterns
            # Pattern: grep -c word1 word2 file → word1+word2 is an unquoted pattern
            # The command runner will see word2 as a filename argument
            words = cmd.split()
            if len(words) >= 4:
                # After grep + flags, check if there are 2+ consecutive non-flag
                # non-file words before the last argument (the file path)
                idx = 1
                while idx < len(words) and words[idx].startswith("-"):
                    idx += 1
                # words[idx] is the first non-flag word (pattern start)
                # If words[idx+1] looks like a pattern continuation (not a path, not quoted)
                if idx + 2 < len(words):
                    next_word = words[idx + 1]
                    last_word = words[-1]
                    # If next_word doesn't look like a file path and isn't quoted
                    if (not ("/" in next_word or next_word.endswith((".py",".yml",".yaml",".json",".md",".sh")))
                        and not (next_word.startswith("'") or next_word.startswith('"'))):
                        pattern_combined = " ".join(words[idx:idx+2])
                        _add_warning(
                            result, "W_GREP_UNQUOTED_SPACE",
                            field_path,
                            f"grep pattern '{pattern_combined}' has spaces without quotes "
                            f"— '{words[idx+1]}' will be treated as a filename argument",
                            title, f"use single quotes: '...{pattern_combined}...'",
                        )

        # Invalid Python one-liners
        if cmd.startswith("python3 -c ") or cmd.startswith("python -c "):
            code = cmd.split("-c ", 1)[1] if "-c " in cmd else ""
            # Try to extract code (may be quoted)
            if code.startswith("'") and "'" in code[1:]:
                code = code.split("'")[1]
            elif code.startswith('"') and '"' in code[1:]:
                code = code.split('"')[1]
            for pat in _INVALID_PY_PATTERNS:
                if pat.search(code):
                    _add_error(
                        result, "E_PYTHON_INVALID_ONELINER",
                        field_path, f"inline Python has invalid one-liner syntax: {pat.pattern[:40]}...",
                        title, "for/while/if/class/def cannot be one-liners; use comprehensions or wrap in exec()",
                    )
                    break

            # Check for missing quotes around -c argument
            non_quoted = cmd.split("-c ", 1)[1] if "-c " in cmd else ""
            if not (non_quoted.startswith("'") or non_quoted.startswith('"')):
                _add_warning(
                    result, "W_PYTHON_C_UNQUOTED",
                    field_path, "python3 -c argument is not quoted; only first word will be executed",
                    title, f"use single quotes: python3 -c '{non_quoted[:50]}...'",
                )

        # Bash-only syntax under sh
        if not env.shell_is_bash:
            for pattern, feature, fix in _BASH_ONLY_PATTERNS:
                if pattern.search(cmd):
                    # Skip 'source' when it's for venv activation (caught by E_VENV_MISSING)
                    if feature == "source" and ("venv" in cmd.lower() or "activate" in cmd.lower()):
                        continue
                    _add_error(
                        result, "E_BASH_SYNTAX_UNDER_SH",
                        field_path, f"command uses bash-only feature '{feature}' but shell is {env.shell}",
                        title, fix,
                    )

        # Shell operators that need shell=True
        if _SHELL_OPS_IN_CMDS.search(cmd):
            pass  # shell=True is now default for non-python3, so this is fine

    def _validate_scope_acceptance(
        self,
        result: CompileResult,
        title: str,
        scope: list[str],
        t1: list[str],
        acceptance: list[str],
        coder_instructions: list[str],
        role: str,
    ) -> None:
        # Check if T1 runs tests on files outside scope
        test_files_in_t1: set[str] = set()
        for cmd in (t1 if isinstance(t1, list) else []):
            cmd_s = str(cmd) if isinstance(cmd, str) else " ".join(cmd)
            import re as _re
            test_refs = _re.findall(r'tests?/[\w/_.-]+\.py', cmd_s)
            test_files_in_t1.update(test_refs)

        test_files_in_scope: set[str] = set()
        for s in scope:
            if "test" in s.lower():
                test_files_in_scope.add(s)

        tests_outside = test_files_in_t1 - test_files_in_scope

        # Check if the packet deletes/renames symbols
        deletes_symbol = False
        all_text = " ".join(coder_instructions + [str(acceptance)])
        if any(
            kw in all_text.lower()
            for kw in ("remove", "delete", "rename", "move ", "extract from")
        ):
            # Negative patterns: phrases like "do not delete", "no renames"
            # should NOT trigger the detection.
            neg = re.compile(
                r'\b(do not|don.t|no|without|never|avoid|prevent)\s+'
                r'(remove|delet|renam|mov|extract)\w*\b',
                re.IGNORECASE,
            )
            has_negative = neg.search(all_text)
            if not has_negative:
                deletes_symbol = True

        # Error only when: tests outside scope + delete/rename + no shim
        if tests_outside and deletes_symbol and role == "coder":
            has_shim = any(
                kw in all_text.lower()
                for kw in ("shim", "compatibility wrapper", "keep old", "deprecated stub",
                          "re-export", "backward compat")
            )
            if not has_shim:
                _add_error(
                    result, "E_SCOPE_ACCEPTANCE_IMPOSSIBLE",
                    f"verification.t1",
                    f"T1 runs tests {tests_outside} outside write scope {scope}, "
                    f"packet deletes/renames/moves symbols, and no compatibility "
                    f"shim is described",
                    title,
                    "keep compatibility shim/wrapper/re-export for old symbol, "
                    "or include test files in write scope",
                )

    def _validate_evidence(
        self,
        result: CompileResult,
        title: str,
        evidence: list[dict],
        role: str,
        description: str,
        scope: list[str],
    ) -> None:
        for ei, ev in enumerate(evidence):
            if not isinstance(ev, dict):
                continue
            kind = ev.get("kind", "")
            patterns = ev.get("artifact_patterns", [])
            required = ev.get("required", True)

            # kind=diff with pattern=agent.patch → wrong
            if kind == "diff" and required:
                if "agent.patch" in str(patterns):
                    _add_warning(
                        result, "W_EVIDENCE_DIFF_AGENT_PATCH",
                        f"expected_evidence[{ei}]",
                        "expected_evidence uses kind=diff with pattern=agent.patch — "
                        "agent.patch never matches changed_files from git diff",
                        title, "use kind=diff without pattern, or kind=file with specific filenames",
                    )

            # Verification-only packet requiring diff
            if kind == "diff" and required and role == "coder":
                no_code = "no code changes" in description.lower() or "no files need modification" in description.lower()
                if no_code:
                    _add_error(
                        result, "E_EVIDENCE_DIFF_VERIFICATION_ONLY",
                        f"expected_evidence[{ei}]",
                        "packet is verification-only but requires diff evidence",
                        title, "remove diff evidence requirement or change role to verifier",
                    )

            # No scope files but requires diff
            if kind == "diff" and required and not scope:
                _add_error(
                    result, "E_EVIDENCE_DIFF_EMPTY_SCOPE",
                    f"expected_evidence[{ei}]",
                    "packet requires diff evidence but has empty write scope",
                    title, "add target files to scope or remove diff evidence",
                )

    def _validate_role_scope(
        self,
        result: CompileResult,
        title: str,
        role: str,
        scope: list[str],
        description: str,
    ) -> None:
        # Coder packets must have scope
        if role == "coder" and not scope:
            _add_error(
                result, "E_CODER_EMPTY_SCOPE",
                "scope", "coder packet has empty write scope — nothing to write",
                title, "add target files to scope or change role to verifier",
            )

        # Coder packets described as verification-only
        if role == "coder" and (
            "no code changes" in description.lower()
            or "no files need modification" in description.lower()
            or "verification-only" in description.lower()
        ):
            _add_error(
                result, "E_VERIFICATION_ONLY_CODER",
                "role", "coder packet described as verification-only",
                title, "change role to 'verifier' or add files to modify",
            )

        # Frozen scope vs scope overlap
        pass  # handled by _strip_frozen_overlap in build_packet_contract


# ── Public convenience function ────────────────────────────────────────

def compile_plan(plan: dict, env: ExecutionEnvironment | None = None) -> CompileResult:
    return PlanCompiler().compile_plan(plan, env)
