# ############################################################################
# AI_HEADER: packet_execution_rerun_service — one-shot verifier/reviewer rerun dispatch
# ROLE: Delegates rerun execution to the existing context, pipeline, and result
#       persistence services without allowing a normal backend fall-through.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Execute and persist a marked packet rerun through the canonical rerun services.
# inputs: Packet id, rerun stage marker, packet contract, current run/evidence context.
# returns: RerunResult carrying the terminal rerun outcome.
# side_effects: Reads prior terminal context and persists the rerun result.
# emitted_logs: rerun_stage_branch and canonical rerun pipeline messages.
# error_behavior: Returns a controlled missing-context RerunResult.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketExecutionRerunService
#     methods:
#       - dispatch
# END_MODULE_MAP

from __future__ import annotations

import time
from pathlib import Path

from grace_control.core.rerun_contracts import RerunResult, RerunStage
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("adapter")


# START_BLOCK_RERUN
class PacketExecutionRerunService:

    # START_FUNCTION_CONTRACT
    # name: dispatch
    # purpose: Execute exactly one marked rerun and persist its terminal result.
    # inputs: packet_id, rerun_marker, packet_contract, run_id, evidence_dir, started_at.
    # returns: RerunResult with the canonical rerun outcome.
    # side_effects: Loads prior terminal context and writes current run evidence.
    # emitted_logs: rerun_stage_branch.
    # error_behavior: Returns RERUN_CONTEXT_MISSING when no prior terminal run exists.
    # END_FUNCTION_CONTRACT
    async def dispatch(
        self,
        *,
        packet_id: str,
        rerun_marker: str,
        packet_contract,
        run_id: str,
        evidence_dir: Path,
        started_at: float,
    ) -> RerunResult:
        from grace_control.services.rerun_context_service import load_previous_terminal_context
        from grace_control.services.rerun_pipeline_service import execute_rerun
        from grace_control.services.run_result_persistence_service import persist_rerun_result

        stage_enum = RerunStage(rerun_marker)
        rerun_ctx = load_previous_terminal_context(
            packet_id=packet_id,
            current_run_id=run_id,
        )
        if not rerun_ctx:
            missing = RerunResult(
                accepted=False,
                domain_status="failed",
                reason="RERUN_CONTEXT_MISSING: no previous terminal run found",
                duration_ms=int((time.time() - started_at) * 1000),
                evidence={
                    "rerun_error": "RERUN_CONTEXT_MISSING",
                    "detail": "no previous terminal run",
                },
            )
            persist_rerun_result(
                run_id=run_id,
                packet_id=packet_id,
                result=missing,
                evidence_dir=evidence_dir,
                started_at=started_at,
            )
            return missing

        result = await execute_rerun(
            stage=stage_enum,
            packet_contract=packet_contract,
            context=rerun_ctx,
            current_evidence_dir=evidence_dir,
            started_at=started_at,
        )
        persist_rerun_result(
            run_id=run_id,
            packet_id=packet_id,
            result=result,
            evidence_dir=evidence_dir,
            started_at=started_at,
        )
        _log.info(
            "rerun_stage_dispatched",
            packet_id=packet_id,
            run_id=run_id,
            stage=rerun_marker,
        )
        return result

# END_BLOCK_RERUN
