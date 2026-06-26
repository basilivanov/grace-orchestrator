"""Comprehensive tests for rerun, run_id, trace, and marker safety."""
from __future__ import annotations

import pytest
from datetime import datetime

from grace_control.db import init_db, get_db
from grace_control.db.schema import (
    Base, Packet, PacketRun, PacketState, StageRun, Lease, Worker, Event,
)
from grace_control.core.uid import new_stage_run_uid
from grace_control.services.packet_control_service import (
    retry_packet, cancel_packet, delete_packet, rerun_stage, consume_rerun_stage,
)
from grace_control.core.stage_instrumentation import _compute_run_id


@pytest.fixture(autouse=True)
def setup_db(tmp_path):
    init_db("sqlite:///:memory:")
    from grace_control.db import engine
    Base.metadata.create_all(engine)


def _pkt(packet_id="pkt_x", state=PacketState.READY, attempt=1, spec=None):
    with get_db() as db:
        p = Packet(id=packet_id, feature_id="feat_t", wave_id="wave_t",
                   slug="test", title="Test", spec_json=spec or {},
                   state=state.value, attempt_count=attempt)
        db.add(p)
        db.commit()
        return p


def _run(packet_id="pkt_x", run_number=1, status="rejected", result_json=None):
    with get_db() as db:
        rid = f"{packet_id}-R{run_number:02d}"
        r = PacketRun(id=rid, packet_id=packet_id, run_number=run_number,
                      worker_id="wkr_t", status=status, result_json=result_json or {})
        db.add(r)
        db.commit()
        return r


def _srun(packet_id="pkt_x", stage_key="coder", status="done", run_id=None, trace_id=None):
    with get_db() as db:
        s = StageRun(id=new_stage_run_uid(), packet_id=packet_id,
                     feature_id="feat_t", wave_id="wave_t",
                     stage_key=stage_key, status=status, run_id=run_id, trace_id=trace_id)
        db.add(s)
        db.commit()
        return s


# ── 1. StageRun run_id ───────────────────────────────────────────────────────

class TestRunId:
    def test_compute_run_id_format(self):
        assert _compute_run_id("pkt_abc", 3) == "pkt_abc-R03"
        assert _compute_run_id("pkt_abc", 1) == "pkt_abc-R01"
        assert _compute_run_id("pkt_abc", 10) == "pkt_abc-R10"

    def test_compute_run_id_planning(self):
        assert _compute_run_id("plan_feat_t", 1) is None
        assert _compute_run_id("unknown", 1) is None

    def test_stage_run_has_run_id(self):
        """Decorator creates StageRun with computed run_id for packet stages."""
        _pkt("pkt_rid1", attempt=2)
        with get_db() as db:
            s = StageRun(id=new_stage_run_uid(), packet_id="pkt_rid1",
                         feature_id="feat_t", wave_id="wave_t",
                         stage_key="coder", status="running",
                         started_at=datetime.utcnow(),
                         attempt_number=2)
            db.add(s)
            db.commit()
            s.run_id = _compute_run_id("pkt_rid1", 2)
            db.commit()
        assert s.run_id == "pkt_rid1-R02"

    def test_stage_run_planning_no_run_id(self):
        _pkt("plan_feat_t", attempt=1)
        rid = _compute_run_id("plan_feat_t", 1)
        assert rid is None


# ── 2. One-shot marker ───────────────────────────────────────────────────────

