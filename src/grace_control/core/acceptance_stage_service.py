# ############################################################################
# AI_HEADER: acceptance_stage_service — command-backed T0/T1/T2 acceptance stages
# ROLE: Own the deterministic command execution and scope preparation used by
#       AcceptancePipeline. It reuses the authoritative scope, gate and runner
#       boundaries while keeping the public pipeline as the compatibility facade.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Prepare T0 scope paths and execute T0, T1 and T2 acceptance stages.
# inputs: ExecutionPacketContract, changed files, worktree paths, ScopeGuard and
#         CommandRunner-compatible dependencies.
# returns: _T0Result or StageResult values with command origins and diagnostics.
# side_effects: Runs verification commands and writes command artifacts through
#               the injected CommandRunner.
# emitted_logs: t0_command_failed, t1_command_failed, t2_command_failed.
# error_behavior: Returns failed StageResult values for command/contract/scope
#                 failures; does not convert runner failures into exceptions.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AcceptanceStageExecutor
#     methods:
#       - build_t0_commands
#       - resolve_t0_scope_paths
#       - run_t0
#       - run_t1
#       - run_t2
#   - dataclass: _T0Result
# END_MODULE_MAP

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from grace_control.core.contracts import (
    AcceptanceProfile,
    CommandResult,
    ExecutionPacketContract,
    ScopeViolation,
    StageName,
    StageResult,
    StageStatus,
    validate_packet_contract,
)
from grace_control.core.gate_resolver import resolve_default_gates, resolve_default_t0
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("acceptance")

_SHELL_OPS_PATTERN = re.compile(r"(&&|\|\||\$\(|[|<>;])")


@dataclass(frozen=True)
class _T0Result:
    stage: StageResult
    scope_violations: list[ScopeViolation]


