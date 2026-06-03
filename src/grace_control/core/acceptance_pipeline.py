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
    ScopeViolation,
    StageName,
    StageResult,
    StageStatus,
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

        # ── T1: targeted verification ────────────────────────────────────────
        t1_result = self._run_t1(packet)
        ep += self._evidence.collect_from_stage(t1_result)
        if t1_result.status == StageStatus.FAILED:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=PacketVerdict.REWORK_REQUIRED,
                stages=[t0.stage, t1_result],
                scope_violations=t0.scope_violations,
                evidence_paths=ep,
                reasons=t1_result.blocking_issues or ["T1 failed"],
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
            )

        has_evidence = self._evidence.has_required_evidence(
            expected_evidence=packet.expected_evidence,
            collected_evidence=ep,
            acceptance_profile=packet.acceptance_profile,
        )
        if packet.acceptance_profile in (AcceptanceProfile.NORMAL, AcceptanceProfile.STRICT) and not has_evidence:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=PacketVerdict.BLOCKED,
                stages=[t0.stage, t1_result, t2_result],
                scope_violations=t0.scope_violations,
                evidence_paths=ep,
                reasons=["missing required evidence"],
            )

        return AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=PacketVerdict.ACCEPTED,
            stages=[t0.stage, t1_result, t2_result],
            scope_violations=t0.scope_violations,
            evidence_paths=ep,
        )

        ep = self._evidence.collect_from_stage(t0_result["stage"]) if "stage" in t0_result else []

        # ── T1: targeted verification ────────────────────────────────────────
        t1_result = self._run_t1(packet)
        ep += self._evidence.collect_from_stage(t1_result)
        if t1_result.status == StageStatus.FAILED:
            t0_stage = t0_result.get("stage")
            stages = [t0_stage] if t0_stage else []
            stages.append(t1_result)
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=PacketVerdict.REWORK_REQUIRED,
                stages=stages,
                scope_violations=scope_violations,
                evidence_paths=ep,
                reasons=t1_result.blocking_issues or ["T1 failed"],
            )

        # ── T2: full checks ──────────────────────────────────────────────────
        t2_result = self._run_t2(packet)
        ep += self._evidence.collect_from_stage(t2_result)
        if t2_result.status == StageStatus.FAILED:
            t0_stage = t0_result.get("stage")
            stages = [t0_stage] if t0_stage else []
            stages.extend([t1_result, t2_result])
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=PacketVerdict.REWORK_REQUIRED,
                stages=stages,
                scope_violations=scope_violations,
                evidence_paths=ep,
                reasons=t2_result.blocking_issues or ["T2 failed"],
            )

        # ── Build final verdict ─────────────────────────────────────────────
        has_evidence = self._evidence.has_required_evidence(
            expected_evidence=packet.expected_evidence,
            collected_evidence=ep,
            acceptance_profile=packet.acceptance_profile,
        )
        if packet.acceptance_profile in (AcceptanceProfile.NORMAL, AcceptanceProfile.STRICT) and not has_evidence:
            t0_stage = t0_result.get("stage")
            stages = [t0_stage] if t0_stage else []
            stages.extend([t1_result, t2_result])
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=PacketVerdict.BLOCKED,
                stages=stages,
                scope_violations=scope_violations,
                evidence_paths=ep,
                reasons=["missing required evidence"],
            )

        t0_stage = t0_result.get("stage")
        final_stages = [t0_stage] if t0_stage else []
        final_stages.extend([t1_result, t2_result])
        return AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=PacketVerdict.ACCEPTED,
            stages=final_stages,
            scope_violations=scope_violations,
            evidence_paths=ep,
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

        for cmd in self._t0_commands:
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
        commands = [self._runner.run(cmd) for cmd in packet.verification_commands]

        if not packet.verification_commands:
            if packet.acceptance_profile == AcceptanceProfile.FAST:
                return StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.SKIPPED,
                                  summary="FAST profile without targeted commands",
                                  skipped_reason="FAST profile without targeted commands")
            return StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.FAILED,
                              summary="NORMAL/STRICT requires verification commands",
                              blocking_issues=["missing verification_commands for NORMAL/STRICT"])

        failed = [c for c in commands if not c.passed]
        if failed:
            return StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.FAILED,
                              summary=f"T1 failed: {len(failed)}/{len(commands)} commands failed",
                              commands=commands,
                              blocking_issues=[f"command failed: {' '.join(c.command)} ({c.exit_code})" for c in failed])
        return StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.PASSED,
                          summary=f"T1 passed: {len(commands)} commands ok", commands=commands)

    def _run_t2(self, packet: ExecutionPacketContract) -> StageResult:
        full_cmds = packet.metadata.get("full_verification_commands", []) if packet.metadata else []
        if not full_cmds:
            if packet.acceptance_profile == AcceptanceProfile.STRICT:
                return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.FAILED,
                                  summary="STRICT requires full verification commands",
                                  blocking_issues=["missing full_verification_commands for STRICT"])
            if packet.acceptance_profile == AcceptanceProfile.NORMAL:
                return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.SKIPPED,
                                  summary="NORMAL without full verification commands",
                                  skipped_reason="no full_verification_commands configured")
            return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.SKIPPED,
                              summary="FAST always skips T2", skipped_reason="FAST profile skips T2")

        commands = [self._runner.run(cmd) for cmd in full_cmds]
        failed = [c for c in commands if not c.passed]
        if failed:
            return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.FAILED,
                              summary=f"T2 failed: {len(failed)}/{len(commands)} commands failed",
                              commands=commands,
                              blocking_issues=[f"full check failed: {' '.join(c.command)} ({c.exit_code})" for c in failed])
        return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.PASSED,
                          summary=f"T2 passed: {len(commands)} commands ok", commands=commands)
