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

    def run(
        self,
        *,
        packet: ExecutionPacketContract,
        changed_files: list[str] | None = None,
        base_ref: str | None = None,
        head_ref: str | None = None,
    ) -> AcceptanceReport:
        stages: list[StageResult] = []
        scope_violations: list[ScopeViolation] = []
        evidence_paths: list[str] = []
        all_blocking: list[str] = []

        # ── T0: scope + cheap machine gates ──────────────────────────────────
        t0_result = self._run_t0(packet, changed_files, base_ref, head_ref)
        stages.append(t0_result)
        scope_violations = t0_result.get("scope_violations", [])
        all_blocking = t0_result.get("blocking_issues", [])
        if t0_result["status"] == StageStatus.FAILED:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=PacketVerdict.REWORK_REQUIRED,
                stages=self._build_stages(t0_result),
                scope_violations=scope_violations,
            )

        ep = self._evidence.collect_from_stage(t0_result["stage"]) if "stage" in t0_result else []

        # ── T1: targeted verification ────────────────────────────────────────
        t1_result = self._run_t1(packet)
        stages.append(t1_result)
        ep += self._evidence.collect_from_stage(t1_result)
        if t1_result.status == StageStatus.FAILED:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=PacketVerdict.REWORK_REQUIRED,
                stages=self._build_stages(t0_result, t1_result),
                scope_violations=scope_violations,
                evidence_paths=ep,
            )
        if t1_result.blocking_issues:
            all_blocking.extend(t1_result.blocking_issues)

        # ── T2: full checks ──────────────────────────────────────────────────
        t2_result = self._run_t2(packet)
        stages.append(t2_result)
        ep += self._evidence.collect_from_stage(t2_result)
        if t2_result.status == StageStatus.FAILED:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=PacketVerdict.REWORK_REQUIRED,
                stages=self._build_stages(t0_result, t1_result, t2_result),
                scope_violations=scope_violations,
                evidence_paths=ep,
            )

        # ── Build final verdict ─────────────────────────────────────────────
        has_evidence = self._evidence.has_required_evidence(
            expected_evidence=packet.expected_evidence,
            collected_evidence=ep,
            acceptance_profile=packet.acceptance_profile,
        )
        if packet.acceptance_profile in (AcceptanceProfile.NORMAL, AcceptanceProfile.STRICT) and not has_evidence:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=PacketVerdict.BLOCKED,
                stages=self._build_stages(t0_result, t1_result, t2_result),
                scope_violations=scope_violations,
                evidence_paths=ep,
                reasons=["missing required evidence"],
            )

        return AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=PacketVerdict.ACCEPTED,
            stages=self._build_stages(t0_result, t1_result, t2_result),
            scope_violations=scope_violations,
            evidence_paths=ep,
        )

    def _run_t0(
        self, packet: ExecutionPacketContract,
        changed_files: list[str] | None,
        base_ref: str | None, head_ref: str | None,
    ) -> dict:
        cf = changed_files or self._scope.get_changed_files(base_ref, head_ref)
        violations = self._scope.validate_changed_files(
            changed_files=cf,
            allowed_write_scope=packet.allowed_write_scope,
            frozen_scope=packet.frozen_scope,
        )
        errs = validate_packet_contract(packet)
        commands: list[CommandResult] = []

        if errs:
            return {"status": StageStatus.FAILED, "summary": "invalid packet contract",
                    "blocking_issues": errs, "scope_violations": violations, "commands": commands}

        if violations:
            return {"status": StageStatus.FAILED, "summary": "scope guard failed",
                    "blocking_issues": [f"scope violations: {v.path}" for v in violations],
                    "scope_violations": violations, "commands": commands}

        # Cheap syntax check
        py_check = self._runner.run(["python", "-m", "py_compile", "src/grace_control/core/contracts.py"])
        commands.append(py_check)
        if not py_check.passed:
            return {"status": StageStatus.FAILED, "summary": "T0 cheap check failed",
                    "blocking_issues": [f"py_compile failed: {py_check.stderr[:200]}"],
                    "scope_violations": violations, "commands": commands}

        stage = StageResult(name=StageName.T0_SCOPE_AND_LINT, status=StageStatus.PASSED,
                           summary="T0 passed: scope clean, contract valid, cheap checks ok",
                           commands=commands)
        return {"status": StageStatus.PASSED, "stage": stage,
                "summary": stage.summary, "commands": commands,
                "scope_violations": violations, "blocking_issues": []}

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

    def _build_stages(self, *results: dict | StageResult) -> list[StageResult]:
        stages: list[StageResult] = []
        for r in results:
            if isinstance(r, dict):
                st = r.get("stage")
                if st is not None:
                    stages.append(st)
                else:
                    status = r.get("status", StageStatus.SKIPPED)
                    name = StageName.T0_SCOPE_AND_LINT
                    stages.append(StageResult(
                        name=name, status=status,
                        summary=r.get("summary", ""),
                        blocking_issues=r.get("blocking_issues", []),
                        commands=r.get("commands", []),
                    ))
            elif isinstance(r, StageResult):
                stages.append(r)
        return stages
