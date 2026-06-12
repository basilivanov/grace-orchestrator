from __future__ import annotations

import pytest
from datetime import UTC, datetime

from grace_control.db.schema import Feature, FeaturePlanningRun, Packet, PacketState, Wave, Event


@pytest.mark.usefixtures("db")
class TestFeaturePlanningStore:
    """Service-layer tests for FeaturePlanningService and FeatureIntakeService."""

    def test_create_feature_creates_planning_runs(self, db):
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.db import get_db

        with get_db() as s:
            svc = FeatureIntakeService(s)
            result = svc.create_feature(
                title="Test Feature",
                description="A test feature",
                mode="draft_plan",
                origin="business",
            )
            fid = result["feature_id"]

            runs = s.query(FeaturePlanningRun).filter_by(feature_id=fid).all()
            assert len(runs) >= 2
            stages = [r.stage for r in runs]
            assert "submit" in stages
            assert "context_builder" in stages

            feat = s.query(Feature).filter_by(id=fid).first()
            assert feat is not None
            assert feat.status == "PLANNING"
            assert feat.title == "Test Feature"

    def test_get_planning_state(self, db):
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="State Test", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            state = planning.get_planning_state(fid)

            assert state["feature_id"] == fid
            assert state["status"] == "PLANNING"
            assert state["current_stage"] is not None
            assert len(state["runs"]) >= 2

    def test_run_context_builder(self, db):
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="CB Test", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            context = planning.run_context_builder(fid)

            assert isinstance(context, dict)
            assert "feature_id" in context
            assert context["feature_id"] == fid

            # Verify run is marked done
            runs = s.query(FeaturePlanningRun).filter_by(
                feature_id=fid, stage="context_builder"
            ).all()
            assert len(runs) >= 1
            assert runs[-1].status == "done"
            assert runs[-1].duration_ms is not None

    def test_run_architect(self, db):
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="Arch Test", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            context = planning.run_context_builder(fid)
            plan = planning.run_architect(fid, context)

            assert isinstance(plan, dict)
            assert "waves" in plan
            assert plan["summary"] is not None

            # Verify feature is PLAN_READY
            feat = s.query(Feature).filter_by(id=fid).first()
            assert feat.status == "PLAN_READY"

    def test_approve_plan_sets_queued_and_readies_first_wave(self, db):
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="Approve Test", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            context = planning.run_context_builder(fid)
            planning.run_architect(fid, context)
            approval = planning.approve_plan(fid)

            assert approval["status"] == "queued"
            assert approval["waves_count"] >= 1
            assert "packet_ids" in approval

            # Verify feature status
            feat = s.query(Feature).filter_by(id=fid).first()
            assert feat.status == "queued"

            # Verify first-wave packets are READY
            waves = s.query(Wave).filter_by(feature_id=fid).order_by(Wave.order).all()
            if waves:
                first_wave = waves[0]
                first_packets = s.query(Packet).filter_by(
                    feature_id=fid, wave_id=first_wave.id
                ).all()
                for p in first_packets:
                    assert p.state == "ready", f"packet {p.id} should be READY, got {p.state}"

    def test_approve_fails_if_not_plan_ready(self, db):
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="Fail Approve", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            import pytest as _pt
            with _pt.raises(ValueError, match="PLAN_READY"):
                planning.approve_plan(fid)

    def test_regenerate_plan_resets_state(self, db):
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="Regen Test", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            context = planning.run_context_builder(fid)
            planning.run_architect(fid, context)

            state = planning.regenerate_plan(fid)
            assert state["status"] == "PLANNING"

            # A new context_builder run should be created
            runs = s.query(FeaturePlanningRun).filter_by(
                feature_id=fid, stage="context_builder"
            ).all()
            assert len(runs) >= 2

    def test_events_emitted_for_feature(self, db):
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="Events Test", mode="draft_plan")
            fid = result["feature_id"]

            events = s.query(Event).filter_by(
                entity_type="feature", entity_id=fid
            ).all()
            event_types = [e.event_type for e in events]
            assert "feature_submitted" in event_types
            assert "planning_started" in event_types

    def test_intake_service_includes_target_repo(self, db):
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.db import get_db

        with get_db() as s:
            svc = FeatureIntakeService(s)
            result = svc.create_feature(
                title="Repo Test",
                target_repo_root="/opt/test-repo",
                mode="draft_plan",
            )
            fid = result["feature_id"]

            feat = s.query(Feature).filter_by(id=fid).first()
            spec = feat.spec_json or {}
            assert spec.get("target_repo_root") == "/opt/test-repo"
