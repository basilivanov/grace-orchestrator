# ############################################################################
# AI_HEADER: dashboard_service
# ROLE: Aggregated view for the dashboard UI. Extracted from api/main.py
#       in W5 of source/codex/tz-api-first-cleanup-waves-w0-w11.md. The
#       only place that builds the /api/dashboard payload.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build the dashboard's view of features → waves → packets, plus
#          workers and per-state stats. The router does no DB aggregation.
# inputs: Session.
# returns: dict with keys {features[], workers[], stats{}}.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: DashboardService
#     methods:
#       - get_dashboard
# END_MODULE_MAP

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from grace_control.db.schema import (
    Feature,
    Packet,
    PacketRun,
    Wave,
    Worker,
)


class DashboardService:
    """Aggregates features → waves → packets + workers + stats for the UI."""

    # START_FUNCTION_CONTRACT
    # name: get_dashboard
    # purpose: Build the full dashboard payload in one pass.
    # inputs: db (Session).
    # returns: dict with three top-level keys:
    #   features: list of {id, slug, title, status, waves[], blocked_recovery_count}
    #             waves[i].packets[j] carries the most recent recovery metadata
    #             for that packet (or null).
    #   workers:  list of {id, status, current_packet_id, last_heartbeat}
    #   stats:    dict of state → count plus {"workers": active_count}
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Never raises.
    # END_FUNCTION_CONTRACT
    def get_dashboard(self, db: Session) -> dict[str, Any]:
        features = db.query(Feature).all()
        workers = db.query(Worker).all()
        result_features: list[dict[str, Any]] = []
        for f in features:
            waves = (
                db.query(Wave)
                .filter_by(feature_id=f.id)
                .order_by(Wave.order)
                .all()
            )
            fw: list[dict[str, Any]] = []
            for w in waves:
                packets = (
                    db.query(Packet)
                    .filter_by(feature_id=f.id, wave_id=w.id)
                    .all()
                )
                fw_packets: list[dict[str, Any]] = []
                for p in packets:
                    recovery_data = self._recovery_for_packet(db, p.id)
                    fw_packets.append({
                        "id": p.id,
                        "title": p.title,
                        "state": p.state,
                        "acceptance_profile": p.acceptance_profile,
                        "attempt_count": p.attempt_count,
                        "max_attempts": p.max_attempts,
                        "feature_id": p.feature_id,
                        "wave_id": p.wave_id,
                        "created_at": self._iso(p.created_at),
                        "updated_at": self._iso(p.updated_at),
                        "recovery": recovery_data,
                    })
                fw.append({
                    "id": w.id,
                    "title": w.title,
                    "order": w.order,
                    "status": w.status,
                    "packets": fw_packets,
                    "created_at": self._iso(w.created_at),
                })
            blocked_recovery_count = sum(
                1 for w in fw for p in w["packets"]
                if p["state"] == "blocked"
                and p.get("recovery") and p["recovery"].get("blocked_reason")
            )
            result_features.append({
                "id": f.id,
                "slug": f.slug,
                "title": f.title,
                "status": f.status,
                "waves": fw,
                "created_at": self._iso(f.created_at),
                "blocked_recovery_count": blocked_recovery_count,
            })
        stats: dict[str, int] = {}
        for p in db.query(Packet).all():
            stats[p.state] = stats.get(p.state, 0) + 1
        active_workers = len([w for w in workers if w.status == "active"])
        return {
            "features": result_features,
            "workers": [
                {
                    "id": w.id,
                    "status": w.status,
                    "current_packet_id": w.current_packet_id,
                    "last_heartbeat": self._iso(w.last_heartbeat),
                }
                for w in workers
            ],
            "stats": {**stats, "workers": active_workers},
        }

    # START_BLOCK_DTO_HELPERS
    def _recovery_for_packet(self, db: Session, packet_id: str) -> dict[str, Any] | None:
        runs = (
            db.query(PacketRun)
            .filter_by(packet_id=packet_id)
            .order_by(PacketRun.run_number.desc())
            .limit(5)
            .all()
        )
        for r in runs:
            rj = r.result_json or {}
            if rj.get("recovery"):
                rec = rj["recovery"]
                return {
                    "failure_class": rec.get("failure_class", ""),
                    "action": rec.get("action", ""),
                    "reason": rec.get("reason", ""),
                    "current_executor_id": rec.get("current_executor_id", ""),
                    "next_executor_hint": rec.get("next_executor_hint", ""),
                    "decision_id": rec.get("decision_id", ""),
                }
        return None

    @staticmethod
    def _iso(dt) -> str | None:
        return dt.isoformat() + "Z" if dt else None
    # END_BLOCK_DTO_HELPERS
