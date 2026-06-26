# ############################################################################
# AI_HEADER: rerun_pipeline_service — verifier/reviewer rerun with gate chaining
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Execute verifier/reviewer rerun with context from previous terminal run.
#          Enforces correct gate sequence: verifier→reviewer, no shortcut to merge.
# inputs: RerunStage, packet_contract, RerunContext, current_evidence_dir, started_at
# outputs: RerunResult
# invariants:
#   - Verifier PASS alone never returns accepted (chains to reviewer)
#   - Reviewer rerun requires persisted verifier verdict == PASS
#   - All accepted results preserve merge metadata (worktree, branch)
# side_effects: LLM calls via run_evidence_verifier / run_reviewer_gate
# error_behavior: Returns controlled failure RerunResult with stable failure_code
# observability: GraceLogger with packet_id, run_id, stage, duration_ms, verdict
# non_goals:
#   - Does not load context (call rerun_context_service separately)
#   - Does not persist anything
#   - Does not touch PacketRun or Packet in DB
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: execute_rerun
# END_MODULE_MAP

from __future__ import annotations

import time
from pathlib import Path

from grace_control.core.rerun_contracts import RerunContext, RerunResult, RerunStage
from grace_control.core.structured_logger import GraceLogger
from grace_control.core.acceptance_pipeline import AcceptanceReport
from grace_control.core.contracts import FinalVerdict, AcceptanceProfile
from grace_control.core.evidence_verifier import (
    EvidenceVerifierReport,
    EvidenceVerifierVerdict,
    run_evidence_verifier,
)
from grace_control.core.reviewer_gate import run_reviewer_gate

_log = GraceLogger("rerun_pipeline")


def _build_acceptance_report(context: RerunContext) -> AcceptanceReport:
    """Reconstitute AcceptanceReport from context dict, converting strings to enums."""
    acc = context.acceptance_report
    fv_str = acc.get("final_verdict", "rework_required")
    try:
        final_verdict = FinalVerdict(fv_str)
    except (ValueError, TypeError):
        final_verdict = FinalVerdict.REWORK_REQUIRED
    profile_str = acc.get("profile", "NORMAL")
    try:
        profile = AcceptanceProfile(profile_str)
    except (ValueError, TypeError):
        profile = AcceptanceProfile.NORMAL
    return AcceptanceReport(
        packet_id=context.packet_id,
        final_verdict=final_verdict,
        profile=profile,
        stages=acc.get("stages", []),
        summary=acc.get("summary", ""),
    )


def _build_verifier_report(evr_data: dict | None) -> EvidenceVerifierReport | None:
    """Reconstitute EvidenceVerifierReport from context dict."""
    if not evr_data or not isinstance(evr_data, dict):
        return None
    verdict_str = evr_data.get("verdict", "")
    if not verdict_str:
        return None
    try:
        verdict = EvidenceVerifierVerdict(verdict_str)
    except (ValueError, TypeError):
        return None
    return EvidenceVerifierReport(
        verdict=verdict,
        summary=evr_data.get("summary", ""),
        missing_evidence=evr_data.get("missing_evidence", []),
        failed_checks=evr_data.get("failed_checks", []),
    )


