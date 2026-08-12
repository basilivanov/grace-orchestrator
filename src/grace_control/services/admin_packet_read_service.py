# ############################################################################
# AI_HEADER: admin_packet_read_service — packet and run read models
# ROLE: Owns packet detail, run summaries, timeline, blocking decisions and
#       session reads behind the stable admin aggregation facade. It delegates
#       pipeline projections and session reads to explicit collaborators.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build packet-centric admin DTOs without changing the public facade.
# inputs: SQLAlchemy Session, packet IDs/run selectors and read collaborators.
# returns: Existing packet/detail/run/timeline DTO dictionaries.
# side_effects: Reads ORM rows, persisted JSON and session registry metadata.
# emitted_logs: None (session storage retains its existing logging behavior).
# error_behavior: Missing packets/runs return None or the existing empty DTO.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminPacketReadService
#     methods:
#       - get_packet_detail
#       - get_packet_blocking_decision
#       - get_packet_timeline
#       - get_packet_runs
#       - get_packet_sessions
# END_MODULE_MAP

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import Event, Packet, PacketRun
from grace_control.services.admin_overview_read_service import (
    _elapsed_seconds,
    _is_running,
    _iso,
    _packet_state,
)
from grace_control.services.admin_read_models import PacketRunSummary
from grace_control.services.admin_read_ports import PacketSessionReader

_log = GraceLogger("admin_packet_read")


# START_BLOCK_CONSTANTS
_BLOCKING_STATES = frozenset([
    "rejected", "failed", "blocked", "blocked_recoverable", "blocked_final",
])
# END_BLOCK_CONSTANTS


# START_BLOCK_HELPERS
def _packet_spec_value(packet: Packet, key: str, default: Any) -> Any:
    spec = packet.spec_json if isinstance(packet.spec_json, dict) else {}
    value = spec.get(key, default)
    return value if isinstance(value, type(default)) else default


def _packet_run_summary(run: PacketRun) -> dict[str, Any]:
    # START_FUNCTION_CONTRACT
    # name: _packet_run_summary
    # purpose: Serialize one rich PacketRun row through the bounded read model.
    # inputs: run — persisted PacketRun ORM row.
    # returns: Plain dictionary preserving the packet-runs endpoint shape.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Propagates missing ORM attributes as the prior mapper did.
    # END_FUNCTION_CONTRACT
    return PacketRunSummary(
        run_id=run.id,
        run_number=run.run_number,
        worker_id=run.worker_id or "",
        executor_id=run.executor_id or "",
        model=run.model or "",
        status=run.status,
        duration_ms=run.duration_ms or 0,
        started_at=_iso(run.started_at),
        finished_at=_iso(run.finished_at),
        elapsed_seconds=_elapsed_seconds(run.started_at, run.finished_at),
        is_running=_is_running(run.status, run.started_at, run.finished_at),
        tokens_in=run.tokens_in,
        tokens_out=run.tokens_out,
        cost_usd=float(run.cost_usd) if run.cost_usd is not None else None,
        base_sha=run.base_sha,
        integration_base_sha=run.integration_base_sha,
    ).to_dict()


# END_BLOCK_HELPERS


