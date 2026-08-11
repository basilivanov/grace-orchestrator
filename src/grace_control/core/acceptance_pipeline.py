# ############################################################################
# AI_HEADER: acceptance_pipeline — compatibility facade for deterministic acceptance
# ROLE: Preserve the public acceptance and replay entry points while coordinating
#       T0/T1/T2, frontend routing, evidence checks and final report composition.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run the deterministic acceptance pipeline and expose stable replay
#          entry points used by packet execution and developer tooling.
# inputs: ExecutionPacketContract, legacy result, project/worktree paths, refs,
#         branch and run-directory metadata.
# returns: AcceptanceReport, or ValueError for an unsupported replay stage.
# side_effects: Runs external commands, writes command/frontend artifacts, persists
#               stage instrumentation and propagates GRACE_BASE_SHA.
# emitted_logs: None directly; command failures are logged by the stage owner.
# error_behavior: Stage failures become non-accepted reports; replay preserves
#                 the existing unsupported-stage ValueError contract.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: run_acceptance_pipeline
#   - function: run_acceptance_stage_replay
#   - function: _run_frontend_stages
#   - class: AcceptancePipeline
#     methods:
#       - run
# END_MODULE_MAP

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from grace_control.core.acceptance_frontend_service import (
    commands_to_results,
    run_frontend_stages,
)
from grace_control.core.acceptance_stage_service import (
    AcceptanceStageExecutor,
    _T0Result,
)
from grace_control.core.command_runner import CommandRunner
from grace_control.core.contracts import (
    AcceptanceProfile,
    AcceptanceReport,
    CommandResult,
    ExecutionPacketContract,
    FinalVerdict,
    StageName,
    StageResult,
    StageStatus,
)
from grace_control.core.evidence import EvidenceCollector, check_expected_evidence
from grace_control.core.scope_guard import ScopeGuard, get_changed_files
from grace_control.core.stage_instrumentation import stage
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("acceptance")


# START_BLOCK_ENTRYPOINT_HELPERS
# START_FUNCTION_CONTRACT
# name: _new_pipeline
# purpose: Build the compatibility facade with authoritative runner and scope dependencies.
# inputs: project_root — repository root; worktree_path — command worktree.
# returns: Configured AcceptancePipeline.
# side_effects: Constructs CommandRunner and ScopeGuard instances.
# emitted_logs: None.
# error_behavior: Propagates dependency construction errors as before.
# END_FUNCTION_CONTRACT
def _new_pipeline(project_root: Path, worktree_path: Path) -> AcceptancePipeline:
    return AcceptancePipeline(
        repo_root=project_root,
        command_runner=CommandRunner(worktree_path),
        scope_guard=ScopeGuard(worktree_path),
    )


# START_FUNCTION_CONTRACT
# name: _prepare_acceptance_context
# purpose: Resolve changed files and propagate the supplied base SHA using the legacy precedence and fallback.
# inputs: worktree_path — target worktree; base_ref — optional base ref; base_sha — optional immutable base SHA.
# returns: Changed file paths, or an empty list when lookup fails.
# side_effects: Reads git changed files and sets GRACE_BASE_SHA when base_sha is supplied.
# emitted_logs: None.
# error_behavior: Swallows changed-file lookup errors and retains empty-list fallback.
# END_FUNCTION_CONTRACT
def _prepare_acceptance_context(
    worktree_path: Path,
    base_ref: str | None,
    base_sha: str | None,
) -> list[str]:
    changed_files: list[str] = []
    try:
        changed_base = base_sha or base_ref or os.environ.get("GRACE_BASE_REF", "HEAD")
        changed_files = get_changed_files(worktree_path, base_ref=changed_base)
    except Exception:
        pass
    if base_sha:
        os.environ["GRACE_BASE_SHA"] = base_sha
    return changed_files


