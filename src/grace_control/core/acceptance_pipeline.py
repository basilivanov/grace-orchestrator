# ############################################################################
# AI_HEADER: acceptance_pipeline
# ROLE: Deterministic T0/T1/T2 acceptance pipeline — scope guard, command runner, evidence.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run T0 (scope+lint), T1 (targeted commands), T2 (full checks) per profile.
#          Produce AcceptanceReport. Replaces fake verifier/reviewer.
# inputs: packet (ExecutionPacketContract), legacy_result, worktree_path, branch_name, run_dir.
# returns: AcceptanceReport.
# side_effects: Runs subprocess commands via CommandRunner.
# emitted_logs: None.
# error_behavior: Returns non-accepted report on any failure. Never raises.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: run_acceptance_pipeline
#   - class: AcceptancePipeline
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from grace_control.core.command_runner import CommandRunner
from grace_control.core.contracts import (
    AcceptanceProfile,
    AcceptanceReport,
    CommandResult,
    ExecutionPacketContract,
    FinalVerdict,
    PacketVerdict,
    ReviewerVerdict,
    ScopeViolation,
    StageName,
    StageResult,
    StageStatus,
    VerifierReport,
    validate_packet_contract,
)
from grace_control.core.evidence import EvidenceCollector, check_expected_evidence
from grace_control.core.scope_guard import ScopeGuard, get_changed_files


from dataclasses import dataclass


@dataclass(frozen=True)
class _T0Result:
    stage: StageResult
    scope_violations: list[ScopeViolation]


