# ############################################################################
# AI_HEADER: admin_feature_read_service — feature, wave and search reads
# ROLE: Owns the feature tree, feature summary, wave detail and cross-entity
#       search DTOs used by the admin UI. Packet pipeline details are delegated
#       to AdminPipelineReadService and size totals to SizeCalculator.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build feature/wave/search read models for the admin facade.
# inputs: SQLAlchemy Session, feature/wave identifiers and search parameters.
# returns: Existing feature tree, wave detail and search dictionaries.
# side_effects: Reads ORM rows and bounded local size metadata.
# emitted_logs: None.
# error_behavior: Missing feature/wave returns None; empty searches return an
#                 empty results list.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminFeatureReadService
#     methods:
#       - get_feature_summary
#       - get_features_tree
#       - get_wave_detail
#       - search
# END_MODULE_MAP

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from grace_control.core.structured_logger import GraceLogger
from grace_control.db.schema import Feature, Packet, PacketRun, Wave
from grace_control.services.admin_overview_read_service import (
    _elapsed_seconds,
    _iso,
    _packet_state,
)

_log = GraceLogger("admin_feature_read")


# START_BLOCK_SERVICE
class AdminFeatureReadService:
    """Read-only owner for feature, wave and search DTOs."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Configure size and pipeline read collaborators.
    # inputs: size_calculator and pipeline_service.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises during configuration.
    # END_FUNCTION_CONTRACT
    def __init__(self, size_calculator: Any, pipeline_service: Any) -> None:
        self._size_calc = size_calculator
        self._pipeline_service = pipeline_service

    # START_FUNCTION_CONTRACT
    # name: get_feature_summary
    # purpose: Return one feature grouped into ordered waves and packet rows.
    # inputs: db and feature_id.
    # returns: Feature summary DTO or None when missing.
    # side_effects: Reads feature, wave and packet rows.
    # emitted_logs: None.
    # error_behavior: Unknown feature returns None.
    # END_FUNCTION_CONTRACT
    def get_feature_summary(
        self,
        db: Session,
        feature_id: str,
    ) -> dict[str, Any] | None:
        feature = db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            return None
        waves = db.query(Wave).filter_by(feature_id=feature_id).order_by(Wave.order).all()
        packets = db.query(Packet).filter_by(feature_id=feature_id).all()
        packets_by_wave: dict[str, list[dict[str, Any]]] = {wave.id: [] for wave in waves}
        for packet in packets:
            packets_by_wave.setdefault(packet.wave_id, []).append({
                "id": packet.id,
                "slug": packet.slug,
                "title": packet.title,
                "state": _packet_state(packet),
                "attempt_count": packet.attempt_count,
            })
        wave_rows: list[dict[str, Any]] = []
        for wave in waves:
            wave_packets = packets_by_wave.get(wave.id, [])
            attention_count = sum(
                1 for packet in wave_packets
                if packet.get("state") in (
                    "rejected", "failed", "blocked", "blocked_recoverable", "blocked_final",
                )
            )
            wave_rows.append({
                "id": wave.id,
                "title": wave.title,
                "order": wave.order,
                "status": wave.status,
                "packets": wave_packets,
                "total_packets": len(wave_packets),
                "attention_count": attention_count,
            })
        return {
            "feature": {
                "id": feature.id,
                "slug": feature.slug,
                "title": feature.title,
                "status": feature.status,
                "description": feature.description or "",
                "created_at": _iso(feature.created_at),
                "updated_at": _iso(feature.updated_at),
            },
            "waves": wave_rows,
        }

    # START_FUNCTION_CONTRACT
    # name: get_features_tree
    # purpose: Return all non-archived features with nested waves and packet
    #          pipeline previews, optionally including archived features.
    # inputs: db and include_archived flag.
    # returns: Dictionary containing the ordered features tree.
    # side_effects: Reads ORM rows and local run-size metadata.
    # emitted_logs: None.
    # error_behavior: Empty database returns {"features": []}.
    # END_FUNCTION_CONTRACT
    def get_features_tree(
        self,
        db: Session,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        query = db.query(Feature)
        if not include_archived:
            query = query.filter(Feature.status != "ARCHIVED")
        features = query.order_by(Feature.created_at).all()
        output: list[dict[str, Any]] = []
        for feature in features:
            waves = db.query(Wave).filter_by(feature_id=feature.id).order_by(Wave.order).all()
            packets = db.query(Packet).filter_by(feature_id=feature.id).all()
            packets_by_wave: dict[str, list[dict[str, Any]]] = {wave.id: [] for wave in waves}
            for packet in packets:
                last_run = (
                    db.query(PacketRun)
                    .filter_by(packet_id=packet.id)
                    .order_by(PacketRun.run_number.desc())
                    .first()
                )
                pipeline = self._pipeline_service.derive_simple_pipeline(
                    packet,
                    last_run,
                    feature.status,
                    db,
                )
                started_at = (
                    _iso(last_run.started_at)
                    if last_run and last_run.started_at else None
                )
                duration_seconds = (
                    _elapsed_seconds(last_run.started_at, last_run.finished_at)
                    if last_run else None
                )
                packets_by_wave.setdefault(packet.wave_id, []).append({
                    "id": packet.id,
                    "slug": packet.slug,
                    "title": packet.title,
                    "feature_id": packet.feature_id,
                    "state": _packet_state(packet),
                    "attempt_count": packet.attempt_count,
                    "max_attempts": packet.max_attempts,
                    "created_at": _iso(packet.created_at),
                    "updated_at": _iso(packet.updated_at),
                    "pipeline": pipeline,
                    "stage": pipeline["stages"][-1],
                    "started_at": started_at,
                    "duration_seconds": duration_seconds,
                    "size_bytes": self._size_calc.packet_runs_size(packet.id),
                })
            wave_rows: list[dict[str, Any]] = []
            for wave in waves:
                wave_packets = packets_by_wave.get(wave.id, [])
                attention_count = sum(
                    1 for packet in wave_packets
                    if packet.get("state") in (
                        "rejected", "failed", "blocked",
                        "blocked_recoverable", "blocked_final",
                    )
                )
                wave_rows.append({
                    "id": wave.id,
                    "slug": wave.slug,
                    "title": wave.title,
                    "order": wave.order,
                    "status": wave.status,
                    "packets": wave_packets,
                    "total_packets": len(wave_packets),
                    "attention_count": attention_count,
                    "size_bytes": sum(packet.get("size_bytes", 0) for packet in wave_packets),
                })
            all_packets = [
                packet
                for wave_packets in packets_by_wave.values()
                for packet in wave_packets
            ]
            attention_count = sum(
                1 for packet in all_packets
                if packet.get("state") in (
                    "rejected", "failed", "blocked",
                    "blocked_recoverable", "blocked_final",
                )
            )
            spec = feature.spec_json or {}
            approval_mode = spec.get("approval_mode", "auto") if isinstance(spec, dict) else "auto"
            output.append({
                "id": feature.id,
                "slug": feature.slug,
                "title": feature.title,
                "status": feature.status,
                "description": feature.description or "",
                "approval_mode": approval_mode,
                "created_at": _iso(feature.created_at),
                "updated_at": _iso(feature.updated_at),
                "wave_count": len(wave_rows),
                "total_packets": len(all_packets),
                "is_archived": feature.status == "ARCHIVED",
                "attention_count": attention_count,
                "waves": wave_rows,
            })
        return {"features": output}

    # START_FUNCTION_CONTRACT
    # name: get_wave_detail
    # purpose: Return one wave with feature context, packet timing, current
    #          stages, counts and total size.
    # inputs: db, feature_id and wave_id.
    # returns: Wave detail DTO or None when the wave/feature pairing is absent.
    # side_effects: Reads feature/wave/packet/run rows and local size metadata.
    # emitted_logs: None.
    # error_behavior: Missing or cross-feature wave returns None.
    # END_FUNCTION_CONTRACT
    def get_wave_detail(
        self,
        db: Session,
        feature_id: str,
        wave_id: str,
    ) -> dict[str, Any] | None:
        feature = db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            return None
        wave = db.query(Wave).filter_by(id=wave_id, feature_id=feature_id).first()
        if not wave:
            return None
        packets = (
            db.query(Packet)
            .filter_by(wave_id=wave_id, feature_id=feature_id)
            .order_by(Packet.id)
            .all()
        )
        packet_rows: list[dict[str, Any]] = []
        for packet in packets:
            last_run = (
                db.query(PacketRun)
                .filter_by(packet_id=packet.id)
                .order_by(PacketRun.run_number.desc())
                .first()
            )
            started_at = _iso(last_run.started_at) if last_run and last_run.started_at else None
            duration_seconds = (
                _elapsed_seconds(last_run.started_at, last_run.finished_at)
                if last_run else None
            )
            packet_rows.append({
                "id": packet.id,
                "title": packet.title,
                "slug": packet.slug,
                "state": _packet_state(packet),
                "attempt_count": packet.attempt_count,
                "max_attempts": packet.max_attempts,
                "started_at": started_at,
                "duration_seconds": duration_seconds,
                "stage": self._pipeline_service.derive_packet_stage(packet, last_run),
                "size_bytes": self._size_calc.packet_runs_size(packet.id),
            })
        counts = {
            "all": len(packet_rows), "failed": 0, "running": 0,
            "blocked": 0, "attention": 0, "done": 0,
        }
        for packet in packet_rows:
            state = packet["state"]
            if state in ("rejected", "failed"):
                counts["failed"] += 1
                counts["attention"] += 1
            elif state == "running":
                counts["running"] += 1
            elif state in ("blocked", "blocked_recoverable", "blocked_final"):
                counts["blocked"] += 1
                counts["attention"] += 1
            elif state in ("accepted", "merged"):
                counts["done"] += 1
        return {
            "wave": {
                "id": wave.id,
                "title": wave.title,
                "slug": wave.slug,
                "order": wave.order,
                "status": wave.status,
                "feature_id": feature.id,
            },
            "feature": {
                "id": feature.id,
                "title": feature.title,
                "slug": feature.slug,
                "status": feature.status,
            },
            "counts": counts,
            "packets": packet_rows,
            "stage_progress": self._derive_wave_stage_progress(packet_rows),
            "total_size_bytes": sum(packet.get("size_bytes", 0) for packet in packet_rows),
        }

    # START_FUNCTION_CONTRACT
    # name: search
    # purpose: Search packet IDs/titles, feature titles and run executors by
    #          substring while preserving the existing result shape/limit.
    # inputs: db, q and result limit.
    # returns: Dictionary containing the ordered results list.
    # side_effects: Reads Packet, Feature and PacketRun rows.
    # emitted_logs: None.
    # error_behavior: Empty query returns {"results": []}.
    # END_FUNCTION_CONTRACT
    def search(self, db: Session, q: str, limit: int = 50) -> dict[str, Any]:
        if not q:
            return {"results": []}
        like = f"%{q}%"
        output: list[dict[str, Any]] = []
        for packet in (
            db.query(Packet)
            .filter((Packet.id.ilike(like)) | (Packet.title.ilike(like)))
            .limit(limit)
            .all()
        ):
            output.append({
                "kind": "packet", "id": packet.id,
                "title": packet.title, "state": _packet_state(packet),
            })
        for feature in db.query(Feature).filter(Feature.title.ilike(like)).limit(limit).all():
            output.append({
                "kind": "feature", "id": feature.id,
                "title": feature.title, "status": feature.status,
            })
        for run in db.query(PacketRun).filter(PacketRun.executor_id.ilike(like)).limit(limit).all():
            output.append({
                "kind": "run", "id": run.id, "packet_id": run.packet_id,
                "executor_id": run.executor_id or "", "status": run.status,
            })
        return {"results": output[:limit]}

    # END_BLOCK_SERVICE

    # START_BLOCK_WAVE_HELPERS
    @staticmethod
    def _derive_wave_stage_progress(
        packets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        stage_order = [
            ("materialized", "Materialized"),
            ("coder_run", "Coder run"),
            ("reviewer", "Reviewer gate"),
            ("merge", "Merge reached"),
        ]
        total = len(packets)
        if total == 0:
            return [
                {"key": key, "label": label, "reached": 0, "total": 0, "severity": "muted"}
                for key, label in stage_order
            ]
        index_for = {key: index for index, (key, _) in enumerate(stage_order)}
        result: list[dict[str, Any]] = []
        for index, (key, label) in enumerate(stage_order):
            reached = sum(
                1 for packet in packets
                if index_for.get(packet.get("stage", {}).get("key", ""), 0) >= index
            )
            severity = "ok" if reached == total else ("muted" if reached == 0 else "attention")
            result.append({
                "key": key,
                "label": label,
                "reached": reached,
                "total": total,
                "severity": severity,
            })
        return result

    # END_BLOCK_WAVE_HELPERS