# START_FUNCTION_CONTRACT
# name: _legacy_result_payload
# purpose: Normalize the legacy executor result into the informational fields accepted by AcceptancePipeline.run().
# inputs: legacy_result — legacy result object or dictionary.
# returns: Dictionary containing ok and domain_status values.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Missing object attributes retain the legacy defaults.
# END_FUNCTION_CONTRACT
def _legacy_result_payload(legacy_result: Any) -> dict[str, Any]:
    if isinstance(legacy_result, dict):
        return {
            "ok": legacy_result.get("ok", True),
            "domain_status": legacy_result.get("domain_status", ""),
        }
    return {
        "ok": getattr(legacy_result, "ok", True),
        "domain_status": getattr(legacy_result, "domain_status", ""),
    }

# END_BLOCK_ENTRYPOINT_HELPERS


# START_BLOCK_FREE_FUNCTIONS
# START_FUNCTION_CONTRACT
# name: run_acceptance_pipeline
# purpose: Run full T0/T1/T2 acceptance pipeline and produce AcceptanceReport.
# inputs: packet, legacy_result, project_root, worktree_path, branch_name, run_dir, base_ref, base_sha.
# returns: AcceptanceReport.
# side_effects: Runs external commands via CommandRunner.
# emitted_logs: None directly; command failures are logged by stage owners.
# error_behavior: Never raises for ordinary acceptance failures; returns a non-accepted report.
# END_FUNCTION_CONTRACT
def run_acceptance_pipeline(
    packet: ExecutionPacketContract,
    legacy_result,
    project_root: Path,
    worktree_path: Path,
    branch_name: str,
    run_dir: Path,
    base_ref: str | None = None,
    base_sha: str | None = None,
) -> AcceptanceReport:
    pipeline = _new_pipeline(project_root, worktree_path)
    changed_files = _prepare_acceptance_context(worktree_path, base_ref, base_sha)
    return pipeline.run(
        packet=packet,
        changed_files=changed_files,
        legacy_result=_legacy_result_payload(legacy_result),
        worktree_path=str(worktree_path),
        branch_name=branch_name,
        run_dir=str(run_dir),
    )


# START_FUNCTION_CONTRACT
# name: run_acceptance_stage_replay
# purpose: Run one supported acceptance stage or the full acceptance pipeline as a replay.
# inputs: packet, legacy_result, project_root, worktree_path, branch_name, run_dir, stage, base_ref, base_sha.
# returns: AcceptanceReport for the selected stage.
# side_effects: Runs external commands and writes replay artifacts.
# emitted_logs: None directly; command failures are logged by stage owners.
# error_behavior: Raises ValueError with UNSUPPORTED_REPLAY_STAGE for unknown stage names.
# END_FUNCTION_CONTRACT
def run_acceptance_stage_replay(
    *,
    packet: ExecutionPacketContract,
    legacy_result: Any,
    project_root: Path,
    worktree_path: Path,
    branch_name: str,
    run_dir: Path,
    stage: str,
    base_ref: str | None = None,
    base_sha: str | None = None,
) -> AcceptanceReport:
    pipeline = _new_pipeline(project_root, worktree_path)
    changed_files = _prepare_acceptance_context(worktree_path, base_ref, base_sha)

    if stage == "full_acceptance":
        return run_acceptance_pipeline(
            packet=packet,
            legacy_result=legacy_result,
            project_root=project_root,
            worktree_path=worktree_path,
            branch_name=branch_name,
            run_dir=run_dir,
            base_ref=base_ref,
            base_sha=base_sha,
        )
    if stage == "t0":
        run_dir_t0 = Path(run_dir) / "t0" if run_dir else worktree_path
        t0_result = pipeline._run_t0(
            packet,
            changed_files,
            base_ref,
            base_sha,
            output_dir=run_dir_t0,
            cwd=worktree_path,
        )
        passed = t0_result.stage.status == StageStatus.PASSED
        return AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.ACCEPTED if passed else FinalVerdict.REWORK_REQUIRED,
            profile=packet.acceptance_profile,
            stages=[t0_result.stage],
            scope_violations=[f"{item.path}: {item.reason}" for item in t0_result.scope_violations],
            summary=t0_result.stage.summary,
        )
    if stage == "t1":
        run_dir_t1 = Path(run_dir) / "t1" if run_dir else worktree_path
        t1_result = pipeline._run_t1(
            packet,
            changed_files or [],
            run_dir=run_dir_t1,
            cwd=worktree_path,
        )
        passed = t1_result.status == StageStatus.PASSED
        return AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.ACCEPTED if passed else FinalVerdict.REWORK_REQUIRED,
            profile=packet.acceptance_profile,
            stages=[t1_result],
            summary=t1_result.summary or "T1 completed",
        )
    if stage == "t2":
        run_dir_t2 = Path(run_dir) / "t2" if run_dir else worktree_path
        t2_result = pipeline._run_t2(
            packet,
            changed_files or [],
            run_dir=run_dir_t2,
            cwd=worktree_path,
        )
        passed = t2_result.status == StageStatus.PASSED
        return AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.ACCEPTED if passed else FinalVerdict.REWORK_REQUIRED,
            profile=packet.acceptance_profile,
            stages=[t2_result],
            summary=t2_result.summary or "T2 completed",
        )
    if stage in ("t2_browser", "t3_visual"):
        stages = _run_frontend_stages(
            packet,
            worktree_root=worktree_path,
            run_dir=run_dir,
            run_id=packet.packet_id,
        )
        target_stage = stages.get(stage)
        if not target_stage:
            target_stage = StageResult(
                name=StageName.T2_BROWSER_E2E if stage == "t2_browser" else StageName.T3_VISUAL_REGRESSION,
                status=StageStatus.SKIPPED,
                summary=f"{stage} skipped",
                skipped_reason="not enabled in packet metadata",
            )
        passed = target_stage.status != StageStatus.FAILED
        return AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.ACCEPTED if passed else FinalVerdict.REWORK_REQUIRED,
            profile=packet.acceptance_profile,
            stages=[target_stage],
            summary=target_stage.summary or f"{stage} completed",
        )
    raise ValueError(f"UNSUPPORTED_REPLAY_STAGE: {stage}")

