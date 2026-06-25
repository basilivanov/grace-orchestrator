"""Integration tests for packet control actions (retry, cancel, delete)."""
from __future__ import annotations

import pytest
from datetime import datetime

from grace_control.db import init_db, get_db
from grace_control.db.schema import (
    Base, Packet, PacketRun, PacketState, StageRun, Lease, Worker, Event,
)
from grace_control.services.packet_control_service import (
    retry_packet, cancel_packet, delete_packet, rerun_stage, stop_worker,
)


@pytest.fixture(autouse=True)
def setup_db(tmp_path):
    init_db("sqlite:///:memory:")
    from grace_control.db import engine
    Base.metadata.create_all(engine)


def _create_packet(packet_id="pkt_test", state=PacketState.READY, attempt_count=1):
    with get_db() as db:
        p = Packet(
            id=packet_id, feature_id="feat_t", wave_id="wave_t",
            slug="test", title="Test", spec_json={}, state=state.value,
            attempt_count=attempt_count,
        )
        db.add(p)
        db.commit()
        return p


def _create_run(packet_id="pkt_test", run_number=1):
    with get_db() as db:
        r = PacketRun(
            id=f"{packet_id}-R{run_number:02d}", packet_id=packet_id,
            run_number=run_number, worker_id="wkr_t", status="failed",
        )
        db.add(r)
        db.commit()
        return r


def _create_lease(packet_id="pkt_test", worker_id="wkr_t"):
    with get_db() as db:
        l = Lease(
            packet_id=packet_id, worker_id=worker_id,
            claimed_attempt=1, expires_at=datetime.utcnow(),
        )
        db.add(l)
        db.commit()
        return l


class TestRetry:
    def test_retry_blocked_recoverable(self):
        _create_packet("pkt_r1", PacketState.BLOCKED_RECOVERABLE)
        result = retry_packet("pkt_r1", actor="test")
        assert result["ok"] is True
        assert result["state"] == PacketState.READY.value
        with get_db() as db:
            p = db.query(Packet).filter_by(id="pkt_r1").first()
            assert p.state == PacketState.READY.value
            assert p.attempt_count == 2  # incremented from 1

    def test_retry_rejected(self):
        _create_packet("pkt_r2", PacketState.REJECTED)
        retry_packet("pkt_r2")
        with get_db() as db:
            p = db.query(Packet).filter_by(id="pkt_r2").first()
            assert p.state == PacketState.READY.value

    def test_retry_invalid_state(self):
        _create_packet("pkt_r3", PacketState.RUNNING)
        with pytest.raises(ValueError, match="Cannot retry"):
            retry_packet("pkt_r3")

    def test_retry_creates_audit_event(self):
        _create_packet("pkt_r4", PacketState.BLOCKED_RECOVERABLE)
        retry_packet("pkt_r4", actor="admin", reason="manual_retry")
        with get_db() as db:
            ev = db.query(Event).filter_by(entity_id="pkt_r4").first()
            assert ev is not None
            assert "manual_retry" in str(ev.payload_json)


class TestCancel:
    def test_cancel_running(self):
        _create_packet("pkt_c1", PacketState.RUNNING)
        _create_lease("pkt_c1", "wkr_c1")
        result = cancel_packet("pkt_c1", actor="test")
        assert result["ok"] is True
        assert result["state"] == PacketState.CANCELLED.value
        with get_db() as db:
            p = db.query(Packet).filter_by(id="pkt_c1").first()
            assert p.state == PacketState.CANCELLED.value
            # lease deleted
            assert db.query(Lease).filter_by(packet_id="pkt_c1").first() is None

    def test_cancel_not_running(self):
        _create_packet("pkt_c2", PacketState.READY)
        with pytest.raises(ValueError, match="Cannot cancel"):
            cancel_packet("pkt_c2")

    def test_cancel_creates_event(self):
        _create_packet("pkt_c3", PacketState.RUNNING)
        _create_lease("pkt_c3")
        cancel_packet("pkt_c3", actor="admin", reason="stuck")
        with get_db() as db:
            ev = db.query(Event).filter_by(
                entity_id="pkt_c3", event_type="packet_transition"
            ).first()
            assert ev is not None
            assert "stuck" in str(ev.payload_json)


class TestDelete:
    def test_delete_requires_confirm(self):
        _create_packet("pkt_d1")
        with pytest.raises(ValueError, match="confirm"):
            delete_packet("pkt_d1", confirm="wrong")

    def test_delete_packet_and_runs(self):
        _create_packet("pkt_d2")
        _create_run("pkt_d2", 1)
        with get_db() as db:
            assert db.query(Packet).filter_by(id="pkt_d2").first() is not None
            assert db.query(PacketRun).filter_by(packet_id="pkt_d2").first() is not None
        delete_packet("pkt_d2", confirm="pkt_d2")
        with get_db() as db:
            assert db.query(Packet).filter_by(id="pkt_d2").first() is None
            assert db.query(PacketRun).filter_by(packet_id="pkt_d2").first() is None

    def test_delete_creates_event(self):
        _create_packet("pkt_d3")
        _create_run("pkt_d3", 1)
        delete_packet("pkt_d3", confirm="pkt_d3", actor="admin")
        with get_db() as db:
            ev = db.query(Event).filter_by(
                entity_id="pkt_d3", event_type="admin_action"
            ).first()
            assert ev is not None
            assert "delete" in str(ev.payload_json)


class TestRerunStage:
    def test_rerun_verifier(self):
        _create_packet("pkt_v1", PacketState.RUNNING)
        result = rerun_stage("pkt_v1", "verifier", actor="test")
        assert result["ok"] is True
        with get_db() as db:
            srun = db.query(StageRun).filter_by(
                packet_id="pkt_v1", stage_key="verifier", status="pending"
            ).first()
            assert srun is not None
            assert srun.recovery_reason is not None

    def test_rerun_reviewer(self):
        _create_packet("pkt_v2", PacketState.RUNNING)
        result = rerun_stage("pkt_v2", "reviewer", actor="test")
        assert result["ok"] is True

    def test_rerun_coder_allowed(self):
        """rerun_stage для coder работает и создаёт pending StageRun (проверка API-слоя отдельно)."""
        _create_packet("pkt_v3", PacketState.RUNNING)
        result = rerun_stage("pkt_v3", "coder", actor="test")
        assert result["ok"] is True
        with get_db() as db:
            srun = db.query(StageRun).filter_by(
                packet_id="pkt_v3", stage_key="coder", status="pending"
            ).first()
            assert srun is not None


class TestPipelineEndpoints:
    def test_pipeline_detail(self):
        from grace_control.services.admin_aggregation_service import AdminAggregationService
        svc = AdminAggregationService()
        _create_packet("pkt_p1")
        with get_db() as db:
            detail = svc.get_packet_detail(db, "pkt_p1")
            assert detail is not None
            assert detail.get("stages") is not None
            assert detail.get("recovery_chain") is not None
            assert detail.get("totals") is not None

    def test_stages_reference(self):
        from grace_control.services.stage_metrics_service import get_all_stages_reference
        ref = get_all_stages_reference()
        assert len(ref["stages"]) == 12
        keys = [s["key"] for s in ref["stages"]]
        assert "context_builder" in keys
        assert "coder" in keys
        assert "verifier" in keys
        assert "merge" in keys
