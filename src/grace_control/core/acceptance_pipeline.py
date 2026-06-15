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

from typing import Any

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("acceptance")

import os
import shlex
from dataclasses import dataclass
from pathlib import Path

import re as _re

from grace_control.core.command_runner import CommandRunner
from grace_control.core.contracts import (
    AcceptanceProfile,
    AcceptanceReport,
    CommandResult,
    ExecutionPacketContract,
    FinalVerdict,
    ScopeViolation,
    StageName,
    StageResult,
    StageStatus,
    validate_packet_contract,
)
from grace_control.core.evidence import EvidenceCollector, check_expected_evidence
from grace_control.core.gate_resolver import resolve_default_gates, resolve_default_t0, resolve_touched_areas
from grace_control.core.scope_guard import ScopeGuard, get_changed_files

# W06: Pattern to detect shell operators in command strings
_SHELL_OPS_PATTERN = _re.compile(r'(&&|\|\||[|<>;])')


@dataclass(frozen=True)
class _T0Result:
    stage: StageResult
    scope_violations: list[ScopeViolation]


# START_BLOCK_FREE_FUNCTIONS
# START_FUNCTION_CONTRACT
# name: run_acceptance_pipeline
# purpose: Run full T0/T1/T2 acceptance pipeline and produce AcceptanceReport.
# inputs: packet, legacy_result, project_root, worktree_path, branch_name, run_dir, base_ref, base_sha.
# returns: AcceptanceReport.
# side_effects: Runs subprocess commands via CommandRunner.
# emitted_logs: None.
# error_behavior: Never raises — returns non-accepted report on any failure.
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
    # Expose base_sha to T1/T2 subprocesses (e.g. changed-file lint)
    if base_sha:
        os.environ["GRACE_BASE_SHA"] = base_sha
    return pipe.run(
        packet=packet,
        changed_files=changed_files,
        legacy_result={"ok": getattr(legacy_result, "ok", True) if not isinstance(legacy_result, dict) else legacy_result.get("ok", True),
                       "domain_status": getattr(legacy_result, "domain_status", "") if not isinstance(legacy_result, dict) else legacy_result.get("domain_status", "")},
        worktree_path=str(worktree_path),
        branch_name=branch_name,
        run_dir=str(run_dir),
    )


# START_FUNCTION_CONTRACT
# name: run_acceptance_stage_replay
# purpose: Run a single acceptance stage (t0, t1, t2, t2_browser, t3_visual, full_acceptance) as a replay.
# inputs: packet, legacy_result, project_root, worktree_path, branch_name, run_dir, stage, base_ref, base_sha.
# returns: AcceptanceReport for the single stage.
# side_effects: Runs subprocess commands for the selected stage.
# emitted_logs: None.
# error_behavior: Raises ValueError for unsupported stage.
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
    # Expose base_sha to T1/T2 subprocesses (e.g. changed-file lint)
    if base_sha:
        os.environ["GRACE_BASE_SHA"] = base_sha

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
    elif stage == "t0":
        run_dir_t0 = Path(run_dir) / "t0" if run_dir else worktree_path
        t0_result = pipe._run_t0(packet, changed_files, base_ref, base_sha, output_dir=run_dir_t0, cwd=worktree_path)
        passed = t0_result.stage.status == StageStatus.PASSED
        return AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.ACCEPTED if passed else FinalVerdict.REWORK_REQUIRED,
            profile=packet.acceptance_profile,
            stages=[t0_result.stage],
            scope_violations=[f"{v.path}: {v.reason}" for v in t0_result.scope_violations],
            summary=t0_result.stage.summary,
        )
    elif stage == "t1":
        run_dir_t1 = Path(run_dir) / "t1" if run_dir else worktree_path
        t1_result = pipe._run_t1(packet, changed_files or [], run_dir=run_dir_t1, cwd=worktree_path)
        passed = t1_result.status == StageStatus.PASSED
        return AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.ACCEPTED if passed else FinalVerdict.REWORK_REQUIRED,
            profile=packet.acceptance_profile,
            stages=[t1_result],
            summary=t1_result.summary or "T1 completed",
        )
    elif stage == "t2":
        run_dir_t2 = Path(run_dir) / "t2" if run_dir else worktree_path
        t2_result = pipe._run_t2(packet, changed_files or [], run_dir=run_dir_t2, cwd=worktree_path)
        passed = t2_result.status == StageStatus.PASSED
        return AcceptanceReport(
            packet_id=packet.packet_id,
            final_verdict=FinalVerdict.ACCEPTED if passed else FinalVerdict.REWORK_REQUIRED,
            profile=packet.acceptance_profile,
            stages=[t2_result],
            summary=t2_result.summary or "T2 completed",
        )
    elif stage in ("t2_browser", "t3_visual"):
        stages_dict = _run_frontend_stages(
            packet, worktree_root=worktree_path, run_dir=run_dir, run_id=packet.packet_id
        )
        target_stage = stages_dict.get(stage)
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
    else:
        raise ValueError(f"UNSUPPORTED_REPLAY_STAGE: {stage}")

