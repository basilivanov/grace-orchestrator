# ############################################################################
# AI_HEADER: feature_intake_service
# ROLE: Feature creation and intake orchestration
# ############################################################################

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from grace_control.db.schema import Feature, FeaturePlanningRun, Event


class FeatureIntakeService:
    """Orchestrate feature creation and initial planning lifecycle."""

    def __init__(self, db):
        self.db = db

    def create_feature(
        self,
        title: str,
        description: str | None = None,
        target_repo_root: str | None = None,
        mode: str = "draft_plan",
        origin: str = "business",
        self_improvement: bool = False,
        trace_id: str = "",
    ) -> dict:
        feature_id = f"feat_{uuid.uuid4().hex[:24]}"
        slug = title.lower().replace(" ", "-")[:64]
        now = datetime.now(UTC)

        spec = {
            "title": title,
            "description": description,
            "target_repo_root": target_repo_root,
            "mode": mode,
            "origin": origin,
        }

        feature = Feature(
            id=feature_id,
            slug=slug,
            title=title,
            description=description,
            spec_json=spec,
            status="PLANNING",
        )
        self.db.add(feature)

        submit_run = FeaturePlanningRun(
            id=f"fpr_{uuid.uuid4().hex[:24]}",
            feature_id=feature_id,
            stage="submit",
            status="done",
            started_at=now,
            finished_at=now,
            duration_ms=0,
            executor_id="feature_intake",
            trace_id=trace_id,
        )
        self.db.add(submit_run)

        cb_run = FeaturePlanningRun(
            id=f"fpr_{uuid.uuid4().hex[:24]}",
            feature_id=feature_id,
            stage="context_builder",
            status="pending",
            executor_id="context_collector",
            trace_id=trace_id,
        )
        self.db.add(cb_run)

        self._emit_event(feature_id, "feature_submitted", {
            "mode": mode,
            "origin": origin,
            "title": title,
        }, trace_id)
        self._emit_event(feature_id, "planning_started", {
            "current_stage": "context_builder",
        }, trace_id)

        self.db.commit()

        return {
            "feature_id": feature_id,
            "status": "PLANNING",
            "mode": mode,
            "planning": {
                "current_stage": "context_builder",
                "runs": [
                    {"id": submit_run.id, "stage": "submit", "status": "done",
                     "executor_id": "feature_intake"},
                    {"id": cb_run.id, "stage": "context_builder", "status": "pending",
                     "executor_id": "context_collector"},
                ],
            },
        }

    def _emit_event(self, feature_id: str, event_type: str, payload: dict, trace_id: str = "") -> None:
        event = Event(
            event_type=event_type,
            entity_type="feature",
            entity_id=feature_id,
            payload_json=payload,
            trace_id=trace_id or "",
        )
        self.db.add(event)
