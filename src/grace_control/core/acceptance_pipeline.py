# ############################################################################
# AI_HEADER: acceptance_pipeline
# ROLE: Deterministic T0/T1/T2 acceptance pipeline — scope guard, command runner, evidence.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run T0 (scope+lint), T1 (targeted commands), T2 (full checks) per profile.
#          Produce AcceptanceReport. Replaces fake verifier/reviewer.
# inputs: packet (ExecutionPacketContract), changed_files, base_ref, head_ref.
# returns: AcceptanceReport.
# side_effects: Runs subprocess commands via CommandRunner.
# emitted_logs: None.
# error_behavior: Returns non-accepted report on any failure. Never raises.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
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
    PacketVerdict,
    ReviewerVerdict,
    ScopeViolation,
    StageName,
    StageResult,
    StageStatus,
    VerifierReport,
    validate_packet_contract,
)
from grace_control.core.evidence import EvidenceCollector
from grace_control.core.scope_guard import ScopeGuard


from dataclasses import dataclass


@dataclass(frozen=True)
class _T0Result:
    stage: StageResult
    scope_violations: list[ScopeViolation]


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
        scope_violations: list[ScopeViolation] = []

        # ── T0: scope + cheap machine gates ──────────────────────────────────
        t0 = self._run_t0(packet, changed_files, base_ref, head_ref)
        if t0.stage.status == StageStatus.FAILED:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=PacketVerdict.REWORK_REQUIRED,
                stages=[t0.stage],
                scope_violations=t0.scope_violations,
                reasons=t0.stage.blocking_issues or ["T0 failed"],
            )

        ep = self._evidence.collect_from_stage(t0.stage)

        # ── T1: targeted verification + VerifierReport ────────────────────────
        t1_result = self._run_t1(packet)
        ep += self._evidence.collect_from_stage(t1_result)

        test_verdict: Literal["passed", "failed", "not_run"] = "passed"
        if t1_result.status == StageStatus.SKIPPED:
            test_verdict = "not_run"
        elif t1_result.status == StageStatus.FAILED:
            test_verdict = "failed"

        verifier_report = VerifierReport(
            packet_id=packet.packet_id,
            verdict=PacketVerdict.ACCEPTED if t1_result.status == StageStatus.PASSED else PacketVerdict.REWORK_REQUIRED,
            requirement_results=[{"command": " ".join(c.command), "exit_code": c.exit_code}
                                for c in t1_result.commands],
            test_verdict=test_verdict,
            commands_run=[" ".join(c.command) for c in t1_result.commands],
            evidence_paths=ep,
            blocking_issues=t1_result.blocking_issues,
        )

        if t1_result.status == StageStatus.FAILED:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=PacketVerdict.REWORK_REQUIRED,
                stages=[t0.stage, t1_result],
                scope_violations=t0.scope_violations,
                evidence_paths=ep,
                reasons=t1_result.blocking_issues or ["T1 failed"],
                verifier_report=verifier_report,
            )

        # ── T2: full checks ──────────────────────────────────────────────────
        t2_result = self._run_t2(packet)
        ep += self._evidence.collect_from_stage(t2_result)
        if t2_result.status == StageStatus.FAILED:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=PacketVerdict.REWORK_REQUIRED,
                stages=[t0.stage, t1_result, t2_result],
                scope_violations=t0.scope_violations,
                evidence_paths=ep,
                reasons=t2_result.blocking_issues or ["T2 failed"],
                verifier_report=verifier_report,
            )

        has_evidence = self._evidence.has_required_evidence(
            expected_evidence=packet.expected_evidence,
            collected_evidence=ep,
            acceptance_profile=packet.acceptance_profile,
        )
        blocked = packet.acceptance_profile in (AcceptanceProfile.NORMAL, AcceptanceProfile.STRICT) and not has_evidence

        if blocked:
            reviewer = ReviewerVerdict(
                packet_id=packet.packet_id,
                packet_verdict=PacketVerdict.BLOCKED,
                follow_up_action="localized_rework",
                route_classification="self_resolvable_rework",
                rework_mode="bounded_fresh",
                reasons=["missing required evidence"],
            )
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=PacketVerdict.BLOCKED,
                stages=[t0.stage, t1_result, t2_result],
                scope_violations=t0.scope_violations,
                evidence_paths=ep,
                reasons=["missing required evidence"],
                verifier_report=verifier_report,
                reviewer_verdict=reviewer,
            )

        # ── All passed but legacy runner failed → can't be ACCEPTED ──────────
        if legacy_result and not legacy_result.get("ok", True):
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=PacketVerdict.REWORK_REQUIRED,
                stages=[t0.stage, t1_result, t2_result],
                scope_violations=t0.scope_violations,
                evidence_paths=ep,
                reasons=["legacy runner execution failed"],
                verifier_report=verifier_report,
            )

        # ── All passed → ACCEPTED ────────────────────────────────────────────
        reviewer = ReviewerVerdict(
            packet_id=packet.packet_id,
            packet_verdict=PacketVerdict.ACCEPTED,
            follow_up_action="none",
            route_classification="accepted",
            rework_mode="none",
        )
        return AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=PacketVerdict.ACCEPTED,
            stages=[t0.stage, t1_result, t2_result],
            scope_violations=t0.scope_violations,
            evidence_paths=ep,
            verifier_report=verifier_report,
            reviewer_verdict=reviewer,
        )

    def _run_t0(
        self, packet: ExecutionPacketContract,
        changed_files: list[str] | None,
        base_ref: str | None, head_ref: str | None,
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

        for cmd in (packet.verification.t0 if packet.verification.t0 else self._t0_commands):
            r = self._runner.run(cmd)
            commands.append(r)
            if not r.passed:
                return _T0Result(
                    stage=StageResult(name=StageName.T0_SCOPE_AND_LINT,
                        status=StageStatus.FAILED, summary="T0 cheap check failed",
                        blocking_issues=[f"{' '.join(cmd)} failed: {r.stderr[:200]}"],
                        commands=commands),
                    scope_violations=violations)

        return _T0Result(
            stage=StageResult(name=StageName.T0_SCOPE_AND_LINT, status=StageStatus.PASSED,
                summary="T0 passed: scope clean, contract valid, cheap checks ok",
                commands=commands),
            scope_violations=violations)

    def _run_t1(self, packet: ExecutionPacketContract) -> StageResult:
        cmds = packet.verification.t1
        commands = [self._runner.run(cmd) for cmd in cmds]

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
                              blocking_issues=[f"command failed: {' '.join(c.command)} ({c.exit_code})" for c in failed])
        return StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.PASSED,
                          summary=f"T1 passed: {len(commands)} commands ok", commands=commands)

    def _run_t2(self, packet: ExecutionPacketContract) -> StageResult:
        cmds = packet.verification.t2
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

        commands = [self._runner.run(cmd) for cmd in cmds]
        failed = [c for c in commands if not c.passed]
        if failed:
            return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.FAILED,
                              summary=f"T2 failed: {len(failed)}/{len(commands)} commands failed",
                              commands=commands,
                              blocking_issues=[f"full check failed: {' '.join(c.command)} ({c.exit_code})" for c in failed])
        return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.PASSED,
                          summary=f"T2 passed: {len(commands)} commands ok", commands=commands)