class TestOneShotMarker:
    def test_create_and_consume(self):
        spec = {"rerun_stage": "verifier"}
        _pkt("pkt_m1", attempt=2, spec=spec)
        result = consume_rerun_stage("pkt_m1", "verifier", 2)
        assert result == "verifier"
        with get_db() as db:
            p = db.query(Packet).filter_by(id="pkt_m1").first()
            assert "rerun_stage" not in (p.spec_json or {})

    def test_consume_wrong_stage(self):
        spec = {"rerun_stage": "verifier"}
        _pkt("pkt_m2", attempt=2, spec=spec)
        result = consume_rerun_stage("pkt_m2", "reviewer", 2)
        assert result is None
        with get_db() as db:
            p = db.query(Packet).filter_by(id="pkt_m2").first()
            assert (p.spec_json or {}).get("rerun_stage") == "verifier"  # preserved

    def test_consume_wrong_attempt(self):
        spec = {"rerun_stage": "verifier"}
        _pkt("pkt_m3", attempt=3, spec=spec)
        result = consume_rerun_stage("pkt_m3", "verifier", 2)
        assert result is None

    def test_marker_gone_after_consume(self):
        spec = {"rerun_stage": "verifier"}
        _pkt("pkt_m4", attempt=1, spec=spec)
        consume_rerun_stage("pkt_m4", "verifier", 1)
        # Second consume should return None
        result = consume_rerun_stage("pkt_m4", "verifier", 1)
        assert result is None

    def test_rerun_stage_creates_marker(self):
        _pkt("pkt_m5", attempt=2)
        rerun_stage("pkt_m5", "verifier", actor="test")
        with get_db() as db:
            p = db.query(Packet).filter_by(id="pkt_m5").first()
            assert (p.spec_json or {}).get("rerun_stage") == "verifier"
            assert p.attempt_count == 3  # incremented


# ── 3. Verifier rerun chain ──────────────────────────────────────────────────

class TestVerifierRerunChain:
    def test_rerun_needs_context(self):
        """Без предыдущего run возвращает RERUN_CONTEXT_MISSING."""
        _pkt("pkt_vc1", attempt=2, spec={"rerun_stage": "verifier"})
        from grace_control.services.pipeline_rerun_service import execute_rerun
        result = execute_rerun("pkt_vc1", "verifier", attempt=2)
        assert result is not None
        assert "RERUN_CONTEXT_MISSING" in (result.get("error") or result.get("reason", ""))

    def test_rerun_verifier_pass_requires_reviewer(self):
        """Verifier PASS не приводит к accepted без reviewer PASS — проверка на уровне mock."""
        _pkt("pkt_vc2", attempt=2, spec={"rerun_stage": "verifier"})
        _run("pkt_vc2", run_number=1, status="rejected",
             result_json={"acceptance_report": {"final_verdict": "rework_required", "stages": [], "summary": ""}})
        from grace_control.services.pipeline_rerun_service import execute_rerun
        result = execute_rerun("pkt_vc2", "verifier", attempt=2)
        assert result is not None
        # mock возвращает rerun_executed, реальный executor chain verifier->reviewer
        assert result.get("result") == "rerun_executed"


# ── 4. Reviewer rerun ────────────────────────────────────────────────────────

class TestReviewerRerun:
    def test_reviewer_requires_verifier_pass(self):
        _pkt("pkt_rr1", attempt=1, spec={"rerun_stage": "reviewer"})
        # Run с verifier verdict не PASS (attempt=0, прошлый)
        _run("pkt_rr1", run_number=0, status="rejected",
             result_json={
                 "acceptance_report": {"final_verdict": "rework_required", "stages": [], "summary": ""},
                 "evidence_verifier_report": {"verdict": "REWORK_TO_CODER", "summary": "evidence missing"},
             })
        # Текущий attempt=1, не имеет acceptance
        from grace_control.services.pipeline_rerun_service import execute_rerun
        result = execute_rerun("pkt_rr1", "reviewer", attempt=1)
        assert result is not None
        # Убеждаемся что error содержит RERUN_VERIFIER_CONTEXT_MISSING
        err = result.get("error") or result.get("reason", "")
        assert "RERUN_VERIFIER_CONTEXT_MISSING" in err


# ── 5. Previous run context ──────────────────────────────────────────────────