async def execute_rerun(
    *,
    stage: RerunStage,
    packet_contract,
    context: RerunContext,
    current_evidence_dir: Path,
    started_at: float,
) -> RerunResult:
    """Execute a single rerun stage. Chains verifier→reviewer when verifier PASSes.

    Returns a RerunResult ready for persistence and/or merge.
    """
    _log.info("rerun_stage_started", packet_id=context.packet_id,
               run_id=context.current_run_id, stage=stage.value,
               source_run_id=context.source_run_id)

    last_acceptance = _build_acceptance_report(context)

    # Carrier for original acceptance report dict in result evidence
    def _make_ev(extra: dict | None = None) -> dict:
        ev = dict(extra or {})
        ev["acceptance_report"] = context.acceptance_report
        return ev

    try:
        if stage == RerunStage.VERIFIER:
            evr = await run_evidence_verifier(
                packet=packet_contract,
                acceptance_report=last_acceptance,
                worktree_path=Path(context.source_worktree_path),
                run_dir=Path(context.source_run_dir),
                changed_files=[],
                artifacts=[],
            )
            if evr.verdict.value != "PASS":
                _log.info("rerun_verifier_completed", packet_id=context.packet_id,
                           run_id=context.current_run_id, verdict=evr.verdict.value,
                           duration_ms=int((time.time() - started_at) * 1000))
                return RerunResult(
                    accepted=False, domain_status="rejected",
                    reason=evr.summary or "verifier rerun rejected",
                    duration_ms=int((time.time() - started_at) * 1000),
                    source_run_id=context.source_run_id,
                    worktree_path=context.source_worktree_path,
                    branch_name=context.branch_name,
                    evidence=_make_ev({
                        "verifier_verdict": evr.verdict.value,
                        "summary": evr.summary,
                    }),
                    evidence_verifier_report=evr.model_dump(),
                )

            # Verifier PASS -> chain to reviewer
            _log.info("rerun_verifier_pass_chain_reviewer", packet_id=context.packet_id,
                       run_id=context.current_run_id)
            rvr = await run_reviewer_gate(
                packet=packet_contract,
                acceptance_report=last_acceptance,
                evidence_verifier_report=evr,
                worktree_path=Path(context.source_worktree_path),
                run_dir=Path(context.source_run_dir),
                changed_files=[],
                artifacts=[],
            )
            accepted = rvr.verdict.value == "PASS"
            _log.info("rerun_reviewer_completed", packet_id=context.packet_id,
                       run_id=context.current_run_id,
                       verdict=rvr.verdict.value, accepted=accepted,
                       duration_ms=int((time.time() - started_at) * 1000))
            return RerunResult(
                accepted=accepted,
                domain_status="accepted" if accepted else "rejected",
                reason=rvr.summary or (
                    "reviewer rerun accepted" if accepted else "reviewer rerun rejected"
                ),
                duration_ms=int((time.time() - started_at) * 1000),
                source_run_id=context.source_run_id,
                worktree_path=context.source_worktree_path,
                branch_name=context.branch_name,
                evidence=_make_ev({
                    "verifier_verdict": evr.verdict.value,
                    "reviewer_verdict": rvr.verdict.value,
                    "verifier_summary": evr.summary,
                    "reviewer_summary": rvr.summary,
                }),
                evidence_verifier_report=evr.model_dump(),
                reviewer_report=rvr.model_dump(),
            )

        elif stage == RerunStage.REVIEWER:
            # Reviewer rerun requires persisted verifier PASS
            last_verifier_report = _build_verifier_report(context.evidence_verifier_report)
            if not last_verifier_report or last_verifier_report.verdict.value != "PASS":
                _log.warn("rerun_verifier_context_missing", packet_id=context.packet_id,
                           run_id=context.current_run_id,
                           source_run_id=context.source_run_id)
                return RerunResult(
                    accepted=False, domain_status="rejected",
                    reason="RERUN_VERIFIER_CONTEXT_MISSING: previous verifier verdict not PASS",
                    duration_ms=int((time.time() - started_at) * 1000),
                    source_run_id=context.source_run_id,
                    evidence=_make_ev({"rerun_error": "RERUN_VERIFIER_CONTEXT_MISSING"}),
                )

            rvr = await run_reviewer_gate(
                packet=packet_contract,
                acceptance_report=last_acceptance,
                evidence_verifier_report=last_verifier_report,
                worktree_path=Path(context.source_worktree_path),
                run_dir=Path(context.source_run_dir),
                changed_files=[],
                artifacts=[],
            )
            accepted = rvr.verdict.value == "PASS"
            _log.info("rerun_reviewer_completed", packet_id=context.packet_id,
                       run_id=context.current_run_id,
                       verdict=rvr.verdict.value, accepted=accepted,
                       duration_ms=int((time.time() - started_at) * 1000))
            return RerunResult(
                accepted=accepted,
                domain_status="accepted" if accepted else "rejected",
                reason=rvr.summary or (
                    "reviewer rerun accepted" if accepted else "reviewer rerun rejected"
                ),
                duration_ms=int((time.time() - started_at) * 1000),
                source_run_id=context.source_run_id,
                worktree_path=context.source_worktree_path,
                branch_name=context.branch_name,
                evidence=_make_ev({
                    "reviewer_verdict": rvr.verdict.value,
                    "summary": rvr.summary,
                }),
                reviewer_report=rvr.model_dump(),
            )
    except Exception as e:
        _log.error("rerun_stage_failed", packet_id=context.packet_id,
                    run_id=context.current_run_id, stage=stage.value,
                    error=str(e)[:200])
        return RerunResult(
            accepted=False, domain_status="failed",
            reason=str(e)[:500],
            duration_ms=int((time.time() - started_at) * 1000),
            source_run_id=context.source_run_id,
            evidence={"error": str(e)[:500]},
        )

    _log.error("rerun_unknown_stage", packet_id=context.packet_id,
                stage=stage.value)
    return RerunResult(
        accepted=False, domain_status="failed",
        reason=f"unknown rerun stage: {stage.value}",
        duration_ms=int((time.time() - started_at) * 1000),
        source_run_id=context.source_run_id,
    )
