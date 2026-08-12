from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from grace_control.db.schema import Feature, FeaturePlanningRun, Packet, PacketState, Wave, Event


@pytest.fixture
def current_architect_llm(monkeypatch):
    """Provide a deterministic current-contract Architect response for store tests."""
    monkeypatch.delenv("GRACE_CONTEXT_DISABLED", raising=False)

    async def fake_run_llm(*args, **kwargs):
        del args, kwargs
        return json.dumps({
            "title": "Deterministic test plan",
            "description": "A plan used by the deterministic planning-store tests.",
            "waves": [{
                "title": "W1",
                "packets": [{
                    "title": "Implement test feature",
                    "role": "coder",
                    "scope": ["src/test_feature.py"],
                    "frozen_scope": [],
                    "acceptance_profile": "NORMAL",
                    "depends_on": [],
                    "conflict_keys": [],
                    "description": "Implement the deterministic test feature.",
                    "coder_instructions": ["Keep the change local to the packet scope."],
                    "acceptance_criteria": ["The scoped implementation exists."],
                    "verification": {"t0": [], "t1": ["true"], "t2": []},
                    "expected_evidence": [],
                }],
            }],
            "constraints": {"frozen_scope": []},
            "verification": {"t0": [], "t1": [], "t2": []},
        })

    monkeypatch.setattr("grace_control.core.llm_runner.run_llm", fake_run_llm)


