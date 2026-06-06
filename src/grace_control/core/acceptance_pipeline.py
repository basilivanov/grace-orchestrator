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

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("acceptance")

import os
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
    base_ref: str | None = None,
    base_sha: str | None = None,
) -> AcceptanceReport:
    pipe = AcceptancePipeline(
        repo_root=project_root,
        command_runner=CommandRunner(worktree_path),
        scope_guard=ScopeGuard(worktree_path),
    )
    changed_files: list[str] = []
    try:
        changed_base = base_sha or base_ref or os.environ.get("GRACE_BASE_REF", "HEAD")
        changed_files = get_changed_files(worktree_path, base_ref=changed_base)
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
        self._t0_command_template: list[list[str]] = [
            ["python3", "-m", "ruff", "check", "src/"],
        ]

    def _build_t0_commands(
        self,
        packet: ExecutionPacketContract,
        changed_files: list[str],
        cwd: Path | None = None,
    ) -> list[list[str]]:
        scope_paths = self._resolve_t0_scope_paths(packet, changed_files, cwd=cwd)
        if not scope_paths:
            return self._t0_command_template
        commands: list[list[str]] = []
        # scripts/grace_lint.py is repo-supplied and optional — only run it
        # if the file is committed in the worktree.
        base = (cwd or self._root).resolve()
        if (base / "scripts" / "grace_lint.py").is_file():
            commands.append(["python3", "scripts/grace_lint.py"] + scope_paths)
        commands.append(["python3", "-m", "ruff", "check"] + scope_paths)
        return commands

    def _resolve_t0_scope_paths(
        self,
        packet: ExecutionPacketContract,
        changed_files: list[str],
        cwd: Path | None = None,
    ) -> list[str]:
        # P1#6: scope paths are resolved against the actual command cwd
        # (the worktree), not the project root. A new file that exists only
        # in the agent worktree would otherwise be skipped by the
        # scope-aware lint selection because `project_root / p` wouldn't
        # exist on disk.
        base = (cwd or self._root).resolve()
        candidates: list[str] = []
        seen: set[str] = set()

        for raw in (packet.allowed_write_scope or []):
            if not raw:
                continue
            if raw in seen:
                continue
            seen.add(raw)
            candidates.append(raw)

        if changed_files:
            for f in changed_files:
                if f in seen:
                    continue
                seen.add(f)
                candidates.append(f)

        existing: list[str] = []
        for p in candidates:
            abs_path = (base / p).resolve() if not Path(p).is_absolute() else Path(p)
            try:
                rel = abs_path.relative_to(base)
            except ValueError:
                rel = abs_path
            if abs_path.exists():
                existing.append(str(rel))

        return existing

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
        t0_result = self._run_t0(packet, changed_files, base_ref, head_ref, output_dir=run_dir_t0, cwd=worktree_root)
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
        t1_result = self._run_t1(packet, run_dir=run_dir_t1, cwd=worktree_root)
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
        t2_result = self._run_t2(packet, run_dir=run_dir_t2, cwd=worktree_root)
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

        # ── Legacy result is informational when T0/T1/T2 pass ─────────────────
        # T0 already validates scope independently. Do not let legacy scope_blocked
        # override a clean deterministic acceptance pipeline result.
        legacy_ok = legacy_result.get("ok", True) if legacy_result else True
        legacy_domain_status = legacy_result.get("domain_status", "") if legacy_result else ""

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
        *, output_dir: Path | None = None, cwd: Path | None = None,
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
            if packet.acceptance_profile == AcceptanceProfile.STRICT:
                return _T0Result(
                    stage=StageResult(name=StageName.T0_SCOPE_AND_LINT,
                        status=StageStatus.FAILED, summary="scope guard failed",
                        blocking_issues=[f"scope violations: {v.path}" for v in violations],
                        commands=commands),
                    scope_violations=violations)
            # FAST/NORMAL: scope violations are warnings, not blockers

        if not cf:
            return _T0Result(
                stage=StageResult(name=StageName.T0_SCOPE_AND_LINT,
                    status=StageStatus.PASSED, summary="no changes to lint (empty diff)",
                    blocking_issues=[], commands=[]),
                scope_violations=violations)

        t0_cmds = self._build_t0_commands(packet, cf, cwd=cwd or self._root)

        for cmd in t0_cmds:
            r = self._runner.run(cmd, output_dir=output_dir, cwd=cwd)
            commands.append(r)
            if not r.passed:
                _log.info("t0_command_failed",
                    command=" ".join(cmd)[:200],
                    exit_code=r.exit_code,
                    stderr=r.stderr[:500],
                    stdout=r.stdout[:500],
                )
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

    def _run_t1(self, packet: ExecutionPacketContract, *, run_dir: Path | None = None, cwd: Path | None = None) -> StageResult:
        cmds = packet.verification.get("t1", [])
        commands = [self._runner.run(cmd, output_dir=run_dir, cwd=cwd) for cmd in cmds]

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
            for c in failed:
                _log.info("t1_command_failed",
                    command=c.command[:200],
                    exit_code=c.exit_code,
                    stderr=c.stderr[:500],
                    stdout=c.stdout[:500],
                )
            return StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.FAILED,
                              summary=f"T1 failed: {len(failed)}/{len(commands)} commands failed",
                              commands=commands,
                              blocking_issues=[f"command failed: {c.command} (exit={c.exit_code}) stderr={c.stderr[:200]} stdout={c.stdout[:200]}" for c in failed])
        return StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.PASSED,
                          summary=f"T1 passed: {len(commands)} commands ok", commands=commands)

    def _run_t2(self, packet: ExecutionPacketContract, *, run_dir: Path | None = None, cwd: Path | None = None) -> StageResult:
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

        commands = [self._runner.run(cmd, output_dir=run_dir, cwd=cwd) for cmd in cmds]
        failed = [c for c in commands if not c.passed]
        if failed:
            for c in failed:
                _log.info("t2_command_failed",
                    command=c.command[:200],
                    exit_code=c.exit_code,
                    stderr=c.stderr[:500],
                    stdout=c.stdout[:500],
                )
            return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.FAILED,
                              summary=f"T2 failed: {len(failed)}/{len(commands)} commands failed",
                              commands=commands,
                              blocking_issues=[f"full check failed: {c.command} (exit={c.exit_code}) stderr={c.stderr[:200]} stdout={c.stdout[:200]}" for c in failed])
        return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.PASSED,
                          summary=f"T2 passed: {len(commands)} commands ok", commands=commands)
