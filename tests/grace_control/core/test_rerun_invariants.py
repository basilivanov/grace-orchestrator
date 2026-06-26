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


def _run(packet_id="pkt_x", run_number=1, status="rejected", result_json=None, evidence_path=None):
    with get_db() as db:
        rid = f"{packet_id}-R{run_number:02d}"
        r = PacketRun(id=rid, packet_id=packet_id, run_number=run_number,
                      worker_id="wkr_t", status=status, result_json=result_json or {},
                      evidence_path=evidence_path)
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
            assert (p.spec_json or {}).get("rerun_stage") == "verifier"

    def test_consume_wrong_attempt(self):
        spec = {"rerun_stage": "verifier"}
        _pkt("pkt_m3", attempt=3, spec=spec)
        result = consume_rerun_stage("pkt_m3", "verifier", 2)
        assert result is None

    def test_marker_gone_after_consume(self):
        spec = {"rerun_stage": "verifier"}
        _pkt("pkt_m4", attempt=1, spec=spec)
        consume_rerun_stage("pkt_m4", "verifier", 1)
        result = consume_rerun_stage("pkt_m4", "verifier", 1)
        assert result is None

    def test_rerun_stage_creates_marker(self):
        _pkt("pkt_m5", attempt=2)
        rerun_stage("pkt_m5", "verifier", actor="test")
        with get_db() as db:
            p = db.query(Packet).filter_by(id="pkt_m5").first()
            assert (p.spec_json or {}).get("rerun_stage") == "verifier"
            assert p.attempt_count == 3


# ── 3. Verifier rerun chain ──────────────────────────────────────────────────

class TestVerifierRerunChain:
    def test_rerun_needs_context(self):
        _pkt("pkt_vc1", attempt=2, spec={"rerun_stage": "verifier"})
        from grace_control.services.pipeline_rerun_service import execute_rerun
        result = execute_rerun("pkt_vc1", "verifier", attempt=2)
        assert result is not None
        assert "RERUN_CONTEXT_MISSING" in (result.get("error") or result.get("reason", ""))

    def test_rerun_verifier_pass_requires_reviewer(self):
        _pkt("pkt_vc2", attempt=2, spec={"rerun_stage": "verifier"})
        _run("pkt_vc2", run_number=1, status="rejected",
             evidence_path="/tmp",
             result_json={
                 "legacy_result": {"worktree_path": "/tmp", "branch_name": "test"},
                 "acceptance_report": {"final_verdict": "rework_required", "stages": [], "summary": ""},
             })
        from grace_control.services.pipeline_rerun_service import execute_rerun
        result = execute_rerun("pkt_vc2", "verifier", attempt=2)
        assert result is not None
        assert result.get("result") == "rerun_executed"


# ── 4. Reviewer rerun ────────────────────────────────────────────────────────

class TestReviewerRerun:
    def test_reviewer_requires_verifier_pass(self):
        _pkt("pkt_rr1", attempt=1, spec={"rerun_stage": "reviewer"})
        _run("pkt_rr1", run_number=0, status="rejected",
             evidence_path="/tmp",
             result_json={
                 "legacy_result": {"worktree_path": "/tmp", "branch_name": "test"},
                 "acceptance_report": {"final_verdict": "rework_required", "stages": [], "summary": ""},
                 "evidence_verifier_report": {"verdict": "REWORK_TO_CODER", "summary": "evidence missing"},
             })
        from grace_control.services.pipeline_rerun_service import execute_rerun
        result = execute_rerun("pkt_rr1", "reviewer", attempt=1)
        assert result is not None
        err = result.get("error") or result.get("reason", "")
        assert "RERUN_VERIFIER_CONTEXT_MISSING" in err


# ── 5. Previous run context ──────────────────────────────────────────────────

class TestPrevRunContext:
    def test_uses_previous_terminal_run(self):
        from pathlib import Path
        _pkt("pkt_pr1", attempt=3)
        _run("pkt_pr1", run_number=1, status="rejected",
             evidence_path="/tmp",
             result_json={
                 "legacy_result": {"worktree_path": "/tmp", "branch_name": "test"},
                 "acceptance_report": {"final_verdict": "rework_required", "stages": [], "summary": "bad"},
             })
        _run("pkt_pr1", run_number=2, status="accepted",
             evidence_path="/tmp",
             result_json={
                 "legacy_result": {"worktree_path": "/tmp", "branch_name": "test"},
                 "acceptance_report": {"final_verdict": "accepted", "stages": [], "summary": "ok"},
             })
        from grace_control.services.rerun_context_service import load_previous_terminal_context
        ctx = load_previous_terminal_context(
            packet_id="pkt_pr1", current_run_id="pkt_pr1-R03",
        )
        assert ctx is not None
        assert ctx.acceptance_report.get("summary") == "ok"

    def test_no_previous_run(self):
        _pkt("pkt_pr2", attempt=1)
        from grace_control.services.rerun_context_service import load_previous_terminal_context
        ctx = load_previous_terminal_context(
            packet_id="pkt_pr2", current_run_id="pkt_pr2-R01",
        )
        assert ctx is None