# START_BLOCK_STAGE_EXECUTOR
# START_FUNCTION_CONTRACT
# name: AcceptanceStageExecutor.__init__
# purpose: Initialize deterministic acceptance stage execution dependencies.
# inputs: repo_root — command base path; command_runner — runner-compatible command executor; scope_guard — scope validator; t0_command_template — fallback T0 command.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
class AcceptanceStageExecutor:

    def __init__(
        self,
        *,
        repo_root: Path,
        command_runner: Any,
        scope_guard: Any,
        t0_command_template: list[list[str]],
    ) -> None:
        self._root = repo_root.resolve()
        self._runner = command_runner
        self._scope = scope_guard
        self._t0_command_template = t0_command_template

    # START_FUNCTION_CONTRACT
    # name: AcceptanceStageExecutor.build_t0_commands
    # purpose: Resolve automatic T0 commands from the changed scope and gate resolver.
    # inputs: packet — execution contract; changed_files — changed paths; cwd — command worktree.
    # returns: Tuple of command values and matching origin labels.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Uses the configured Ruff fallback when no resolver command applies.
    # END_FUNCTION_CONTRACT
    def build_t0_commands(
        self,
        packet: ExecutionPacketContract,
        changed_files: list[str],
        cwd: Path | None = None,
    ) -> tuple[list[Any], list[str]]:
        scope_paths = self.resolve_t0_scope_paths(packet, changed_files, cwd=cwd)
        base = (cwd or self._root).resolve()
        commands, origins = resolve_default_t0(
            scope_paths,
            base,
            packet.acceptance_profile.value,
        )
        if commands:
            return commands, origins

        py_paths = [path for path in scope_paths if path.endswith(".py")]
        if py_paths:
            return [["python3", "-m", "ruff", "check", *py_paths]], [
                "auto:t0:ruff_fallback"
            ]
        return self._t0_command_template, ["auto:t0:ruff_src"]

    # START_FUNCTION_CONTRACT
    # name: AcceptanceStageExecutor.resolve_t0_scope_paths
    # purpose: Resolve existing allowed-scope and changed-file paths relative to the command cwd.
    # inputs: packet — execution contract; changed_files — changed paths; cwd — command worktree.
    # returns: Existing relative paths in stable first-seen order.
    # side_effects: Reads path existence from the worktree.
    # emitted_logs: None.
    # error_behavior: Paths outside cwd remain absolute; missing paths are omitted.
    # END_FUNCTION_CONTRACT
    def resolve_t0_scope_paths(
        self,
        packet: ExecutionPacketContract,
        changed_files: list[str],
        cwd: Path | None = None,
    ) -> list[str]:
        base = (cwd or self._root).resolve()
        candidates: list[str] = []
        seen: set[str] = set()

        for raw in packet.allowed_write_scope or []:
            if not raw or raw in seen:
                continue
            seen.add(raw)
            candidates.append(raw)

        for changed_file in changed_files:
            if changed_file in seen:
                continue
            seen.add(changed_file)
            candidates.append(changed_file)

        existing: list[str] = []
        for path_value in candidates:
            path = (base / path_value).resolve() if not Path(path_value).is_absolute() else Path(path_value)
            try:
                relative = path.relative_to(base)
            except ValueError:
                relative = path
            if path.exists():
                existing.append(str(relative))
        return existing

    # START_FUNCTION_CONTRACT
    # name: AcceptanceStageExecutor.run_t0
    # purpose: Validate packet/scope and execute the T0 scope and lint stage.
    # inputs: packet, changed_files, base_ref, head_ref, output_dir, cwd.
    # returns: _T0Result containing T0 StageResult and scope violations.
    # side_effects: Runs T0 commands through CommandRunner.
    # emitted_logs: t0_command_failed.
    # error_behavior: Returns failed T0 results for invalid contracts, strict scope violations or failed commands.
    # END_FUNCTION_CONTRACT
    def run_t0(
        self,
        packet: ExecutionPacketContract,
        changed_files: list[str] | None,
        base_ref: str | None,
        head_ref: str | None,
        *,
        output_dir: Path | None = None,
        cwd: Path | None = None,
    ) -> _T0Result:
        changed = changed_files or self._scope.get_changed_files(base_ref, head_ref)
        violations = self._scope.validate_changed_files(
            changed_files=changed,
            allowed_write_scope=packet.allowed_write_scope,
            frozen_scope=packet.frozen_scope,
        )
        errors = validate_packet_contract(packet)
        commands: list[CommandResult] = []

        if errors:
            return _T0Result(
                stage=StageResult(
                    name=StageName.T0_SCOPE_AND_LINT,
                    status=StageStatus.FAILED,
                    summary="invalid packet contract",
                    blocking_issues=errors,
                    commands=commands,
                ),
                scope_violations=violations,
            )

        if violations and packet.acceptance_profile == AcceptanceProfile.STRICT:
            return _T0Result(
                stage=StageResult(
                    name=StageName.T0_SCOPE_AND_LINT,
                    status=StageStatus.FAILED,
                    summary="scope guard failed",
                    blocking_issues=[f"scope violations: {item.path}" for item in violations],
                    commands=commands,
                ),
                scope_violations=violations,
            )

        if not changed:
            return _T0Result(
                stage=StageResult(
                    name=StageName.T0_SCOPE_AND_LINT,
                    status=StageStatus.PASSED,
                    summary="no changes to lint (empty diff)",
                    blocking_issues=[],
                    commands=[],
                ),
                scope_violations=violations,
            )

        explicit_t0 = packet.verification.get("t0", [])
        if explicit_t0:
            t0_commands = [self.verification_command(command) for command in explicit_t0]
            origins = ["architect:verification"] * len(explicit_t0)
        else:
            t0_commands, origins = self.build_t0_commands(packet, changed, cwd=cwd or self._root)

        for command in t0_commands:
            result = self._runner.run(
                command,
                output_dir=output_dir,
                cwd=cwd,
                shell=self.needs_shell(command),
            )
            commands.append(result)
            if not result.passed:
                command_text = self.command_text(command)
                _log.info(
                    "t0_command_failed",
                    command=command_text[:200],
                    exit_code=result.exit_code,
                    stderr=result.stderr[:500],
                    stdout=result.stdout[:500],
                )
                return _T0Result(
                    stage=StageResult(
                        name=StageName.T0_SCOPE_AND_LINT,
                        status=StageStatus.FAILED,
                        summary="T0 cheap check failed",
                        blocking_issues=[f"{command_text} failed: {result.stderr[:200]}"],
                        commands=commands,
                        command_origins=origins,
                    ),
                    scope_violations=violations,
                )

        summary = "T0 passed: scope clean, contract valid"
        summary += ", cheap checks ok" if t0_commands else ", no cheap commands configured"
        return _T0Result(
            stage=StageResult(
                name=StageName.T0_SCOPE_AND_LINT,
                status=StageStatus.PASSED,
                summary=summary,
                commands=commands,
                command_origins=origins,
            ),
            scope_violations=violations,
        )

    # START_FUNCTION_CONTRACT
    # name: AcceptanceStageExecutor.run_t1
    # purpose: Resolve, filter and execute targeted T1 verification commands.
    # inputs: packet — execution contract; changed_files — changed paths; run_dir — artifact directory; cwd — command worktree.
    # returns: T1 StageResult with profile-specific empty-command semantics.
    # side_effects: Runs T1 commands through CommandRunner.
    # emitted_logs: t1_command_failed.
    # error_behavior: Returns skipped/failed StageResult when no commands apply or a command fails.
    # END_FUNCTION_CONTRACT
    def run_t1(
        self,
        packet: ExecutionPacketContract,
        changed_files: list[str],
        *,
        run_dir: Path | None = None,
        cwd: Path | None = None,
    ) -> StageResult:
        base_path = (cwd or self._root).resolve()
        explicit_raw = packet.verification.get("t1")
        if isinstance(explicit_raw, list) and "t1" in packet.verification:
            commands = [self.verification_command(command) for command in explicit_raw]
            origins = ["architect:verification"] * len(explicit_raw) if explicit_raw else []
        else:
            defaults = resolve_default_gates(
                changed_files,
                packet.acceptance_profile.value,
                base_path,
            )
            commands = defaults["t1"]["commands"]
            origins = defaults["t1"]["origins"]

        commands, origins = self._filter_commands(
            commands,
            origins,
            ("guardrails.sh", "check_frontmatter", "check_secrets"),
        )
        results = [
            self._runner.run(
                command,
                output_dir=run_dir,
                cwd=cwd,
                shell=self.needs_shell(command),
            )
            for command in commands
        ]

        if not commands:
            if packet.acceptance_profile == AcceptanceProfile.FAST:
                return StageResult(
                    name=StageName.T1_TARGETED_TESTS,
                    status=StageStatus.SKIPPED,
                    summary="FAST profile without T1 commands",
                    skipped_reason="FAST profile without T1 commands",
                    command_origins=[],
                )
            return StageResult(
                name=StageName.T1_TARGETED_TESTS,
                status=StageStatus.FAILED,
                summary="NORMAL/STRICT requires T1 — no auto defaults and no explicit commands",
                blocking_issues=[
                    "no auto T1 defaults resolved and architect did not provide extra_verification.t1"
                ],
                command_origins=[],
            )

        failed = [result for result in results if not result.passed]
        if failed:
            for result in failed:
                _log.info(
                    "t1_command_failed",
                    command=result.command[:200],
                    exit_code=result.exit_code,
                    stderr=result.stderr[:500],
                    stdout=result.stdout[:500],
                )
            return StageResult(
                name=StageName.T1_TARGETED_TESTS,
                status=StageStatus.FAILED,
                summary=f"T1 failed: {len(failed)}/{len(results)} commands failed",
                commands=results,
                blocking_issues=[
                    f"command failed: {result.command} (exit={result.exit_code}) "
                    f"stderr={result.stderr[:200]} stdout={result.stdout[:200]}"
                    for result in failed
                ],
                command_origins=origins,
            )
        return StageResult(
            name=StageName.T1_TARGETED_TESTS,
            status=StageStatus.PASSED,
            summary=f"T1 passed: {len(results)} commands ok",
            commands=results,
            command_origins=origins,
        )

    # START_FUNCTION_CONTRACT
    # name: AcceptanceStageExecutor.run_t2
    # purpose: Resolve, filter and execute full T2 verification commands.
    # inputs: packet — execution contract; changed_files — changed paths; run_dir — artifact directory; cwd — command worktree.
    # returns: T2 StageResult with profile-specific skip and failure semantics.
    # side_effects: Runs T2 commands through CommandRunner.
    # emitted_logs: t2_command_failed.
    # error_behavior: Returns skipped/failed StageResult when no commands apply or a command fails.
    # END_FUNCTION_CONTRACT
    def run_t2(
        self,
        packet: ExecutionPacketContract,
        changed_files: list[str],
        *,
        run_dir: Path | None = None,
        cwd: Path | None = None,
    ) -> StageResult:
        base_path = (cwd or self._root).resolve()
        explicit = packet.verification.get("t2", [])
        if explicit:
            commands = [self.verification_command(command) for command in explicit]
            origins = ["architect:verification"] * len(explicit)
        else:
            defaults = resolve_default_gates(
                changed_files,
                packet.acceptance_profile.value,
                base_path,
            )
            commands = defaults["t2"]["commands"]
            origins = defaults["t2"]["origins"]

        commands, origins = self._filter_commands(
            commands,
            origins,
            ("guardrails.sh", "check_frontmatter", "check_secrets"),
        )
        if not commands:
            if packet.acceptance_profile == AcceptanceProfile.STRICT:
                return StageResult(
                    name=StageName.T2_FULL_TESTS,
                    status=StageStatus.SKIPPED,
                    summary="STRICT skipped T2 (guardrails filtered, no explicit commands)",
                    skipped_reason="guardrails.sh filtered out for packet-level run",
                    command_origins=[],
                )
            if packet.acceptance_profile == AcceptanceProfile.NORMAL:
                return StageResult(
                    name=StageName.T2_FULL_TESTS,
                    status=StageStatus.SKIPPED,
                    summary="NORMAL without T2 commands",
                    skipped_reason="no verification.t2 configured",
                    command_origins=[],
                )
            return StageResult(
                name=StageName.T2_FULL_TESTS,
                status=StageStatus.SKIPPED,
                summary="FAST always skips T2",
                skipped_reason="FAST profile skips T2",
                command_origins=[],
            )

        results = [
            self._runner.run(
                command,
                output_dir=run_dir,
                cwd=cwd,
                shell=self.needs_shell(command),
            )
            for command in commands
        ]
        failed = [result for result in results if not result.passed]
        if failed:
            for result in failed:
                _log.info(
                    "t2_command_failed",
                    command=result.command[:200],
                    exit_code=result.exit_code,
                    stderr=result.stderr[:500],
                    stdout=result.stdout[:500],
                )
            return StageResult(
                name=StageName.T2_FULL_TESTS,
                status=StageStatus.FAILED,
                summary=f"T2 failed: {len(failed)}/{len(results)} commands failed",
                commands=results,
                blocking_issues=[
                    f"full check failed: {result.command} (exit={result.exit_code}) "
                    f"stderr={result.stderr[:200]} stdout={result.stdout[:200]}"
                    for result in failed
                ],
                command_origins=origins,
            )
        return StageResult(
            name=StageName.T2_FULL_TESTS,
            status=StageStatus.PASSED,
            summary=f"T2 passed: {len(results)} commands ok",
            commands=results,
            command_origins=origins,
        )

    # START_FUNCTION_CONTRACT
    # name: AcceptanceStageExecutor._filter_commands
    # purpose: Remove repository-wide guardrail commands from packet-level stages while preserving order and origins.
    # inputs: commands — command values; origins — matching labels; excluded — textual filters.
    # returns: Filtered command values and matching origin labels.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Pairs commands and origins using their existing zip semantics.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _filter_commands(
        commands: list[Any],
        origins: list[str],
        excluded: tuple[str, ...],
    ) -> tuple[list[Any], list[str]]:
        filtered_commands: list[Any] = []
        filtered_origins: list[str] = []
        for command, origin in zip(commands, origins, strict=False):
            joined = " ".join(command) if isinstance(command, list) else str(command)
            if any(marker in joined for marker in excluded):
                continue
            filtered_commands.append(command)
            filtered_origins.append(origin)
        return filtered_commands, filtered_origins

    # START_FUNCTION_CONTRACT
    # name: AcceptanceStageExecutor.needs_shell
    # purpose: Decide whether a packet command requires explicit shell execution.
    # inputs: cmd — shell string or argv list.
    # returns: True for shell operators, negation or leading environment assignments; otherwise False.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Treats argv lists as non-shell commands.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def needs_shell(cmd: Any) -> bool:
        if isinstance(cmd, list):
            return False
        command = str(cmd)
        if _SHELL_OPS_PATTERN.search(command) or command.lstrip().startswith("! "):
            return True
        return AcceptanceStageExecutor.has_env_assignment_prefix(command)

    # START_FUNCTION_CONTRACT
    # name: AcceptanceStageExecutor.has_env_assignment_prefix
    # purpose: Detect a POSIX NAME=value prefix before a shell command.
    # inputs: cmd_str — command string.
    # returns: True when the first token is a valid environment assignment.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Empty or malformed prefixes return False.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def has_env_assignment_prefix(cmd_str: str) -> bool:
        tokens = cmd_str.strip().split()
        if not tokens:
            return False
        first = tokens[0]
        equals = first.find("=")
        if equals <= 0:
            return False
        name = first[:equals]
        if not (name[0].isalpha() or name[0] == "_"):
            return False
        return all(char.isalnum() or char == "_" for char in name)

    # START_FUNCTION_CONTRACT
    # name: AcceptanceStageExecutor.verification_command
    # purpose: Preserve packet shell strings and copy argv lists for execution.
    # inputs: raw_command — packet verification command.
    # returns: Original string or copied argv list.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def verification_command(raw_command: Any) -> Any:
        return raw_command if isinstance(raw_command, str) else list(raw_command)

    # START_FUNCTION_CONTRACT
    # name: AcceptanceStageExecutor.command_text
    # purpose: Render a command for diagnostics without changing its execution form.
    # inputs: command — shell string or argv list.
    # returns: Human-readable command string.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def command_text(command: Any) -> str:
        return " ".join(command) if isinstance(command, list) else str(command)

# END_BLOCK_STAGE_EXECUTOR
