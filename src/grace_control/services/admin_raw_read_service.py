# ############################################################################
# AI_HEADER: admin_raw_read_service — complete project-local diagnostic models
# ROLE: Builds raw packet, run and stage read models from the local SQLAlchemy
#       session. It exposes persisted JSON and logical artifact resources while
#       keeping physical paths out of browser-facing raw DTOs.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide complete packet/run/stage diagnostics for the project API.
# inputs: SQLAlchemy Session and local entity identifiers.
# returns: JSON-safe raw diagnostic dictionaries or None on missing entities.
# side_effects: Reads the project-local database; does not read arbitrary files.
# emitted_logs: None.
# error_behavior: Returns None for a missing packet/run/stage.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminRawReadService
#     methods:
#       - packet_raw
#       - run_raw
#       - stage_raw
# END_MODULE_MAP

from __future__ import annotations

from datetime import UTC
from typing import Any

from sqlalchemy.orm import Session

from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import Packet, PacketRun, StageRun
from grace_control.services.admin_aggregation_service import AdminAggregationService

_log = GraceLogger("admin_raw_read")


# START_BLOCK_SERVICE
class AdminRawReadService:
    """Read-only complete project diagnostic surface."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure the existing admin aggregation service for compatible
    #          state-machine/pipeline summaries.
    # inputs: aggregator — optional canonical AdminAggregationService.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def __init__(self, aggregator: AdminAggregationService | None = None) -> None:
        self._aggregator = aggregator or AdminAggregationService()

    # START_FUNCTION_CONTRACT
    # name: packet_raw
    # purpose: Return packet spec, complete runs, stages, recovery and pipeline
    #          diagnostic data for one packet.
    # inputs: db (Session), packet_id (str).
    # returns: Complete raw packet DTO or None when missing.
    # side_effects: Reads local ORM rows and existing aggregation summaries.
    # emitted_logs: None.
    # error_behavior: Returns None when packet_id is unknown.
    # END_FUNCTION_CONTRACT
    def packet_raw(self, db: Session, packet_id: str) -> dict[str, Any] | None:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if packet is None:
            return None
        spec = packet.spec_json if isinstance(packet.spec_json, dict) else {}
        runs = db.query(PacketRun).filter_by(packet_id=packet_id).order_by(PacketRun.run_number).all()
        try:
            stages = db.query(StageRun).filter_by(packet_id=packet_id).order_by(StageRun.started_at).all()
        except Exception:
            stages = []
        try:
            detail = self._aggregator.get_packet_detail(db, packet_id) or {}
        except Exception:
            # Raw rows remain useful even when an older pretty DTO expects a
            # legacy Event column that is absent in this database revision.
            detail = {}
        return {
            "packet": {
                "id": packet.id,
                "feature_id": packet.feature_id,
                "wave_id": packet.wave_id,
                "slug": packet.slug,
                "title": packet.title,
                "description": packet.description or "",
                "state": _packet_state(packet),
                "attempt_count": packet.attempt_count,
                "max_attempts": packet.max_attempts,
                "acceptance_profile": packet.acceptance_profile,
                "spec_json": spec,
                "scope": spec.get("scope", []),
                "conflict_keys": spec.get("conflict_keys", []),
                "depends_on": spec.get("depends_on", []),
                "created_at": _iso(packet.created_at),
                "updated_at": _iso(packet.updated_at),
            },
            "runs": [self._run_to_dict(run) for run in runs],
            "stages": [self._stage_to_dict(stage) for stage in stages],
            "state_machine": detail.get("state_machine", {}),
            "pipeline": detail.get("pipeline", {}),
            "recovery": detail.get("recovery"),
            "recovery_chain": detail.get("recovery_chain", []),
            "totals": detail.get("totals", {}),
        }

    # START_FUNCTION_CONTRACT
    # name: run_raw
    # purpose: Return persisted run metadata, prompt/command/evidence metadata
    #          and full result_json for one packet run.
    # inputs: db (Session), packet_id (str), run_id (str).
    # returns: Complete raw run DTO or None when missing.
    # side_effects: Reads local ORM rows only.
    # emitted_logs: None.
    # error_behavior: Returns None when the run does not belong to packet_id.
    # END_FUNCTION_CONTRACT
    def run_raw(self, db: Session, packet_id: str, run_id: str) -> dict[str, Any] | None:
        run = _find_run(db, packet_id, run_id)
        if run is None:
            return None
        return self._run_to_dict(run)

    # START_FUNCTION_CONTRACT
    # name: stage_raw
    # purpose: Return complete StageRun metadata and logical output resources.
    # inputs: db (Session), stage_run_id (str).
    # returns: Complete raw stage DTO or None when missing.
    # side_effects: Reads local ORM rows only; never opens a stage path.
    # emitted_logs: None.
    # error_behavior: Returns None when stage_run_id is unknown.
    # END_FUNCTION_CONTRACT
    def stage_raw(self, db: Session, stage_run_id: str) -> dict[str, Any] | None:
        try:
            stage = db.query(StageRun).filter_by(id=stage_run_id).first()
        except Exception:
            return None
        if stage is None:
            return None
        return self._stage_to_dict(stage)

    # START_FUNCTION_CONTRACT
    # name: _run_to_dict
    # purpose: Serialize a PacketRun without dropping persisted diagnostic fields.
    # inputs: run (PacketRun).
    # returns: JSON-safe run DTO.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for a mapped ORM row.
    # END_FUNCTION_CONTRACT
    def _run_to_dict(self, run: PacketRun) -> dict[str, Any]:
        result = run.result_json if isinstance(run.result_json, dict) else {}
        parallel = result.get("parallel_execution") if isinstance(result.get("parallel_execution"), dict) else {}
        return {
            "run_id": run.id,
            "packet_id": run.packet_id,
            "run_number": run.run_number,
            "status": run.status,
            "executor_id": run.executor_id,
            "worker_id": run.worker_id,
            "model": run.model,
            "prompt": run.prompt,
            "prompt_present": bool(run.prompt),
            "command_preview": run.command_preview or [],
            "tokens_in": run.tokens_in,
            "tokens_out": run.tokens_out,
            "cost_usd": float(run.cost_usd) if run.cost_usd is not None else None,
            "base_sha": run.base_sha,
            "integration_base_sha": run.integration_base_sha,
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
            "duration_ms": run.duration_ms,
            "evidence": {
                "available": bool(run.evidence_path),
                "root": "state" if run.evidence_path else None,
                "resource": "packet_run_evidence" if run.evidence_path else None,
            },
            "evidence_path": (
                f"state://packets/{run.packet_id}/runs/R{run.run_number:02d}"
                if run.evidence_path else None
            ),
            "result_json": result,
            "wait_reason": result.get("wait_reason") or result.get("current_wait_reason"),
            "failure_reason": result.get("failure_reason") or result.get("error"),
            "recovery_reason": result.get("recovery_reason"),
            "integration_recheck": parallel.get("integration_recheck"),
            "parallel_execution": parallel,
        }

    # START_FUNCTION_CONTRACT
    # name: _stage_to_dict
    # purpose: Serialize StageRun fields and map physical output columns to
    #          logical resources addressed by safe filesystem endpoints.
    # inputs: stage (StageRun).
    # returns: JSON-safe stage DTO.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises for a mapped ORM row.
    # END_FUNCTION_CONTRACT
    def _stage_to_dict(self, stage: StageRun) -> dict[str, Any]:
        return {
            "stage_run_id": stage.id,
            "packet_id": stage.packet_id,
            "run_id": stage.run_id,
            "feature_id": stage.feature_id,
            "wave_id": stage.wave_id,
            "stage_key": stage.stage_key,
            "attempt_number": stage.attempt_number,
            "loop_round": stage.loop_round,
            "parent_stage_run_id": stage.parent_stage_run_id,
            "status": stage.status,
            "error": stage.error,
            "started_at": _iso(stage.started_at),
            "finished_at": _iso(stage.finished_at),
            "last_heartbeat": _iso(stage.last_heartbeat),
            "duration_ms": stage.duration_ms,
            "executor_id": stage.executor_id,
            "worker_id": stage.worker_id,
            "model": stage.model,
            "prompt_hash": stage.prompt_hash,
            "command_preview": stage.command_preview or [],
            "tokens_in": stage.tokens_in,
            "tokens_out": stage.tokens_out,
            "cost_usd": float(stage.cost_usd) if stage.cost_usd is not None else None,
            "trace_id": stage.trace_id,
            "recovery_reason": stage.recovery_reason,
            "logical_paths": {
                "stdout": _logical_resource(stage.id, "stdout", stage.stdout_path),
                "stderr": _logical_resource(stage.id, "stderr", stage.stderr_path),
                "result": _logical_resource(stage.id, "result", stage.result_path),
                "artifacts": _logical_resource(stage.id, "artifacts", stage.artifacts_dir),
            },
            "stdout_path": _logical_resource(stage.id, "stdout", stage.stdout_path),
            "stderr_path": _logical_resource(stage.id, "stderr", stage.stderr_path),
            "result_path": _logical_resource(stage.id, "result", stage.result_path),
            "artifacts_dir": _logical_resource(stage.id, "artifacts", stage.artifacts_dir),
        }


# END_BLOCK_SERVICE


# START_BLOCK_HELPERS
def _find_run(db: Session, packet_id: str, run_id: str) -> PacketRun | None:
    run = db.query(PacketRun).filter_by(id=run_id, packet_id=packet_id).first()
    if run is not None:
        return run
    return db.query(PacketRun).filter_by(id=f"{packet_id}-{run_id}", packet_id=packet_id).first()


def _logical_resource(stage_run_id: str, kind: str, configured_path: str | None) -> dict[str, Any]:
    return {
        "resource": f"stage_{kind}",
        "stage_run_id": stage_run_id,
        "available": bool(configured_path),
    }


def _packet_state(packet: Packet) -> str:
    return str(getattr(packet, "state", ""))


def _iso(value) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat().replace("+00:00", "Z")


# END_BLOCK_HELPERS