# START_BLOCK_SERVICE
class AdminPacketReadService:
    """Read-only owner for packet-centric admin DTOs."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure every collaborator required by packet read methods.
    # inputs: size_calculator, pipeline_service and session_reader.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Collaborator contract errors propagate during calls.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        size_calculator: Any,
        pipeline_service: Any,
        session_reader: PacketSessionReader,
    ) -> None:
        self._size_calc = size_calculator
        self._pipeline_service = pipeline_service
        self._session_reader = session_reader

    # START_FUNCTION_CONTRACT
    # name: get_packet_detail
    # purpose: Return the complete operator-console packet detail DTO.
    # inputs: db — active SQLAlchemy Session; packet_id — canonical packet ID.
    # returns: Existing packet detail dictionary or None when missing.
    # side_effects: Reads packet/run/stage/event/session/evidence metadata.
    # emitted_logs: None.
    # error_behavior: Missing packet returns None; optional reads fall back to
    #                 the existing empty DTO shapes.
    # END_FUNCTION_CONTRACT
    def get_packet_detail(self, db: Session, packet_id: str) -> dict[str, Any] | None:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            return None
        runs = (
            db.query(PacketRun)
            .filter_by(packet_id=packet_id)
            .order_by(PacketRun.run_number)
            .all()
        )
        last_run = runs[-1] if runs else None
        runs_breakdown = self._size_calc.packet_runs_breakdown(packet_id)
        dev_replay = None
        if last_run and last_run.result_json:
            replay = last_run.result_json.get("dev_replay", {})
            if replay:
                dev_replays = last_run.result_json.get("dev_replays", [])
                dev_replay = {
                    "run_id": last_run.id,
                    "run_number": last_run.run_number,
                    **replay,
                    "replays": dev_replays,
                }
                if "worktree_path" in dev_replay:
                    dev_replay["worktree_path"] = str(dev_replay["worktree_path"])
                if "run_dir" in dev_replay:
                    dev_replay["run_dir"] = str(dev_replay["run_dir"])
        runs_summary = [
            {
                "run_id": run.id,
                "run_number": run.run_number,
                "executor_id": run.executor_id or "",
                "status": run.status,
                "duration_ms": run.duration_ms or 0,
                "started_at": _iso(run.started_at),
                "finished_at": _iso(run.finished_at),
            }
            for run in runs
        ]
        pipeline = self._pipeline_service
        return {
            "packet": {
                "id": packet.id,
                "feature_id": packet.feature_id,
                "wave_id": packet.wave_id,
                "slug": packet.slug,
                "title": packet.title,
                "state": _packet_state(packet),
                "acceptance_profile": packet.acceptance_profile,
                "description": packet.description or "",
                "spec_json": packet.spec_json if isinstance(packet.spec_json, dict) else {},
                "scope": _packet_spec_value(packet, "scope", []),
                "conflict_keys": _packet_spec_value(packet, "conflict_keys", []),
                "depends_on": _packet_spec_value(packet, "depends_on", []),
                "attempt_count": packet.attempt_count,
                "max_attempts": packet.max_attempts,
                "created_at": _iso(packet.created_at),
                "updated_at": _iso(packet.updated_at),
            },
            "worker_id": (last_run.worker_id if last_run else "") or "",
            "model": (last_run.model if last_run else "") or "",
            "started_at": _iso(last_run.started_at) if last_run else None,
            "finished_at": _iso(last_run.finished_at) if last_run else None,
            "elapsed_seconds": (
                _elapsed_seconds(last_run.started_at, last_run.finished_at)
                if last_run else None
            ),
            "is_running": (
                _is_running(last_run.status, last_run.started_at, last_run.finished_at)
                if last_run else False
            ),
            "recovery": self._recovery_dict(last_run),
            "recommendation": self._recommend(packet, last_run),
            "sessions_summary": self.get_packet_sessions(db, packet_id),
            "runs_summary": runs_summary,
            "runs_breakdown": runs_breakdown.to_dict(),
            "total_size_bytes": runs_breakdown.size_bytes,
            "blocking_decision": self.get_packet_blocking_decision(db, packet_id),
            "state_machine": pipeline.derive_state_machine(db, packet, runs),
            "pipeline": pipeline.derive_pipeline(db, packet, runs),
            "dev_replay": dev_replay,
            "stages": pipeline.derive_stages(db, packet),
            "recovery_chain": pipeline.derive_recovery_chain(db, packet),
            "totals": pipeline.derive_totals(db, packet),
        }

    # START_FUNCTION_CONTRACT
    # name: get_packet_blocking_decision
    # purpose: Return the existing blocking decision DTO for terminal packet
    #          states and None for non-blocking states.
    # inputs: db and packet_id.
    # returns: Blocking decision dictionary or None.
    # side_effects: Reads packet, run and recovery event rows.
    # emitted_logs: None.
    # error_behavior: Missing/non-blocking packet returns None.
    # END_FUNCTION_CONTRACT
    def get_packet_blocking_decision(
        self,
        db: Session,
        packet_id: str,
    ) -> dict[str, Any] | None:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet or _packet_state(packet) not in _BLOCKING_STATES:
            return None
        last_run = (
            db.query(PacketRun)
            .filter_by(packet_id=packet_id)
            .order_by(PacketRun.run_number.desc())
            .first()
        )
        if last_run is None:
            return {
                "has_blocking": True,
                "state": _packet_state(packet),
                "decided_by": None,
                "action": None,
                "reason": None,
                "at": None,
                "last_failure": None,
            }
        result_json = last_run.result_json or {}
        recovery = result_json.get("recovery") or {}
        last_failure = self._last_failure_from_run(last_run)
        decided_by = self._detect_decision_component(db, packet_id, _packet_state(packet))
        action = recovery.get("action", "") or None
        reason = (
            recovery.get("reason", "")
            or result_json.get("acceptance_report", {}).get("summary", "")
            if last_run.result_json
            else None
        )
        return {
            "has_blocking": True,
            "state": _packet_state(packet),
            "decided_by": decided_by,
            "action": action,
            "reason": reason,
            "at": _iso(last_run.finished_at) or _iso(last_run.started_at),
            "last_failure": last_failure,
        }

    # START_FUNCTION_CONTRACT
    # name: get_packet_timeline
    # purpose: Return the paginated packet event timeline in reverse time order.
    # inputs: db, packet_id, limit and offset.
    # returns: Existing total/limit/offset/events dictionary.
    # side_effects: Reads Event rows only.
    # emitted_logs: None.
    # error_behavior: Empty packet timelines return total zero and no events.
    # END_FUNCTION_CONTRACT
    def get_packet_timeline(
        self,
        db: Session,
        packet_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        query = db.query(Event).filter(Event.entity_id == packet_id)
        total = query.count()
        rows = (
            query.order_by(Event.timestamp.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        events = [
            {
                "id": event.id,
                "timestamp": _iso(event.timestamp),
                "event_type": event.event_type,
                "entity_type": event.entity_type,
                "entity_id": event.entity_id,
                "component": (event.payload_json or {}).get("component", "") or "",
                "reason": (event.payload_json or {}).get("reason", "") or "",
                "payload": event.payload_json or {},
                "trace_id": event.trace_id or "",
            }
            for event in rows
        ]
        return {"total": total, "limit": limit, "offset": offset, "events": events}

    # START_FUNCTION_CONTRACT
    # name: get_packet_runs
    # purpose: Return all packet runs with timing, execution and cost fields.
    # inputs: db and packet_id.
    # returns: Dictionary containing the ordered runs list.
    # side_effects: Reads PacketRun rows only.
    # emitted_logs: None.
    # error_behavior: Unknown packet returns an empty runs list.
    # END_FUNCTION_CONTRACT
    def get_packet_runs(self, db: Session, packet_id: str) -> dict[str, Any]:
        runs = (
            db.query(PacketRun)
            .filter_by(packet_id=packet_id)
            .order_by(PacketRun.run_number)
            .all()
        )
        return {
            "runs": [_packet_run_summary(run) for run in runs]
        }

    # START_FUNCTION_CONTRACT
    # name: get_packet_sessions
    # purpose: Return the session-store summary for a packet.
    # inputs: db and packet_id.
    # returns: Existing session summary dictionary.
    # side_effects: Reads the optional agent_sessions table.
    # emitted_logs: SessionStore's existing session query logs.
    # error_behavior: SessionStore returns its table_missing/empty fallback.
    # END_FUNCTION_CONTRACT
    def get_packet_sessions(self, db: Session, packet_id: str) -> dict[str, Any]:
        return self._session_reader.get_packet_sessions(db, packet_id)

    # END_BLOCK_SERVICE

    # START_BLOCK_DECISION_HELPERS
    def _detect_decision_component(self, db: Session, packet_id: str, state: str) -> str | None:
        if state not in _BLOCKING_STATES:
            return None
        last_recovery = (
            db.query(Event)
            .filter(Event.entity_id == packet_id, Event.event_type.like("recovery_%"))
            .order_by(Event.timestamp.desc())
            .first()
        )
        if last_recovery:
            event_type = last_recovery.event_type
            known_events = (
                "recovery_classified", "recovery_decision_made", "recovery_retry_same_coder",
                "recovery_switch_coder", "recovery_return_to_architect", "recovery_escalate_architect",
                "recovery_retry_verifier", "recovery_retry_reviewer", "recovery_retry_merge",
                "recovery_block_feature", "recovery_no_action", "recovery_apply_failed",
            )
            if event_type in known_events:
                payload = last_recovery.payload_json or {}
                component = payload.get("component", "") or payload.get("decided_by", "")
                if component:
                    return component
                if event_type == "recovery_block_feature":
                    return "feature_recovery"
                return "recovery_controller"
        if state in ("rejected", "failed"):
            return "acceptance_pipeline"
        return None

    def _last_failure_from_run(self, run: PacketRun) -> dict[str, Any] | None:
        result_json = run.result_json or {}
        acceptance = result_json.get("acceptance_report") or {}
        stages = acceptance.get("stages", []) or []
        blocking_issues: list[str] = []
        for stage in stages:
            blocking_issues.extend(stage.get("blocking_issues", []) or [])
        command_failures: list[dict[str, Any]] = []
        if blocking_issues or acceptance.get("summary"):
            for stage in stages:
                for command in stage.get("commands", []) or []:
                    if (command.get("exit_code") or 0) != 0 or command.get("timed_out"):
                        command_failures.append({
                            "command": command.get("command", ""),
                            "exit_code": command.get("exit_code", -1),
                            "stderr_tail": self._tail_text(command.get("stderr", "") or "", 30),
                            "stdout_tail": self._tail_text(command.get("stdout", "") or "", 30),
                        })
        legacy_result = result_json.get("legacy_result", {})
        stderr_tail = self._tail_text(
            legacy_result.get("stderr", "") if isinstance(legacy_result, dict) else "",
            30,
        )
        command_preview = list(run.command_preview or [])
        prompt = run.prompt or ""
        if not (blocking_issues or acceptance.get("summary") or stderr_tail or command_failures):
            return None
        return {
            "stage": "acceptance" if acceptance else "executor",
            "summary": acceptance.get("summary", "") or result_json.get("reason", ""),
            "blocking_issues": blocking_issues,
            "command_failures": command_failures,
            "stderr_tail": stderr_tail,
            "command_preview": command_preview,
            "model": run.model or "",
            "prompt_preview": self._tail_text(prompt, 30),
        }

    @staticmethod
    def _tail_text(value: str, lines: int) -> str:
        if not value:
            return ""
        chunks = value.splitlines()
        return "\n".join(chunks[-lines:]) if len(chunks) > lines else value

    def _recovery_dict(self, run: PacketRun | None) -> dict[str, Any] | None:
        if run is None or run.result_json is None:
            return None
        recovery = run.result_json.get("recovery") or {}
        if not recovery:
            return None
        return {
            "failure_class": recovery.get("failure_class", ""),
            "action": recovery.get("action", ""),
            "reason": recovery.get("reason", ""),
            "current_executor_id": recovery.get("current_executor_id", ""),
            "next_executor_hint": recovery.get("next_executor_hint", ""),
            "decision_id": recovery.get("decision_id", ""),
        }

    @staticmethod
    def _recommend(packet: Packet, last_run: PacketRun | None) -> str:
        if _packet_state(packet) in ("merged", "accepted"):
            return "none"
        if last_run is None:
            return "none"
        if last_run.status in ("rejected", "failed", "blocked"):
            return "manual" if packet.attempt_count >= packet.max_attempts else "retry"
        return "none"


# END_BLOCK_DECISION_HELPERS