def run_acceptance_pipeline(
    packet: ExecutionPacketContract,
    legacy_result,
    project_root: Path,
    worktree_path: Path,
    branch_name: str,
    run_dir: Path,
) -> AcceptanceReport:
    pipe = AcceptancePipeline(
        repo_root=project_root,
        command_runner=CommandRunner(worktree_path),
        scope_guard=ScopeGuard(worktree_path),
    )
    changed_files: list[str] = []
    try:
        changed_files = get_changed_files(worktree_path, base_ref="main")
    except Exception:
        pass
    return pipe.run(
        packet=packet,
        changed_files=changed_files,
        legacy_result={"ok": getattr(legacy_result, "ok", True), "domain_status": getattr(legacy_result, "domain_status", "")},
        worktree_path=str(worktree_path),
        branch_name=branch_name,
        run_dir=str(run_dir),
    )


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
        self._t0_commands: list[list[str]] = [
            ["python", "-m", "py_compile", "src/grace_control/core/contracts.py"],
        ]

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
        scope_violations_raw: list[str] = []
        worktree_root = Path(worktree_path) if worktree_path else self._root

        # ── T0: scope + cheap machine gates ──────────────────────────────────
        run_dir_t0 = Path(run_dir) / "t0" if run_dir else worktree_root
        t0_result = self._run_t0(packet, changed_files, base_ref, head_ref, output_dir=run_dir_t0)
        scope_violations_raw = [f"{v.path}: {v.reason}" for v in t0_result.scope_violations]
        if t0_result.stage.status == StageStatus.FAILED:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=FinalVerdict.REWORK_REQUIRED,
                profile=packet.acceptance_profile,
                stages=[t0_result.stage],
                scope_violations=scope_violations_raw,
                summary=t0_result.stage.summary,
            )

        ep = self._evidence.collect_from_stage(t0_result.stage)

        # ── T1: targeted verification + VerifierReport ────────────────────────
        run_dir_t1 = Path(run_dir) / "t1" if run_dir else worktree_root
        t1_result = self._run_t1(packet, run_dir=run_dir_t1)
        ep += self._evidence.collect_from_stage(t1_result)

        if t1_result.status == StageStatus.FAILED:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=FinalVerdict.REWORK_REQUIRED,
                profile=packet.acceptance_profile,
                stages=[t0_result.stage, t1_result],
                scope_violations=scope_violations_raw,
                summary=t1_result.summary or "T1 failed",
            )

        # ── T2: full checks ──────────────────────────────────────────────────
        run_dir_t2 = Path(run_dir) / "t2" if run_dir else worktree_root
        t2_result = self._run_t2(packet, run_dir=run_dir_t2)
        ep += self._evidence.collect_from_stage(t2_result)
        if t2_result.status == StageStatus.FAILED:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=FinalVerdict.REWORK_REQUIRED,
                profile=packet.acceptance_profile,
                stages=[t0_result.stage, t1_result, t2_result],
                scope_violations=scope_violations_raw,
                summary=t2_result.summary or "T2 failed",
            )

        evidence_issues = check_expected_evidence(
            expected=packet.expected_evidence,
            stage_results=[t0_result.stage, t1_result, t2_result],
            worktree_path=worktree_root,
            changed_files=changed_files or [],
            profile=packet.acceptance_profile,
        )
        if evidence_issues:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=FinalVerdict.BLOCKED if packet.acceptance_profile == AcceptanceProfile.STRICT else FinalVerdict.REWORK_REQUIRED,
                profile=packet.acceptance_profile,
                stages=[t0_result.stage, t1_result, t2_result],
                scope_violations=scope_violations_raw,
                evidence_issues=evidence_issues,
                summary=evidence_issues[0] if evidence_issues else "missing required evidence",
            )

        # ── All passed but legacy runner failed → can't be ACCEPTED ──────────
        legacy_ok = legacy_result.get("ok", True) if legacy_result else True
        legacy_domain_status = legacy_result.get("domain_status", "") if legacy_result else ""
        if not legacy_ok:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=FinalVerdict.REWORK_REQUIRED,
                profile=packet.acceptance_profile,
                stages=[t0_result.stage, t1_result, t2_result],
                scope_violations=scope_violations_raw,
                legacy_domain_status=legacy_domain_status,
                legacy_ok=legacy_ok,
                summary="legacy runner execution failed",
            )

        if legacy_domain_status and legacy_domain_status != "accepted":
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=FinalVerdict.REWORK_REQUIRED,
                profile=packet.acceptance_profile,
                stages=[t0_result.stage, t1_result, t2_result],
                scope_violations=scope_violations_raw,
                legacy_domain_status=legacy_domain_status,
                legacy_ok=legacy_ok,
                summary=f"legacy domain_status is '{legacy_domain_status}', not 'accepted'",
            )

        # ── All passed → ACCEPTED ────────────────────────────────────────────
        return AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.ACCEPTED,
            profile=packet.acceptance_profile,
            stages=[t0_result.stage, t1_result, t2_result],
            scope_violations=scope_violations_raw,
            legacy_domain_status=legacy_domain_status,
            legacy_ok=legacy_ok,
            summary="all deterministic gates passed",
        )

    def _run_t0(
        self, packet: ExecutionPacketContract,
        changed_files: list[str] | None,
        base_ref: str | None, head_ref: str | None,
        *, output_dir: Path | None = None,
    ) -> _T0Result:
        cf = changed_files or self._scope.get_changed_files(base_ref, head_ref)
        violations = self._scope.validate_changed_files(
            changed_files=cf,
            allowed_write_scope=packet.allowed_write_scope,
            frozen_scope=packet.frozen_scope,
        )
        errs = validate_packet_contract(packet)
        commands: list[CommandResult] = []

        if errs:
            return _T0Result(
                stage=StageResult(name=StageName.T0_SCOPE_AND_LINT,
                    status=StageStatus.FAILED, summary="invalid packet contract",
                    blocking_issues=errs, commands=commands),
                scope_violations=violations)

        if violations:
            return _T0Result(
                stage=StageResult(name=StageName.T0_SCOPE_AND_LINT,
                    status=StageStatus.FAILED, summary="scope guard failed",
                    blocking_issues=[f"scope violations: {v.path}" for v in violations],
                    commands=commands),
                scope_violations=violations)

        if "t0" in packet.verification:
            t0_cmds = packet.verification.get("t0", []) or []
        else:
            t0_cmds = self._t0_commands

        for cmd in t0_cmds:
            r = self._runner.run(cmd, output_dir=output_dir)
            commands.append(r)
            if not r.passed:
                return _T0Result(
                    stage=StageResult(name=StageName.T0_SCOPE_AND_LINT,
                        status=StageStatus.FAILED, summary="T0 cheap check failed",
                        blocking_issues=[f"{' '.join(cmd)} failed: {r.stderr[:200]}"],
                        commands=commands),
                    scope_violations=violations)

        summary = "T0 passed: scope clean, contract valid"
        if t0_cmds:
            summary += ", cheap checks ok"
        else:
            summary += ", no cheap commands configured"

        return _T0Result(
            stage=StageResult(name=StageName.T0_SCOPE_AND_LINT, status=StageStatus.PASSED,
                summary=summary,
                commands=commands),
            scope_violations=violations)

    def _run_t1(self, packet: ExecutionPacketContract, *, run_dir: Path | None = None) -> StageResult:
        cmds = packet.verification.get("t1", [])
        commands = [self._runner.run(cmd, output_dir=run_dir) for cmd in cmds]

        if not cmds:
            if packet.acceptance_profile == AcceptanceProfile.FAST:
                return StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.SKIPPED,
                                  summary="FAST profile without T1 commands",
                                  skipped_reason="FAST profile without T1 commands")
            return StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.FAILED,
                              summary="NORMAL/STRICT requires verification.t1",
                              blocking_issues=["missing verification.t1 for NORMAL/STRICT"])

        failed = [c for c in commands if not c.passed]
        if failed:
            return StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.FAILED,
                              summary=f"T1 failed: {len(failed)}/{len(commands)} commands failed",
                              commands=commands,
                              blocking_issues=[f"command failed: {c.command} ({c.exit_code})" for c in failed])
        return StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.PASSED,
                          summary=f"T1 passed: {len(commands)} commands ok", commands=commands)

    def _run_t2(self, packet: ExecutionPacketContract, *, run_dir: Path | None = None) -> StageResult:
        cmds = packet.verification.get("t2", [])
        if not cmds:
            if packet.acceptance_profile == AcceptanceProfile.STRICT:
                return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.FAILED,
                                  summary="STRICT requires verification.t2",
                                  blocking_issues=["missing verification.t2 for STRICT"])
            if packet.acceptance_profile == AcceptanceProfile.NORMAL:
                return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.SKIPPED,
                                  summary="NORMAL without T2 commands",
                                  skipped_reason="no verification.t2 configured")
            return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.SKIPPED,
                              summary="FAST always skips T2", skipped_reason="FAST profile skips T2")

        commands = [self._runner.run(cmd, output_dir=run_dir) for cmd in cmds]
        failed = [c for c in commands if not c.passed]
        if failed:
            return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.FAILED,
                              summary=f"T2 failed: {len(failed)}/{len(commands)} commands failed",
                              commands=commands,
                              blocking_issues=[f"full check failed: {c.command} ({c.exit_code})" for c in failed])
        return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.PASSED,
                          summary=f"T2 passed: {len(commands)} commands ok", commands=commands)