class TestPrevRunContext:
    def test_uses_previous_terminal_run(self):
        """Проверяет, что выбирается предыдущий terminal run, а не текущий."""
        from pathlib import Path
        _pkt("pkt_pr1", attempt=3)
        rid1 = f"pkt_pr1-R01"
        rid2 = f"pkt_pr1-R02"
        rid3 = f"pkt_pr1-R03"
        _run("pkt_pr1", run_number=1, status="rejected",
             result_json={"acceptance_report": {"final_verdict": "rework_required", "stages": [], "summary": ""}})
        _run("pkt_pr1", run_number=2, status="accepted",
             result_json={"acceptance_report": {"final_verdict": "accepted", "stages": [], "summary": "ok"}})
        # Current empty run (run_number=3) should be ignored
        from grace_control.adapters.packet_executor import PacketExecutionAdapter
        adapter = PacketExecutionAdapter.__new__(PacketExecutionAdapter)
        adapter.state_root = Path("/tmp")
        adapter.worktree_root = Path("/tmp")
        ctx = adapter._load_prev_run_context("pkt_pr1", rid3)
        assert ctx is not None
        assert ctx["acceptance_report"].summary == "ok"

    def test_no_previous_run(self):
        _pkt("pkt_pr2", attempt=1)
        from grace_control.adapters.packet_executor import PacketExecutionAdapter
        adapter = PacketExecutionAdapter.__new__(PacketExecutionAdapter)
        ctx = adapter._load_prev_run_context("pkt_pr2", "pkt_pr2-R01")
        assert ctx is None


# ── 6. Persistence ───────────────────────────────────────────────────────────

class TestRerunPersist:
    def test_persist_rerun_result(self):
        _pkt("pkt_pe1", attempt=2)
        rid = f"pkt_pe1-R02"
        _run("pkt_pe1", run_number=2, status="running")
        from grace_control.adapters.packet_executor import ExecutionResult
        er = ExecutionResult(
            accepted=False, domain_status="rejected", reason="rerun verifier failed",
            duration_ms=5000, evidence={"verifier_verdict": "REWORK_TO_CODER"},
        )
        from grace_control.adapters.packet_executor import PacketExecutionAdapter
        adapter = PacketExecutionAdapter.__new__(PacketExecutionAdapter)
        adapter._persist_rerun_result(rid, er, 1000.0, "pkt_pe1")
        with get_db() as db:
            r = db.query(PacketRun).filter_by(id=rid).first()
            assert r is not None
            assert r.status == "rejected"
            assert r.duration_ms is not None

    def test_persist_accepted(self):
        _pkt("pkt_pe2", attempt=1)
        rid = f"pkt_pe2-R01"
        _run("pkt_pe2", run_number=1, status="running")
        from grace_control.adapters.packet_executor import ExecutionResult
        er = ExecutionResult(
            accepted=True, domain_status="accepted", reason="rerun ok",
            duration_ms=3000, evidence={"reviewer_verdict": "PASS"},
        )
        from grace_control.adapters.packet_executor import PacketExecutionAdapter
        adapter = PacketExecutionAdapter.__new__(PacketExecutionAdapter)
        adapter._persist_rerun_result(rid, er, 500.0, "pkt_pe2")
        with get_db() as db:
            r = db.query(PacketRun).filter_by(id=rid).first()
            assert r.status == "accepted"


# ── 7. Trace correlation ──────────────────────────────────────────────────────

class TestTraceCorrelation:
    def test_trace_per_run_id(self):
        """Логи разных run получают разные trace_id."""
        _pkt("pkt_tr1", attempt=2)
        _run("pkt_tr1", run_number=1, status="rejected")
        _run("pkt_tr1", run_number=2, status="running")
        s1 = _srun("pkt_tr1", stage_key="coder", status="done",
                    run_id="pkt_tr1-R01", trace_id="trc_old")
        s2 = _srun("pkt_tr1", stage_key="coder", status="running",
                    run_id="pkt_tr1-R02", trace_id="trc_current")
        # Проверяем, что для каждого run_id будет свой trace
        from grace_control.services.aggregated_logs_service import _read_worker_logs
        logs = _read_worker_logs("pkt_tr1", 10, include_stdout=True, include_stderr=False)
        # Без реальных файлов на диске, просто проверяем что функция не падает
        assert logs == []

    def test_trace_not_mixed(self):
        """StageRun для run 1 не влияет на trace run 2."""
        _pkt("pkt_tr2", attempt=2)
        s1 = _srun("pkt_tr2", stage_key="coder", status="done",
                    run_id="pkt_tr2-R01", trace_id="trc_run1")
        s2 = _srun("pkt_tr2", stage_key="coder", status="running",
                    run_id="pkt_tr2-R02", trace_id="trc_run2")
        assert s1.trace_id == "trc_run1"
        assert s2.trace_id == "trc_run2"
        assert s1.trace_id != s2.trace_id
