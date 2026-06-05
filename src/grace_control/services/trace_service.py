# ############################################################################
# AI_HEADER: trace_service
# ROLE: Read-only aggregator for packet / feature / run / wave trace data.
#       Replaces the deleted `grace trace --packet/--feature/--wave` CLI (W2)
#       and is the single source of truth for /api/trace/* (W4).
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build trace DTOs from Packet / PacketRun / Event / Feature / Wave
#          rows. No HTTP, no CLI, no Prefect. Routers call this; never
#          build SQL aggregation loops in the router.
# inputs: SQLAlchemy Session + entity IDs / search string.
# returns: Plain dicts (DTOs). None when the entity is not found.
# side_effects: None.
# emitted_logs: None (read-only).
# error_behavior: Never raises; returns None or empty list on miss.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: TraceService
#     methods:
#       - get_packet_trace
#       - get_run_trace
#       - get_feature_trace
#       - search
# END_MODULE_MAP

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from grace_control.db.schema import (
    Event,
    Feature,
    Packet,
    PacketRun,
    Wave,
)


class TraceService:
    """Read-only aggregator for packet / feature / run / wave trace data."""

    # START_FUNCTION_CONTRACT
    # name: get_packet_trace
    # purpose: Return the full trace of one packet: state, runs, timeline,
    #          last failure, recommended next action.
    # inputs: db (Session), packet_id (str).
    # returns: dict | None — None when the packet is not found.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def get_packet_trace(self, db: Session, packet_id: str) -> dict[str, Any] | None:
        packet = db.query(Packet).filter_by(id=packet_id).first()
        if not packet:
            return None
        runs = (
            db.query(PacketRun)
            .filter_by(packet_id=packet_id)
            .order_by(PacketRun.run_number)
            .all()
        )
        events = (
            db.query(Event)
            .filter_by(entity_id=packet_id)
            .order_by(Event.timestamp)
            .all()
        )
        last_failure = self._last_failure(runs)
        return {
            "packet_id": packet.id,
            "feature_id": packet.feature_id,
            "wave_id": packet.wave_id,
            "title": packet.title,
            "slug": packet.slug,
            "current_state": packet.state,
            "attempt_count": packet.attempt_count,
            "max_attempts": packet.max_attempts,
            "runs": [self._run_to_dict(r) for r in runs],
            "timeline": [self._event_to_dict(e) for e in events],
            "last_failure": last_failure,
            "recommended_next_action": self._recommend(packet, last_failure),
        }

    # START_FUNCTION_CONTRACT
    # name: get_run_trace
    # purpose: Return one PacketRun with its full result_json exposed.
    # inputs: db (Session), run_id (str).
    # returns: dict | None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def get_run_trace(self, db: Session, run_id: str) -> dict[str, Any] | None:
        run = db.query(PacketRun).filter_by(id=run_id).first()
        if not run:
            return None
        return self._run_to_dict(run, with_result=True)

    # START_FUNCTION_CONTRACT
    # name: get_feature_trace
    # purpose: Return feature → waves → packets grouped summary + timeline.
    # inputs: db (Session), feature_id (str).
    # returns: dict | None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def get_feature_trace(self, db: Session, feature_id: str) -> dict[str, Any] | None:
        feature = db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            return None
        waves = (
            db.query(Wave)
            .filter_by(feature_id=feature_id)
            .order_by(Wave.order)
            .all()
        )
        packets = db.query(Packet).filter_by(feature_id=feature_id).all()
        grouped: dict[str, list[dict[str, Any]]] = {w.id: [] for w in waves}
        for p in packets:
            grouped.setdefault(p.wave_id, []).append({
                "packet_id": p.id,
                "slug": p.slug,
                "title": p.title,
                "state": p.state,
                "attempt_count": p.attempt_count,
            })
        events = (
            db.query(Event)
            .filter_by(entity_id=feature_id)
            .order_by(Event.timestamp)
            .all()
        )
        return {
            "feature_id": feature.id,
            "title": feature.title,
            "status": feature.status,
            "waves": [
                {
                    "wave_id": w.id,
                    "title": w.title,
                    "order": w.order,
                    "status": w.status,
                    "packets": grouped.get(w.id, []),
                }
                for w in waves
            ],
            "packets_without_wave": grouped.get("", []),
            "timeline": [self._event_to_dict(e) for e in events],
        }

    # START_FUNCTION_CONTRACT
    # name: search
    # purpose: Cross-entity substring search (MVP; no full-text engine).
    #          Matches packet id / title, feature title, run executor_id.
    # inputs: db (Session), q (str), limit (int, default 25, max 200).
    # returns: list of dicts with keys {kind, id, ...}.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Returns [] when q is empty.
    # END_FUNCTION_CONTRACT
    def search(self, db: Session, q: str, limit: int = 25) -> list[dict[str, Any]]:
        if not q:
            return []
        like = f"%{q}%"
        packets = (
            db.query(Packet)
            .filter((Packet.id.ilike(like)) | (Packet.title.ilike(like)))
            .limit(limit)
            .all()
        )
        features = (
            db.query(Feature)
            .filter(Feature.title.ilike(like))
            .limit(limit)
            .all()
        )
        runs = (
            db.query(PacketRun)
            .filter(PacketRun.executor_id.ilike(like))
            .limit(limit)
            .all()
        )
        out: list[dict[str, Any]] = []
        for p in packets:
            out.append({"kind": "packet", "id": p.id, "title": p.title, "state": p.state})
        for f in features:
            out.append({"kind": "feature", "id": f.id, "title": f.title, "status": f.status})
        for r in runs:
            out.append({
                "kind": "run",
                "id": r.id,
                "packet_id": r.packet_id,
                "executor_id": r.executor_id,
                "status": r.status,
            })
        return out[:limit]

    # START_BLOCK_DTO_HELPERS
    def _run_to_dict(self, r: PacketRun, with_result: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "run_id": r.id,
            "run_number": r.run_number,
            "status": r.status,
            "executor_id": r.executor_id,
            "worker_id": r.worker_id,
            "started_at": r.started_at.isoformat() + "Z" if r.started_at else "",
            "finished_at": r.finished_at.isoformat() + "Z" if r.finished_at else "",
            "duration_ms": r.duration_ms or 0,
            "evidence_path": r.evidence_path or "",
        }
        if with_result and r.result_json:
            rj = r.result_json
            acc = rj.get("acceptance_report", {}) or {}
            d["acceptance_verdict"] = acc.get("final_verdict", "")
            d["acceptance_summary"] = acc.get("summary", "")
        return d

    def _event_to_dict(self, e: Event) -> dict[str, Any]:
        return {
            "timestamp": e.timestamp.isoformat() + "Z" if e.timestamp else "",
            "event_type": e.event_type,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "payload": e.payload_json or {},
            "trace_id": e.trace_id or "",
        }

    def _last_failure(self, runs: list[PacketRun]) -> dict[str, Any] | None:
        for r in reversed(runs):
            if r.status in ("rejected", "failed", "blocked"):
                rj = r.result_json or {}
                acc = rj.get("acceptance_report", {}) or {}
                blocking_issues: list[str] = []
                for stage in acc.get("stages", []) or []:
                    blocking_issues.extend(stage.get("blocking_issues", []) or [])
                return {
                    "stage": "acceptance" if acc else "executor",
                    "summary": acc.get("summary", "") or rj.get("reason", ""),
                    "blocking_issues": blocking_issues,
                }
        return None

    def _recommend(self, packet: Packet, last_failure: dict[str, Any] | None) -> str:
        if packet.state == "merged":
            return "none"
        if last_failure is None:
            return "none"
        if packet.attempt_count >= packet.max_attempts:
            return "manual"
        return "retry"
    # END_BLOCK_DTO_HELPERS