@pytest.mark.usefixtures("db")
class TestFeaturePlanningStore:
    """Service-layer tests for FeaturePlanningService and FeatureIntakeService."""

    def test_create_feature_creates_planning_runs(self):
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

    def test_get_planning_state(self):
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

    @pytest.mark.asyncio
    async def test_run_context_builder(self):
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="CB Test", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            context = await planning.run_context_builder(fid)

            assert isinstance(context, dict)
            assert context.get("summary") is not None

            # Verify run is marked done
            runs = s.query(FeaturePlanningRun).filter_by(
                feature_id=fid, stage="context_builder"
            ).all()
            assert len(runs) >= 1
            assert runs[-1].status == "done"
            assert runs[-1].duration_ms is not None

    @pytest.mark.asyncio
    async def test_run_architect(self, current_architect_llm):
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="Arch Test", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            context = await planning.run_context_builder(fid)
            plan = await planning.run_architect(fid, context)

            assert isinstance(plan, dict)
            assert "waves" in plan
            assert len(plan.get("waves", [])) > 0

            # Verify feature is PLAN_READY
            feat = s.query(Feature).filter_by(id=fid).first()
            assert feat.status == "PLAN_READY"

    @pytest.mark.asyncio
    async def test_approve_plan_sets_queued_and_readies_first_wave(self, current_architect_llm):
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="Approve Test", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            context = await planning.run_context_builder(fid)
            await planning.run_architect(fid, context)
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

    def test_approve_fails_if_not_plan_ready(self):
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="Fail Approve", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            with pytest.raises(ValueError, match="PLAN_READY"):
                planning.approve_plan(fid)

    @pytest.mark.asyncio
    async def test_regenerate_plan_resets_state(self, current_architect_llm):
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="Regen Test", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            context = await planning.run_context_builder(fid)
            await planning.run_architect(fid, context)

            state = planning.regenerate_plan(fid)
            assert state["status"] == "PLANNING"

            # A new context_builder run should be created
            runs = s.query(FeaturePlanningRun).filter_by(
                feature_id=fid, stage="context_builder"
            ).all()
            assert len(runs) >= 2

    def test_events_emitted_for_feature(self):
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

    def test_intake_service_includes_target_repo(self):
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

    @pytest.mark.asyncio
    async def test_context_builder_sets_stdout_stderr_paths(self):
        """Wave 4: planning run stores log paths."""
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="Log Paths Test", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            # GRACE_CONTEXT_DISABLED means log dir is created but not used
            context = await planning.run_context_builder(fid)

            runs = s.query(FeaturePlanningRun).filter_by(
                feature_id=fid, stage="context_builder"
            ).all()
            assert len(runs) >= 1
            r = runs[-1]
            assert r.stdout_path is not None
            assert r.stderr_path is not None
            from grace_control.config.settings import settings
            assert settings.planning_logs_root in r.stdout_path
            assert settings.planning_logs_root in r.stderr_path

    @pytest.mark.asyncio
    async def test_architect_sets_stdout_stderr_paths(self, current_architect_llm):
        """Wave 4: architect run stores log paths."""
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db
        from grace_control.config.settings import settings

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="Arch Log Paths", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            context = await planning.run_context_builder(fid)
            await planning.run_architect(fid, context)

            runs = s.query(FeaturePlanningRun).filter_by(
                feature_id=fid, stage="architect"
            ).all()
            assert len(runs) >= 1
            r = runs[-1]
            assert r.stdout_path is not None
            assert r.stderr_path is not None
            assert settings.planning_logs_root in r.stdout_path

    @pytest.mark.asyncio
    async def test_approve_blocked_on_plan_failed(self):
        """Approve raises 409 when feature is PLAN_FAILED."""
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="Fail Approve2", mode="draft_plan")
            fid = result["feature_id"]
            feat = s.query(Feature).filter_by(id=fid).first()
            feat.status = "PLAN_FAILED"
            s.commit()

            planning = FeaturePlanningService(s)
            with pytest.raises(ValueError, match="PLAN_READY"):
                planning.approve_plan(fid)

    @pytest.mark.asyncio
    async def test_approve_creates_ready_first_wave_draft_rest(self, current_architect_llm):
        """After approve, exact state assertions on multi-wave plan."""
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="MultiWave Q", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            context = await planning.run_context_builder(fid)
            await planning.run_architect(fid, context)
            approval = planning.approve_plan(fid)

            assert approval["status"] == "queued"
            assert approval["waves_count"] >= 1

            waves = s.query(Wave).filter_by(feature_id=fid).order_by(Wave.order).all()
            for i, wave in enumerate(waves):
                packets = s.query(Packet).filter_by(
                    feature_id=fid, wave_id=wave.id
                ).all()
                for p in packets:
                    if i == 0:
                        assert p.state == "ready", f"first-wave pkt {p.id} not ready: {p.state}"
                    else:
                        assert p.state == "draft", f"later-wave pkt {p.id} not draft: {p.state}"

    @pytest.mark.asyncio
    async def test_feature_id_uses_canonical_uid_format(self):
        """Feature IDs use canonical feat_ format from uid.py."""
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="UID Format", mode="draft_plan")
            fid = result["feature_id"]
            assert fid.startswith("feat_")
            assert len(fid) == 15  # feat_ + 10 nanoid chars

    @pytest.mark.asyncio
    async def test_packets_use_canonical_pkt_uid(self, current_architect_llm):
        """After approve, packet IDs start with pkt_."""
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(title="Pkt UID", mode="draft_plan")
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            context = await planning.run_context_builder(fid)
            await planning.run_architect(fid, context)
            approval = planning.approve_plan(fid)

            for pid in approval.get("packet_ids", []):
                assert pid.startswith("pkt_")
                assert len(pid) == 14  # pkt_ + 10 nanoid chars

    def test_create_feature_persists_approval_mode(self):
        """FeatureIntakeService persists approval_mode in spec_json."""
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.db import get_db

        with get_db() as s:
            svc = FeatureIntakeService(s)
            result = svc.create_feature(
                title="Approval Mode Test", mode="draft_plan",
                approval_mode="manual",
            )
            fid = result["feature_id"]

            feat = s.query(Feature).filter_by(id=fid).first()
            spec = feat.spec_json or {}
            assert spec.get("approval_mode") == "manual"

    def test_create_feature_default_approval_mode_is_auto(self):
        """FeatureIntakeService defaults approval_mode to auto."""
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.db import get_db

        with get_db() as s:
            svc = FeatureIntakeService(s)
            result = svc.create_feature(
                title="Default Approval Mode", mode="draft_plan",
            )
            fid = result["feature_id"]

            feat = s.query(Feature).filter_by(id=fid).first()
            spec = feat.spec_json or {}
            assert spec.get("approval_mode") == "auto"

    @pytest.mark.asyncio
    async def test_approve_plan_event_includes_approval_mode(self, current_architect_llm):
        """plan_materialized event carries approval_mode field."""
        from grace_control.services.feature_intake_service import FeatureIntakeService
        from grace_control.services.feature_planning_service import FeaturePlanningService
        from grace_control.db import get_db

        with get_db() as s:
            intake = FeatureIntakeService(s)
            result = intake.create_feature(
                title="Approval Event", mode="draft_plan",
                approval_mode="manual",
            )
            fid = result["feature_id"]

            planning = FeaturePlanningService(s)
            context = await planning.run_context_builder(fid)
            await planning.run_architect(fid, context)
            planning.approve_plan(fid)

            events = s.query(Event).filter_by(
                entity_type="feature", entity_id=fid
            ).all()
            materialized = [e for e in events if e.event_type == "plan_materialized"]
            assert len(materialized) >= 1
            payload = materialized[-1].payload_json or {}
            assert payload.get("approval_mode") == "manual"