# ── 6. Persistence ───────────────────────────────────────────────────────────

class TestRerunPersist:
    def test_persist_rerun_result(self):
        from grace_control.services.run_result_persistence_service import persist_rerun_result
        from grace_control.core.rerun_contracts import RerunResult

        _pkt("pkt_pe1", attempt=2)
        rid = "pkt_pe1-R02"
        _run("pkt_pe1", run_number=2, status="running")

        rr = RerunResult(
            accepted=False, domain_status="rejected",
            reason="rerun verifier failed", duration_ms=5000,
            acceptance_report={"final_verdict": "rejected", "summary": "verifier fail"},
        )
        persist_rerun_result(run_id=rid, packet_id="pkt_pe1", result=rr)

        with get_db() as db:
            r = db.query(PacketRun).filter_by(id=rid).first()
            assert r is not None
            assert r.status == "rejected"
            assert r.duration_ms is not None

    def test_persist_accepted(self):
        from grace_control.services.run_result_persistence_service import persist_rerun_result
        from grace_control.core.rerun_contracts import RerunResult

        _pkt("pkt_pe2", attempt=1)
        rid = "pkt_pe2-R01"
        _run("pkt_pe2", run_number=1, status="running")

        rr = RerunResult(
            accepted=True, domain_status="accepted",
            reason="rerun ok", duration_ms=3000,
            acceptance_report={"final_verdict": "accepted", "summary": "all good"},
        )
        persist_rerun_result(run_id=rid, packet_id="pkt_pe2", result=rr)

        with get_db() as db:
            r = db.query(PacketRun).filter_by(id=rid).first()
            assert r.status == "accepted"


# ── 7. Trace correlation ──────────────────────────────────────────────────────

class TestTraceCorrelation:
    def test_trace_per_run_id(self):
        _pkt("pkt_tr1", attempt=2)
        _run("pkt_tr1", run_number=1, status="rejected")
        _run("pkt_tr1", run_number=2, status="running")
        _srun("pkt_tr1", stage_key="coder", status="done",
              run_id="pkt_tr1-R01", trace_id="trc_old")
        _srun("pkt_tr1", stage_key="coder", status="running",
              run_id="pkt_tr1-R02", trace_id="trc_current")
        from grace_control.services.aggregated_logs_service import _read_worker_logs
        logs = _read_worker_logs("pkt_tr1", 10, include_stdout=True, include_stderr=False)
        assert logs == []

    def test_trace_not_mixed(self):
        _pkt("pkt_tr2", attempt=2)
        s1 = _srun("pkt_tr2", stage_key="coder", status="done",
                    run_id="pkt_tr2-R01", trace_id="trc_run1")
        s2 = _srun("pkt_tr2", stage_key="coder", status="running",
                    run_id="pkt_tr2-R02", trace_id="trc_run2")
        assert s1.trace_id == "trc_run1"
        assert s2.trace_id == "trc_run2"
        assert s1.trace_id != s2.trace_id


# ── 8. Integration: real persistence + worktree merge path ───────────────────