# END_BLOCK_FREE_FUNCTIONS


# START_BLOCK_PIPELINE_CLASS
# START_FUNCTION_CONTRACT
# name: AcceptancePipeline.__init__
# purpose: Initialize the compatibility facade and its coherent acceptance owners.
# inputs: repo_root — project root Path; command_runner — optional CommandRunner; scope_guard — optional ScopeGuard; evidence_collector — optional EvidenceCollector.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
class AcceptancePipeline:

    def __init__(
        self,
        *,
        repo_root: Path,
        command_runner: CommandRunner | None = None,
        scope_guard: ScopeGuard | None = None,
        evidence_collector: EvidenceCollector | None = None,
    ) -> None:
        self._root = repo_root.resolve()
        self._runner = command_runner or CommandRunner(self._root)
        self._scope = scope_guard or ScopeGuard(self._root)
        self._evidence = evidence_collector or EvidenceCollector()
        self._t0_command_template: list[list[str]] = [
            ["python3", "-m", "ruff", "check", "src/"],
        ]
        self._stage_executor = AcceptanceStageExecutor(
            repo_root=self._root,
            command_runner=self._runner,
            scope_guard=self._scope,
            t0_command_template=self._t0_command_template,
        )

    # START_FUNCTION_CONTRACT
    # name: AcceptancePipeline._build_t0_commands
    # purpose: Preserve the private T0 command-resolution seam while delegating to the stage owner.
    # inputs: packet, changed_files, cwd.
    # returns: T0 command values and origins.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Preserves AcceptanceStageExecutor fallback behavior.
    # END_FUNCTION_CONTRACT
    def _build_t0_commands(
        self,
        packet: ExecutionPacketContract,
        changed_files: list[str],
        cwd: Path | None = None,
    ) -> tuple[list[Any], list[str]]:
        return self._stage_executor.build_t0_commands(packet, changed_files, cwd=cwd)

    # START_FUNCTION_CONTRACT
    # name: AcceptancePipeline._resolve_t0_scope_paths
    # purpose: Preserve the private T0 scope-path seam while delegating path preparation.
    # inputs: packet, changed_files, cwd.
    # returns: Existing scope paths relative to cwd.
    # side_effects: Reads path existence from cwd.
    # emitted_logs: None.
    # error_behavior: Preserves AcceptanceStageExecutor path handling.
    # END_FUNCTION_CONTRACT
    def _resolve_t0_scope_paths(
        self,
        packet: ExecutionPacketContract,
        changed_files: list[str],
        cwd: Path | None = None,
    ) -> list[str]:
        return self._stage_executor.resolve_t0_scope_paths(packet, changed_files, cwd=cwd)

    # START_FUNCTION_CONTRACT
    # name: AcceptancePipeline.run
    # purpose: Coordinate T0, T1, T2, frontend stages, evidence checks and final report composition.
    # inputs: packet, changed_files, base_ref, head_ref, legacy_result, worktree_path, branch_name, run_dir.
    # returns: AcceptanceReport with final verdict, ordered stages and diagnostics.
    # side_effects: Runs commands, collects evidence and writes frontend artifacts.
    # emitted_logs: None directly; stage owner logs failed commands.
    # error_behavior: Returns a non-accepted report on any deterministic stage/evidence failure.
    # END_FUNCTION_CONTRACT
    def run(
        self,
        *,
        packet: ExecutionPacketContract,
        changed_files: list[str] | None = None,
        base_ref: str | None = None,
        head_ref: str | None = None,
        legacy_result: dict[str, Any] | None = None,
        worktree_path: str = "",
        branch_name: str = "",
        run_dir: str = "",
    ) -> AcceptanceReport:
        del branch_name
        scope_violations_raw: list[str] = []
        worktree_root = Path(worktree_path) if worktree_path else self._root

        run_dir_t0 = Path(run_dir) / "t0" if run_dir else worktree_root
        t0_result = self._run_t0(
            packet,
            changed_files,
            base_ref,
            head_ref,
            output_dir=run_dir_t0,
            cwd=worktree_root,
        )
        scope_violations_raw = [f"{item.path}: {item.reason}" for item in t0_result.scope_violations]
        if t0_result.stage.status == StageStatus.FAILED:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=FinalVerdict.REWORK_REQUIRED,
                profile=packet.acceptance_profile,
                stages=[t0_result.stage],
                scope_violations=scope_violations_raw,
                summary=t0_result.stage.summary,
            )

        self._evidence.collect_from_stage(t0_result.stage)

        run_dir_t1 = Path(run_dir) / "t1" if run_dir else worktree_root
        t1_result = self._run_t1(
            packet,
            changed_files or [],
            run_dir=run_dir_t1,
            cwd=worktree_root,
        )
        self._evidence.collect_from_stage(t1_result)
        if t1_result.status == StageStatus.FAILED:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=FinalVerdict.REWORK_REQUIRED,
                profile=packet.acceptance_profile,
                stages=[t0_result.stage, t1_result],
                scope_violations=scope_violations_raw,
                summary=t1_result.summary or "T1 failed",
            )

        run_dir_t2 = Path(run_dir) / "t2" if run_dir else worktree_root
        t2_result = self._run_t2(
            packet,
            changed_files or [],
            run_dir=run_dir_t2,
            cwd=worktree_root,
        )
        self._evidence.collect_from_stage(t2_result)
        if t2_result.status == StageStatus.FAILED:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=FinalVerdict.REWORK_REQUIRED,
                profile=packet.acceptance_profile,
                stages=[t0_result.stage, t1_result, t2_result],
                scope_violations=scope_violations_raw,
                summary=t2_result.summary or "T2 failed",
            )

        acceptance_run_dir = Path(run_dir) if run_dir else worktree_root
        run_id = (
            f"{packet.packet_id}-{acceptance_run_dir.name}"
            if acceptance_run_dir.name.startswith("R")
            else packet.packet_id
        )
        frontend_stages = _run_frontend_stages(
            packet,
            worktree_root=worktree_root,
            run_dir=acceptance_run_dir,
            run_id=run_id,
        )
        t2_browser_stage = frontend_stages.get("t2_browser")
        t3_visual_stage = frontend_stages.get("t3_visual")
        if t2_browser_stage:
            if t2_browser_stage.status == StageStatus.FAILED:
                return AcceptanceReport(
                    packet_id=packet.packet_id,
                    final_verdict=FinalVerdict.REWORK_REQUIRED,
                    profile=packet.acceptance_profile,
                    stages=[t0_result.stage, t1_result, t2_result, t2_browser_stage],
                    scope_violations=scope_violations_raw,
                    summary=t2_browser_stage.summary or "T2_BROWSER failed",
                )
            self._evidence.collect_from_stage(t2_browser_stage)
        if t3_visual_stage:
            if t3_visual_stage.status == StageStatus.FAILED:
                stages = [t0_result.stage, t1_result, t2_result]
                if t2_browser_stage:
                    stages.append(t2_browser_stage)
                stages.append(t3_visual_stage)
                return AcceptanceReport(
                    packet_id=packet.packet_id,
                    final_verdict=FinalVerdict.REWORK_REQUIRED,
                    profile=packet.acceptance_profile,
                    stages=stages,
                    scope_violations=scope_violations_raw,
                    summary=t3_visual_stage.summary or "T3_VISUAL failed",
                )
            self._evidence.collect_from_stage(t3_visual_stage)

        final_stages = [t0_result.stage, t1_result, t2_result]
        if t2_browser_stage:
            final_stages.append(t2_browser_stage)
        if t3_visual_stage:
            final_stages.append(t3_visual_stage)

        evidence_issues = check_expected_evidence(
            expected=packet.expected_evidence,
            stage_results=final_stages,
            worktree_path=worktree_root,
            changed_files=changed_files or [],
            profile=packet.acceptance_profile,
            run_dir=acceptance_run_dir,
        )
        if evidence_issues:
            verdict = (
                FinalVerdict.BLOCKED
                if packet.acceptance_profile == AcceptanceProfile.STRICT
                else FinalVerdict.REWORK_REQUIRED
            )
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=verdict,
                profile=packet.acceptance_profile,
                stages=final_stages,
                scope_violations=scope_violations_raw,
                evidence_issues=evidence_issues,
                summary=evidence_issues[0],
            )

        legacy_ok = legacy_result.get("ok", True) if legacy_result else True
        legacy_domain_status = legacy_result.get("domain_status", "") if legacy_result else ""
        return AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.ACCEPTED,
            profile=packet.acceptance_profile,
            stages=final_stages,
            scope_violations=scope_violations_raw,
            legacy_domain_status=legacy_domain_status,
            legacy_ok=legacy_ok,
            summary="all deterministic gates passed",
        )

    # START_FUNCTION_CONTRACT
    # name: AcceptancePipeline._run_t0
    # purpose: Preserve the instrumented T0 seam while delegating implementation to AcceptanceStageExecutor.
    # inputs: packet, changed_files, base_ref, head_ref, output_dir, cwd.
    # returns: _T0Result.
    # side_effects: Runs T0 commands and stage instrumentation.
    # emitted_logs: t0_command_failed.
    # error_behavior: Returns the delegated T0 result.
    # END_FUNCTION_CONTRACT
    @stage("t0_scope_lint")
    def _run_t0(
        self,
        packet: ExecutionPacketContract,
        changed_files: list[str] | None,
        base_ref: str | None,
        head_ref: str | None,
        *,
        output_dir: Path | None = None,
        cwd: Path | None = None,
    ) -> _T0Result:
        return self._stage_executor.run_t0(
            packet,
            changed_files,
            base_ref,
            head_ref,
            output_dir=output_dir,
            cwd=cwd,
        )

    # START_FUNCTION_CONTRACT
    # name: AcceptancePipeline._run_t1
    # purpose: Preserve the instrumented T1 seam while delegating command semantics to AcceptanceStageExecutor.
    # inputs: packet, changed_files, run_dir, cwd.
    # returns: T1 StageResult.
    # side_effects: Runs T1 commands and stage instrumentation.
    # emitted_logs: t1_command_failed.
    # error_behavior: Returns the delegated T1 result.
    # END_FUNCTION_CONTRACT
    @stage("t1_unit_tests")
    def _run_t1(
        self,
        packet: ExecutionPacketContract,
        changed_files: list[str],
        *,
        run_dir: Path | None = None,
        cwd: Path | None = None,
    ) -> StageResult:
        return self._stage_executor.run_t1(packet, changed_files, run_dir=run_dir, cwd=cwd)

    # START_FUNCTION_CONTRACT
    # name: AcceptancePipeline._run_t2
    # purpose: Preserve the instrumented T2 seam while delegating command semantics to AcceptanceStageExecutor.
    # inputs: packet, changed_files, run_dir, cwd.
    # returns: T2 StageResult.
    # side_effects: Runs T2 commands and stage instrumentation.
    # emitted_logs: t2_command_failed.
    # error_behavior: Returns the delegated T2 result.
    # END_FUNCTION_CONTRACT
    @stage("t2_e2e_smoke")
    def _run_t2(
        self,
        packet: ExecutionPacketContract,
        changed_files: list[str],
        *,
        run_dir: Path | None = None,
        cwd: Path | None = None,
    ) -> StageResult:
        return self._stage_executor.run_t2(packet, changed_files, run_dir=run_dir, cwd=cwd)

    # START_FUNCTION_CONTRACT
    # name: AcceptancePipeline._needs_shell
    # purpose: Preserve the private shell-detection seam for packet verification tests and callers.
    # inputs: cmd — shell string or argv list.
    # returns: Whether explicit shell execution is required.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Delegates unchanged shell detection semantics.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _needs_shell(cmd: Any) -> bool:
        return AcceptanceStageExecutor.needs_shell(cmd)

    # START_FUNCTION_CONTRACT
    # name: AcceptancePipeline._has_env_assignment_prefix
    # purpose: Preserve the private environment-prefix detection seam.
    # inputs: cmd_str — command string.
    # returns: Whether the command begins with a valid NAME=value prefix.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Delegates unchanged validation semantics.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _has_env_assignment_prefix(cmd_str: str) -> bool:
        return AcceptanceStageExecutor.has_env_assignment_prefix(cmd_str)

    # START_FUNCTION_CONTRACT
    # name: AcceptancePipeline._verification_command
    # purpose: Preserve shell strings and copy argv lists at the compatibility boundary.
    # inputs: raw_command — packet command.
    # returns: Unchanged string or copied list.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _verification_command(raw_command: Any) -> Any:
        return AcceptanceStageExecutor.verification_command(raw_command)

    # START_FUNCTION_CONTRACT
    # name: AcceptancePipeline._command_text
    # purpose: Preserve command rendering used in diagnostics.
    # inputs: command — shell string or argv list.
    # returns: Human-readable command text.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: None.
    # END_FUNCTION_CONTRACT
    @staticmethod
    def _command_text(command: Any) -> str:
        return AcceptanceStageExecutor.command_text(command)