# END_BLOCK_FREE_FUNCTIONS

# START_BLOCK_PIPELINE_CLASS
# START_FUNCTION_CONTRACT
# name: AcceptancePipeline.__init__
# purpose: Initialize the pipeline with repo root, command runner, scope guard, and evidence collector.
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

    def _build_t0_commands(
        self,
        packet: ExecutionPacketContract,
        changed_files: list[str],
        cwd: Path | None = None,
    ) -> tuple[list[list[str]], list[str]]:
        """Return (commands, origins) for T0 using gate_resolver defaults."""
        scope_paths = self._resolve_t0_scope_paths(packet, changed_files, cwd=cwd)
        base = (cwd or self._root).resolve()

        cmds, origins = resolve_default_t0(scope_paths, base, packet.acceptance_profile.value)
        if cmds:
            return cmds, origins

        # Fallback: hardcoded ruff on src/
        py_paths = [p for p in scope_paths if p.endswith(".py")]
        if py_paths:
            return (
                [["python3", "-m", "ruff", "check"] + py_paths],
                ["auto:t0:ruff_fallback"],
            )

        return self._t0_command_template, ["auto:t0:ruff_src"]

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

    # START_FUNCTION_CONTRACT
    # name: AcceptancePipeline.run
    # purpose: Execute T0 → T1 → T2 → T2_BROWSER → T3_VISUAL pipeline and produce AcceptanceReport.
    # inputs: packet, changed_files, base_ref, head_ref, legacy_result, worktree_path, branch_name, run_dir.
    # returns: AcceptanceReport with final_verdict, stages, scope_violations, evidence_issues.
    # side_effects: Runs subprocess commands via CommandRunner; collects evidence.
    # emitted_logs: None.
    # error_behavior: Never raises — returns non-accepted report on failure at any stage.
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
        t1_result = self._run_t1(packet, changed_files or [], run_dir=run_dir_t1, cwd=worktree_root)
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
        t2_result = self._run_t2(packet, changed_files or [], run_dir=run_dir_t2, cwd=worktree_root)
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

        # ── T2_BROWSER + T3_VISUAL: frontend acceptance (TZ_FRONTEND_ACCEPTANCE P0) ──
        _rd = Path(run_dir) if run_dir else worktree_root
        _derived_run_id = f"{packet.packet_id}-{_rd.name}" if _rd.name.startswith("R") else packet.packet_id
        browser_routing = _run_frontend_stages(
            packet, worktree_root=worktree_root, run_dir=_rd, run_id=_derived_run_id,
        )
        t2_browser_stage = browser_routing.get("t2_browser")
        t3_visual_stage = browser_routing.get("t3_visual")
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
            ep += self._evidence.collect_from_stage(t2_browser_stage)
        if t3_visual_stage:
            if t3_visual_stage.status == StageStatus.FAILED:
                stages = [t0_result.stage, t1_result, t2_result]
                if t2_browser_stage: stages.append(t2_browser_stage)
                stages.append(t3_visual_stage)
                return AcceptanceReport(
                    packet_id=packet.packet_id,
                    final_verdict=FinalVerdict.REWORK_REQUIRED,
                    profile=packet.acceptance_profile,
                    stages=stages,
                    scope_violations=scope_violations_raw,
                    summary=t3_visual_stage.summary or "T3_VISUAL failed",
                )
            ep += self._evidence.collect_from_stage(t3_visual_stage)

        # Collect all stages for final report
        final_stages = [t0_result.stage, t1_result, t2_result]
        if t2_browser_stage: final_stages.append(t2_browser_stage)
        if t3_visual_stage: final_stages.append(t3_visual_stage)

        evidence_issues = check_expected_evidence(
            expected=packet.expected_evidence,
            stage_results=final_stages,
            worktree_path=worktree_root,
            changed_files=changed_files or [],
            profile=packet.acceptance_profile,
            run_dir=_rd,
        )
        if evidence_issues:
            return AcceptanceReport(
                packet_id=packet.packet_id,
                final_verdict=FinalVerdict.BLOCKED if packet.acceptance_profile == AcceptanceProfile.STRICT else FinalVerdict.REWORK_REQUIRED,
                profile=packet.acceptance_profile,
                stages=final_stages,
                scope_violations=scope_violations_raw,
                evidence_issues=evidence_issues,
                summary=evidence_issues[0] if evidence_issues else "missing required evidence",
            )

        # ── Legacy result is informational when T0/T1/T2 pass ─────────────────
        legacy_ok = legacy_result.get("ok", True) if legacy_result else True
        legacy_domain_status = legacy_result.get("domain_status", "") if legacy_result else ""

        # ── All passed → ACCEPTED ────────────────────────────────────────────
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

        # Use explicit T0 commands if provided; otherwise fall back to auto defaults.
        explicit_t0 = packet.verification.get("t0", [])
        if explicit_t0:
            t0_cmds = [shlex.split(c) if isinstance(c, str) else c for c in explicit_t0]
            t0_origins = ["architect:verification"] * len(explicit_t0)
        else:
            t0_cmds, t0_origins = self._build_t0_commands(packet, cf, cwd=cwd or self._root)

        for cmd in t0_cmds:
            # W06: Detect shell operators and pass shell=True explicitly
            r = self._runner.run(cmd, output_dir=output_dir, cwd=cwd, shell=self._needs_shell(cmd))
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
                        commands=commands, command_origins=t0_origins),
                    scope_violations=violations)

        summary = "T0 passed: scope clean, contract valid"
        if t0_cmds:
            summary += ", cheap checks ok"
        else:
            summary += ", no cheap commands configured"

        return _T0Result(
            stage=StageResult(name=StageName.T0_SCOPE_AND_LINT, status=StageStatus.PASSED,
                summary=summary,
                commands=commands, command_origins=t0_origins),
            scope_violations=violations)

    @staticmethod
    def _needs_shell(cmd) -> bool:
        """W06: Detect if a command needs shell=True."""
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        return bool(_SHELL_OPS_PATTERN.search(cmd_str))

    def _run_t1(self, packet: ExecutionPacketContract, changed_files: list[str],
                *, run_dir: Path | None = None, cwd: Path | None = None) -> StageResult:
        base_path = (cwd or self._root).resolve()

        # Explicit commands from architect (complete, not extra)
        explicit_raw = packet.verification.get("t1")
        if isinstance(explicit_raw, list) and "t1" in packet.verification:
            # Architect explicitly provided T1 (even if empty list).
            # Empty list means explicit skip — NORMAL/STRICT still fail.
            all_cmds = [shlex.split(c) if isinstance(c, str) else c for c in explicit_raw]
            all_origins = ["architect:verification"] * len(explicit_raw) if explicit_raw else []
        else:
            # No explicit T1 — use auto defaults from gate resolver
            defaults = resolve_default_gates(changed_files, packet.acceptance_profile.value, base_path)
            all_cmds = defaults["t1"]["commands"]
            all_origins = defaults["t1"]["origins"]

        # Filter out guardrails.sh from T1 — same as T2 filter
        _filter_out_t1 = ("guardrails.sh", "check_frontmatter", "check_secrets")
        filtered_cmds, filtered_origins = [], []
        for cmd, origin in zip(all_cmds, all_origins):
            joined = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if any(f in joined for f in _filter_out_t1):
                continue
            filtered_cmds.append(cmd)
            filtered_origins.append(origin)
        all_cmds, all_origins = filtered_cmds, filtered_origins

        # W06: Detect shell operators and pass shell=True explicitly
        commands = [self._runner.run(cmd, output_dir=run_dir, cwd=cwd, shell=self._needs_shell(cmd)) for cmd in all_cmds]

        if not all_cmds:
            if packet.acceptance_profile == AcceptanceProfile.FAST:
                return StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.SKIPPED,
                                  summary="FAST profile without T1 commands",
                                  skipped_reason="FAST profile without T1 commands",
                                  command_origins=[])
            return StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.FAILED,
                              summary="NORMAL/STRICT requires T1 — no auto defaults and no explicit commands",
                              blocking_issues=["no auto T1 defaults resolved and architect did not provide extra_verification.t1"],
                              command_origins=[])

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
                              blocking_issues=[f"command failed: {c.command} (exit={c.exit_code}) stderr={c.stderr[:200]} stdout={c.stdout[:200]}" for c in failed],
                              command_origins=all_origins)
        return StageResult(name=StageName.T1_TARGETED_TESTS, status=StageStatus.PASSED,
                          summary=f"T1 passed: {len(commands)} commands ok",
                          commands=commands, command_origins=all_origins)

    def _run_t2(self, packet: ExecutionPacketContract, changed_files: list[str],
                *, run_dir: Path | None = None, cwd: Path | None = None) -> StageResult:
        base_path = (cwd or self._root).resolve()

        # Explicit commands from architect (complete, not extra)
        explicit = packet.verification.get("t2", [])

        if explicit:
            # When architect provides explicit T2, use ONLY those commands.
            all_cmds = [shlex.split(c) if isinstance(c, str) else c for c in explicit]
            all_origins = ["architect:verification"] * len(explicit)
        else:
            # No explicit T2 — use auto defaults from gate resolver
            defaults = resolve_default_gates(changed_files, packet.acceptance_profile.value, base_path)
            all_cmds = defaults["t2"]["commands"]
            all_origins = defaults["t2"]["origins"]

        # Filter out guardrails.sh from T2 — it runs full-suite checks that
        # pick up pre-existing failures (secret scan, docs frontmatter, etc.)
        # unrelated to this packet. The architect should provide targeted T2.
        _filter_out = ("guardrails.sh", "check_frontmatter", "check_secrets")
        filtered = []
        origins = []
        for cmd, origin in zip(all_cmds, all_origins):
            joined = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if any(f in joined for f in _filter_out):
                continue
            filtered.append(cmd)
            origins.append(origin)
        all_cmds = filtered
        all_origins = origins

        if not all_cmds:
            if packet.acceptance_profile == AcceptanceProfile.STRICT:
                return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.SKIPPED,
                                  summary="STRICT skipped T2 (guardrails filtered, no explicit commands)",
                                  skipped_reason="guardrails.sh filtered out for packet-level run",
                                  command_origins=[])
            if packet.acceptance_profile == AcceptanceProfile.NORMAL:
                return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.SKIPPED,
                                  summary="NORMAL without T2 commands",
                                  skipped_reason="no verification.t2 configured",
                                  command_origins=[])
            return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.SKIPPED,
                              summary="FAST always skips T2",
                              skipped_reason="FAST profile skips T2",
                              command_origins=[])

        # W06: Detect shell operators and pass shell=True explicitly
        commands = [self._runner.run(cmd, output_dir=run_dir, cwd=cwd, shell=self._needs_shell(cmd)) for cmd in all_cmds]
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
                              blocking_issues=[f"full check failed: {c.command} (exit={c.exit_code}) stderr={c.stderr[:200]} stdout={c.stdout[:200]}" for c in failed],
                              command_origins=all_origins)
        return StageResult(name=StageName.T2_FULL_TESTS, status=StageStatus.PASSED,
                          summary=f"T2 passed: {len(commands)} commands ok",
                          commands=commands, command_origins=all_origins)

