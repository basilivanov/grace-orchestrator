# ############################################################################
# AI_HEADER: feature_planning_service
# ROLE: Feature planning orchestration — context builder, architect, approval
# ############################################################################

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from grace_control.db.schema import Feature, FeaturePlanningRun, Wave, Packet, Event
from grace_control.db.schema import PacketState


class FeaturePlanningService:
    """Orchestrate feature planning stages."""

    def __init__(self, db):
        self.db = db

    def get_planning_state(self, feature_id: str) -> dict:
        feature = self.db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            raise ValueError(f"Feature not found: {feature_id}")

        runs = self.db.query(FeaturePlanningRun).filter_by(feature_id=feature_id).order_by(FeaturePlanningRun.created_at).all()

        spec = feature.spec_json or {}
        plan_json = spec.get("plan_json") if isinstance(spec, dict) else None

        current_stage = None
        for r in runs:
            if r.status in ("running", "pending"):
                current_stage = r.stage
                break
        if current_stage is None and runs:
            last = runs[-1]
            if last.status != "done":
                current_stage = last.stage

        return {
            "feature_id": feature_id,
            "status": feature.status,
            "current_stage": current_stage,
            "plan_json": plan_json,
            "runs": [
                {
                    "id": r.id,
                    "stage": r.stage,
                    "status": r.status,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                    "duration_ms": r.duration_ms,
                    "executor_id": r.executor_id,
                    "model": r.model,
                    "stdout_path": r.stdout_path,
                    "stderr_path": r.stderr_path,
                    "error": r.error,
                }
                for r in runs
            ],
        }

    def run_context_builder(self, feature_id: str) -> dict:
        cb_run = self.db.query(FeaturePlanningRun).filter_by(
            feature_id=feature_id, stage="context_builder"
        ).order_by(FeaturePlanningRun.created_at.desc()).first()

        now = datetime.now(UTC)
        run_id = cb_run.id if cb_run else f"fpr_{uuid.uuid4().hex[:24]}"
        if not cb_run:
            cb_run = FeaturePlanningRun(id=run_id, feature_id=feature_id, stage="context_builder", status="pending")
            self.db.add(cb_run)

        cb_run.status = "running"
        cb_run.started_at = now
        cb_run.executor_id = "context_collector"

        context = {
            "repo_root": ".",
            "feature_id": feature_id,
            "files_scanned": 0,
            "summary": "Context collection stub — Wave 1",
        }

        cb_run.status = "done"
        cb_run.finished_at = datetime.now(UTC)
        cb_run.duration_ms = int((cb_run.finished_at - cb_run.started_at).total_seconds() * 1000)
        cb_run.result_json = context

        self._emit_event(feature_id, "context_builder_completed", {
            "run_id": run_id, "duration_ms": cb_run.duration_ms,
        })

        self.db.commit()
        return context

    def run_architect(self, feature_id: str, context: dict) -> dict:
        arch_run = self.db.query(FeaturePlanningRun).filter_by(
            feature_id=feature_id, stage="architect"
        ).order_by(FeaturePlanningRun.created_at.desc()).first()

        now = datetime.now(UTC)
        run_id = arch_run.id if arch_run else f"fpr_{uuid.uuid4().hex[:24]}"
        if not arch_run:
            arch_run = FeaturePlanningRun(id=run_id, feature_id=feature_id, stage="architect", status="pending")
            self.db.add(arch_run)

        arch_run.status = "running"
        arch_run.started_at = now
        arch_run.executor_id = "architect-business-flash"
        arch_run.model = "stub-model"

        plan = {
            "waves": [
                {
                    "id": f"wave_{uuid.uuid4().hex[:12]}",
                    "title": "Implementation",
                    "packets": [
                        {
                            "id": f"pkt_{uuid.uuid4().hex[:12]}",
                            "title": "Initial implementation",
                            "scope": ["src/"],
                        }
                    ],
                }
            ],
            "summary": f"Plan for feature {feature_id} — stub",
            "context_used": context.get("summary", ""),
        }

        arch_run.status = "done"
        arch_run.finished_at = datetime.now(UTC)
        arch_run.duration_ms = int((arch_run.finished_at - arch_run.started_at).total_seconds() * 1000)
        arch_run.result_json = plan

        feature = self.db.query(Feature).filter_by(id=feature_id).first()
        if feature:
            spec = dict(feature.spec_json) if feature.spec_json else {}
            spec["plan_json"] = plan
            feature.spec_json = spec
            feature.status = "PLAN_READY"

        self._emit_event(feature_id, "architect_completed", {
            "run_id": run_id, "duration_ms": arch_run.duration_ms, "waves_count": len(plan["waves"]),
        })
        self._emit_event(feature_id, "plan_ready", {
            "waves_count": len(plan["waves"]),
        })

        self.db.commit()
        return plan

    def approve_plan(self, feature_id: str) -> dict:
        feature = self.db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            raise ValueError(f"Feature not found: {feature_id}")
        if feature.status != "PLAN_READY":
            raise ValueError(f"Cannot approve plan in status {feature.status}. Must be PLAN_READY.")

        spec = feature.spec_json or {}
        plan = spec.get("plan_json", {}) if isinstance(spec, dict) else {}
        waves = plan.get("waves", []) if isinstance(plan, dict) else []

        now = datetime.now(UTC)
        materialize_run = FeaturePlanningRun(
            id=f"fpr_{uuid.uuid4().hex[:24]}",
            feature_id=feature_id,
            stage="materialize",
            status="running",
            started_at=now,
            executor_id="plan_materializer",
        )
        self.db.add(materialize_run)

        packet_ids = []
        for i, w in enumerate(waves):
            wave_id = w.get("id", f"wave_{uuid.uuid4().hex[:12]}")
            wave_obj = Wave(
                id=wave_id,
                feature_id=feature_id,
                slug=f"wave-{i}",
                title=w.get("title", f"Wave {i}"),
                order=i,
                status="NOT_STARTED",
            )
            self.db.add(wave_obj)

            is_first_wave = i == 0
            for pkt in w.get("packets", []):
                pkt_id = pkt.get("id", f"pkt_{uuid.uuid4().hex[:12]}")
                packet = Packet(
                    id=pkt_id,
                    feature_id=feature_id,
                    wave_id=wave_id,
                    slug=pkt.get("title", f"pkt-{i}").lower().replace(" ", "-"),
                    title=pkt.get("title", f"Packet {i}"),
                    spec_json=pkt,
                    state=PacketState.READY.value if is_first_wave else PacketState.DRAFT.value,
                )
                self.db.add(packet)
                packet_ids.append(pkt_id)

        materialize_run.status = "done"
        materialize_run.finished_at = datetime.now(UTC)
        materialize_run.duration_ms = int((materialize_run.finished_at - materialize_run.started_at).total_seconds() * 1000)
        materialize_run.result_json = {"waves_count": len(waves), "packets_count": len(packet_ids), "packet_ids": packet_ids}

        feature.status = "queued"

        self._emit_event(feature_id, "plan_materialized", {
            "waves_count": len(waves), "packets_count": len(packet_ids),
        })
        self._emit_event(feature_id, "feature_queued", {})

        self.db.commit()
        return {"status": "queued", "waves_count": len(waves), "packets_count": len(packet_ids), "packet_ids": packet_ids}

    def regenerate_plan(self, feature_id: str) -> dict:
        feature = self.db.query(Feature).filter_by(id=feature_id).first()
        if not feature:
            raise ValueError(f"Feature not found: {feature_id}")
        if feature.status not in ("PLAN_READY", "PLAN_FAILED"):
            raise ValueError(f"Cannot regenerate plan in status {feature.status}. Must be PLAN_READY or PLAN_FAILED.")

        feature.status = "PLANNING"

        cb_run = FeaturePlanningRun(
            id=f"fpr_{uuid.uuid4().hex[:24]}",
            feature_id=feature_id,
            stage="context_builder",
            status="pending",
            executor_id="context_collector",
        )
        self.db.add(cb_run)

        spec = dict(feature.spec_json) if feature.spec_json else {}
        spec.pop("plan_json", None)
        feature.spec_json = spec

        self.db.commit()
        return self.get_planning_state(feature_id)

    def _emit_event(self, feature_id: str, event_type: str, payload: dict, trace_id: str = "") -> None:
        event = Event(
            event_type=event_type,
            entity_type="feature",
            entity_id=feature_id,
            payload_json=payload,
            trace_id=trace_id or "",
        )
        self.db.add(event)