# END_BLOCK_PIPELINE_CLASS


# START_BLOCK_FRONTEND_COMPATIBILITY
# START_FUNCTION_CONTRACT
# name: _run_frontend_stages
# purpose: Preserve the frontend acceptance helper import path while delegating routing to its owner.
# inputs: packet, worktree_root, run_dir, run_id.
# returns: Frontend StageResult mapping.
# side_effects: Runs frontend helpers and writes frontend artifacts.
# emitted_logs: None.
# error_behavior: Preserves frontend helper skip/failure mapping.
# END_FUNCTION_CONTRACT
def _run_frontend_stages(
    packet: ExecutionPacketContract,
    *,
    worktree_root: Path,
    run_dir: Path,
    run_id: str = "",
) -> dict[str, StageResult]:
    return run_frontend_stages(
        packet,
        worktree_root=worktree_root,
        run_dir=run_dir,
        run_id=run_id,
    )


# START_FUNCTION_CONTRACT
# name: _commands_to_results
# purpose: Preserve the private frontend command-result helper import path.
# inputs: commands, worktree_path, run_dir.
# returns: Placeholder CommandResult list.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _commands_to_results(
    commands: list[Any], *, worktree_path: str, run_dir: str
) -> list[CommandResult]:
    return commands_to_results(commands, worktree_path=worktree_path, run_dir=run_dir)

# END_BLOCK_FRONTEND_COMPATIBILITY