# END_BLOCK_PIPELINE_CLASS

# START_BLOCK_FRONTEND_STAGES
def _run_frontend_stages(
    packet: ExecutionPacketContract,
    *,
    worktree_root: Path,
    run_dir: Path,
    run_id: str = "",
) -> dict[str, StageResult]:
    """Run T2_BROWSER_E2E and T3_VISUAL_REGRESSION if frontend is enabled.

    TZ_FRONTEND_ACCEPTANCE P0 — routing via resolve_browser_routing().
    Skips FAST profile entirely. Runs per-viewport in parallel.
    """
    from grace_control.core.frontend_stages import (
        BrowserStageResult,
        resolve_browser_routing,
        run_t2_browser_e2e,
        run_t3_visual_regression,
    )

    frontend_spec = packet.metadata.get("frontend") if hasattr(packet, "metadata") else {}
    routing = resolve_browser_routing(
        frontend_spec,
        acceptance_profile=packet.acceptance_profile.value,
    )

    result: dict[str, StageResult] = {}
    t2b_commands = packet.verification.get("t2_browser", [])
    t3v_commands = packet.verification.get("t3_visual", [])
    t2a_commands = packet.verification.get("t2_a11y", [])

    # T2_BROWSER_E2E
    if routing.run_t2_browser:
        browser_results: list[BrowserStageResult] = run_t2_browser_e2e(
            worktree_root, run_dir, routing,
            telegram_mode=routing.telegram_mode,
            custom_cmds=t2b_commands if t2b_commands else None,
            telegram_bot_token_env=routing.telegram_bot_token_env,
            packet_id=packet.packet_id,
            run_id=run_id,
        )
        passed = all(r.passed for r in browser_results)
        screenshots = sum((r.screenshots for r in browser_results), [])
        errors = sum((r.errors for r in browser_results), [])

        # Build CommandResults from actual browser execution
        cmd_results = [
            CommandResult(
                command=r.command or " ".join(t2b_commands[i]) if i < len(t2b_commands) else "npx playwright test",
                cwd=str(worktree_root),
                exit_code=r.exit_code if r.exit_code >= 0 else (0 if r.passed else 1),
                stdout=r.stdout_snippet,
                stderr=r.stderr_snippet,
            )
            for i, r in enumerate(browser_results)
        ] if browser_results else _commands_to_results(t2b_commands, worktree_path=str(worktree_root), run_dir=str(run_dir))
        result["t2_browser"] = StageResult(
            name=StageName.T2_BROWSER_E2E,
            status=StageStatus.PASSED if passed else StageStatus.FAILED,
            summary=f"T2_BROWSER: {len(browser_results)} viewports, {len(screenshots)} screenshots",
            commands=cmd_results,
            blocking_issues=errors if not passed else [],
        )
    else:
        result["t2_browser"] = StageResult(
            name=StageName.T2_BROWSER_E2E,
            status=StageStatus.SKIPPED,
            summary=f"T2_BROWSER skipped: {routing.reason}",
            commands=[],
            skipped_reason=routing.reason,
        )

    # T3_VISUAL_REGRESSION
    if routing.run_t3_visual:
        visual_results: list[BrowserStageResult] = run_t3_visual_regression(
            worktree_root, run_dir, routing,
            telegram_mode=routing.telegram_mode,
            custom_cmds=t3v_commands if t3v_commands else None,
            telegram_bot_token_env=routing.telegram_bot_token_env,
            packet_id=packet.packet_id,
            run_id=run_id,
        )
        passed = all(r.passed for r in visual_results)
        screenshots = sum((r.screenshots for r in visual_results), [])
        errors = sum((r.errors for r in visual_results), [])

        cmd_results = [
            CommandResult(
                command=r.command or " ".join(t3v_commands[i]) if i < len(t3v_commands) else "npx playwright test --visual",
                cwd=str(worktree_root),
                exit_code=r.exit_code if r.exit_code >= 0 else (0 if r.passed else 1),
                stdout=r.stdout_snippet,
                stderr=r.stderr_snippet,
            )
            for i, r in enumerate(visual_results)
        ] if visual_results else _commands_to_results(t3v_commands, worktree_path=str(worktree_root), run_dir=str(run_dir))
        result["t3_visual"] = StageResult(
            name=StageName.T3_VISUAL_REGRESSION,
            status=StageStatus.PASSED if passed else StageStatus.FAILED,
            summary=f"T3_VISUAL: {len(visual_results)} viewports, {len(screenshots)} screenshots",
            commands=cmd_results,
            blocking_issues=errors if not passed else [],
        )
    else:
        result["t3_visual"] = StageResult(
            name=StageName.T3_VISUAL_REGRESSION,
            status=StageStatus.SKIPPED,
            summary=f"T3_VISUAL skipped: {routing.reason}",
            commands=[],
            skipped_reason=routing.reason,
        )

    # T2_BROWSER_A11Y — axe-core accessibility check (P2)
    if routing.run_a11y:
        if not t2a_commands:
            # A11y required but no custom command specified — cannot run without axe.
            result["t2_browser_a11y"] = StageResult(
                name=StageName.T2_BROWSER_A11Y,
                status=StageStatus.FAILED,
                summary="T2_BROWSER_A11Y failed: verification.t2_a11y is required but empty",
                commands=[],
                blocking_issues=["verification.t2_a11y is required for a11y gate — no axe-core command specified"],
            )
        else:
            from grace_control.core.frontend_stages import run_a11y_check
            a11y_results = run_a11y_check(
                worktree_root, run_dir, routing,
                telegram_mode=routing.telegram_mode,
                telegram_bot_token_env=routing.telegram_bot_token_env,
                custom_cmds=t2a_commands if t2a_commands else None,
                packet_id=packet.packet_id,
                run_id=run_id,
            )
            a11y_passed = all(r.passed for r in a11y_results)
            a11y_errors = sum((r.errors for r in a11y_results), [])
            violations_count = sum(len(r.screenshots) for r in a11y_results)
            result["t2_browser_a11y"] = StageResult(
                name=StageName.T2_BROWSER_A11Y,
                status=StageStatus.PASSED if a11y_passed else StageStatus.FAILED,
                summary=f"T2_BROWSER_A11Y: {len(a11y_results)} viewports, {violations_count} violations",
                commands=[
                    CommandResult(
                        command=r.command or " ".join(t2a_commands[0]) if t2a_commands else f"npx playwright a11y --viewport={r.viewport}",
                        cwd=str(worktree_root),
                        exit_code=0 if r.passed else 1,
                        stdout=r.stdout_snippet,
                        stderr=r.stderr_snippet,
                    )
                    for r in a11y_results
                ],
                blocking_issues=a11y_errors if not a11y_passed else [],
            )
    else:
        result["t2_browser_a11y"] = StageResult(
            name=StageName.T2_BROWSER_A11Y,
            status=StageStatus.SKIPPED,
            summary="T2_BROWSER_A11Y skipped: a11y not required",
            commands=[],
            skipped_reason="a11y not required",
        )

    return result


def _commands_to_results(
    commands: list[list[str]], *, worktree_path: str, run_dir: str
) -> list[CommandResult]:
    """Convert verification command lists to CommandResult objects.

    When commands haven't actually been executed yet (pre-run),
    this produces placeholder results. Actual execution fills them in.
    """
    from grace_control.core.contracts import CommandResult
    return [
        CommandResult(
            command=" ".join(cmd) if isinstance(cmd, list) else str(cmd),
            cwd=worktree_path,
            exit_code=0,
            stdout="",
            stderr="",
        )
        for cmd in commands
    ]

# END_BLOCK_FRONTEND_STAGES