class TestIntegration:
    def test_persist_canonical_format(self):
        from grace_control.services.run_result_persistence_service import persist_rerun_result
        from grace_control.core.rerun_contracts import RerunResult

        _pkt("pkt_int1", attempt=2)
        rid = "pkt_int1-R02"
        _run("pkt_int1", run_number=2, status="running")

        rr = RerunResult(
            accepted=True, domain_status="accepted",
            reason="rerun ok", duration_ms=3000,
            source_run_id="pkt_int1-R01",
            worktree_path="/tmp/test_wt",
            branch_name="agent/test-branch",
            acceptance_report={
                "final_verdict": "accepted", "profile": "NORMAL",
                "stages": [], "summary": "all good",
            },
            evidence_verifier_report={"verdict": "PASS", "summary": "all good"},
            reviewer_report={"verdict": "PASS", "summary": "safe"},
        )
        persist_rerun_result(run_id=rid, packet_id="pkt_int1", result=rr)

        with get_db() as db:
            r = db.query(PacketRun).filter_by(id=rid).first()
            assert r is not None
            assert r.status == "accepted"
            rj = r.result_json or {}
            assert "evidence_verifier_report" in rj
            assert rj["evidence_verifier_report"]["verdict"] == "PASS"
            assert "reviewer_report" in rj
            assert rj["reviewer_report"]["verdict"] == "PASS"
            lr = rj.get("legacy_result", {})
            assert lr.get("worktree_path") == "/tmp/test_wt"
            assert lr.get("branch_name") == "agent/test-branch"

    def test_rerun_context_requires_worktree(self):
        from grace_control.services.rerun_context_service import load_previous_terminal_context

        _pkt("pkt_int2", attempt=2)
        _run("pkt_int2", run_number=1, status="rejected",
             result_json={
                 "legacy_result": {"worktree_path": "", "branch_name": ""},
                 "acceptance_report": {"final_verdict": "rework_required", "stages": [], "summary": ""},
             })
        ctx = load_previous_terminal_context(
            packet_id="pkt_int2", current_run_id="pkt_int2-R02",
        )
        assert ctx is None

    def test_rerun_context_missing_acceptance(self):
        from grace_control.services.rerun_context_service import load_previous_terminal_context

        _pkt("pkt_int3", attempt=2)
        _run("pkt_int3", run_number=1, status="rejected",
             result_json={
                 "legacy_result": {"worktree_path": "/tmp", "branch_name": "test"},
             })
        ctx = load_previous_terminal_context(
            packet_id="pkt_int3", current_run_id="pkt_int3-R02",
        )
        assert ctx is None

    def test_re_rerun_chain(self, tmp_path):
        from grace_control.services.run_result_persistence_service import persist_rerun_result
        from grace_control.services.rerun_context_service import load_previous_terminal_context
        from grace_control.core.rerun_contracts import RerunResult
        from pathlib import Path

        evidence_dir = tmp_path / "packets" / "pkt_chain1" / "runs" / "R02"
        assert not evidence_dir.exists()

        _pkt("pkt_chain1", attempt=2)
        _run("pkt_chain1", run_number=1, status="rejected",
             evidence_path=str(evidence_dir),
             result_json={
                 "legacy_result": {"worktree_path": str(tmp_path), "branch_name": "agent/initial"},
                 "acceptance_report": {
                     "final_verdict": "rework_required", "profile": "NORMAL",
                     "stages": [{"name": "coder", "status": "failed"}],
                     "summary": "fix it",
                 },
                 "evidence_verifier_report": {"verdict": "REWORK_TO_CODER", "summary": "bad"},
             })
        rid2 = "pkt_chain1-R02"
        _run("pkt_chain1", run_number=2, status="running")

        rr = RerunResult(
            accepted=True, domain_status="accepted",
            reason="rerun ok", duration_ms=3000,
            source_run_id="pkt_chain1-R01",
            worktree_path=str(tmp_path),
            branch_name="agent/rerun-fix",
            acceptance_report={
                "final_verdict": "rework_required", "profile": "NORMAL",
                "stages": [{"name": "coder", "status": "failed"}],
                "summary": "fix it",
            },
            evidence_verifier_report={"verdict": "PASS", "summary": "all fixed"},
            reviewer_report={"verdict": "PASS", "summary": "safe"},
        )
        persist_rerun_result(
            run_id=rid2, packet_id="pkt_chain1",
            result=rr, evidence_dir=evidence_dir,
        )

        with get_db() as db:
            r2 = db.query(PacketRun).filter_by(id=rid2).first()
            assert r2 is not None
            assert r2.evidence_path == str(evidence_dir)
            assert evidence_dir.exists()
            assert r2.status == "accepted"
            rj2 = r2.result_json or {}
            assert rj2["acceptance_report"]["final_verdict"] == "rework_required"
            assert rj2["acceptance_report"]["profile"] == "NORMAL"
            assert len(rj2["acceptance_report"]["stages"]) == 1

        rid3 = "pkt_chain1-R03"
        ctx = load_previous_terminal_context(
            packet_id="pkt_chain1", current_run_id=rid3,
        )
        assert ctx is not None
        assert ctx.acceptance_report.get("summary") == "fix it"
        assert ctx.source_worktree_path == str(tmp_path)
        assert ctx.source_run_dir == str(evidence_dir)

    def test_execution_result_has_worktree_branch(self):
        from grace_control.adapters.packet_executor import ExecutionResult
        er = ExecutionResult(
            accepted=True, domain_status="accepted",
            reason="test", duration_ms=100,
            worktree_path="/tmp/wt", branch_name="agent/test",
        )
        assert er.worktree_path == "/tmp/wt"
        assert er.branch_name == "agent/test"
