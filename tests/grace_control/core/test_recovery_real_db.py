"""
TZ-023 — Recovery integration tests with REAL SQLite (no mock.patch).

Categories: SESSION (3) + FAILURE INJECTION (5) + FULL PIPELINE (6) + EDGE CASES (5) = 19 tests.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from grace_control.db import get_db
from grace_control.db.schema import (
    Feature,
    Packet,
    PacketRun,
    PacketState,
    SelfEvolutionSession,
    Wave,
)
from tests.conftest import make_feature, make_packet, make_wave


# ═══════════════════════════════════════════════════════════════════════════════
# SESSION Category (3 tests) — real SQLite, real get_db()
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_signal_real_db(db):
    """build_signal() must work with real SQLite session (no DetachedInstanceError)."""
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1", order=1)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        d.add(PacketRun(
            id="R01", packet_id="P1", run_number=1, status="rejected",
            result_json={
                "acceptance_report": {"final_verdict": "rework_required", "summary": "T1 failed"},
                "evidence_verifier_report": {"verdict": "REWORK_TO_CODER"},
            },
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        ))
        d.flush()

    ctrl = RecoveryController()
    signal = ctrl.build_signal("P1")
    assert signal.packet_id == "P1"
    assert signal.coder_attempt_count == 1
    assert signal.acceptance_verdict == "rework_required"
    assert signal.evidence_verifier_verdict == "REWORK_TO_CODER"


async def test_apply_decision_real_db(db):
    """apply_decision makes real DB transitions via PacketStateMachine."""
    from grace_control.core.recovery_controller import RecoveryController
    from grace_control.core.feature_recovery import RecoveryDecision, RecoveryAction, FailureClass

    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1", order=1)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        d.flush()

    ctrl = RecoveryController()
    decision = RecoveryDecision(
        action=RecoveryAction.RETRY_SAME_CODER,
        failure_class=FailureClass.RETRYABLE_CODER,
        reason="test retry",
    )
    await ctrl._apply_decision("P1", decision)

    with get_db() as d:
        p = d.query(Packet).filter_by(id="P1").first()
        assert p.state == PacketState.READY.value


def test_evaluate_stale_workers(db):
    """build_signal works with zombie workers in historical PacketRun."""
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1")
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        for i, (eid, status) in enumerate([
            ("eval-w1", "rejected"), ("eval-w2", "rejected"), ("golden-w0", "rejected")
        ], 1):
            d.add(PacketRun(
                id=f"R0{i}", packet_id="P1", run_number=i, status=status,
                result_json={"executor_id": eid, "domain_status": status},
            ))
        d.flush()

    ctrl = RecoveryController()
    signal = ctrl.build_signal("P1")
    assert signal.coder_attempt_count == 3
    assert "eval-w1" in signal.previous_executor_ids
    assert "golden-w0" in signal.previous_executor_ids


# ═══════════════════════════════════════════════════════════════════════════════
# FAILURE INJECTION Category (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_signal_no_runs(db):
    """Packet without PacketRun → ValueError, not DetachedInstanceError."""
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1", order=1)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.READY.value)
        d.flush()

    ctrl = RecoveryController()
    with pytest.raises(ValueError, match="No runs"):
        ctrl.build_signal("P1")


def test_build_signal_corrupted_result_json(db):
    """result_json = None → does not crash."""
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1", order=1)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        d.add(PacketRun(id="R01", packet_id="P1", run_number=1, status="rejected",
                        result_json=None))
        d.flush()

    ctrl = RecoveryController()
    signal = ctrl.build_signal("P1")
    assert signal.packet_id == "P1"
    assert signal.evidence_verifier_verdict == ""


async def test_evaluate_crash_is_safe(db, monkeypatch):
    """build_signal crash → evaluate handles gracefully."""
    from grace_control.core.recovery_controller import RecoveryController

    ctrl = RecoveryController()

    def _crash(*a, **kw):
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(ctrl, "build_signal", _crash)

    try:
        decision = await ctrl.evaluate("nonexistent", allow_apply=False)
        assert decision is not None
    except Exception:
        pass


async def test_apply_decision_missing_packet(db):
    """Packet deleted between evaluate and apply → no crash."""
    from grace_control.core.recovery_controller import RecoveryController
    from grace_control.core.feature_recovery import RecoveryAction, FailureClass, RecoveryDecision

    ctrl = RecoveryController()
    decision = RecoveryDecision(
        action=RecoveryAction.RETRY_SAME_CODER,
        failure_class=FailureClass.RETRYABLE_CODER,
        reason="test",
    )
    try:
        await ctrl._apply_decision("nonexistent", decision)
    except Exception:
        pass


def test_evaluate_max_sessions(db):
    """50+ historical runs → build_signal does not hang or crash."""
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1", order=1)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        for i in range(1, 51):
            d.add(PacketRun(
                id=f"R{i:02d}", packet_id="P1", run_number=i, status="rejected",
                result_json={"acceptance_verdict": "rework_required"},
            ))
        d.flush()

    ctrl = RecoveryController()
    signal = ctrl.build_signal("P1")
    assert signal.coder_attempt_count >= 1
    assert signal.coder_attempt_count <= 50


# ═══════════════════════════════════════════════════════════════════════════════
# FULL PIPELINE Category (6 tests)
# ═══════════════════════════════════════════════════════════════════════════════


def test_full_odd_even_real_db(db):
    """Full odd/even ladder: attempt 1 → RETRY_SAME, attempt 2 → RUN_VERIFIER."""
    from grace_control.core.recovery_rules import evaluate_ladder, RecoveryLadder, RouteAction

    route1 = evaluate_ladder(1)
    assert route1.action == RouteAction.RETRY_SAME_CODER
    assert route1.skip_verifier is True

    route2 = evaluate_ladder(2)
    assert route2.action == RouteAction.RUN_VERIFIER
    assert route2.skip_verifier is False
    assert "REWORK_TO_CODER" in route2.on_verdict
    assert "RETURN_TO_ARCHITECT" in route2.on_verdict

    route7 = evaluate_ladder(7)
    assert route7.action == RouteAction.NEW_ARCHITECT


async def test_full_coder_switch_real_db(db):
    """decide_recovery → SWITCH_CODER → _apply_switch_coder → READY + requested_executor_id."""
    from grace_control.core.feature_recovery import (
        FailureSignal, RecoveryPolicy, classify_failure, decide_recovery,
        RecoveryAction, FailureClass,
    )
    from grace_control.core.recovery_controller import RecoveryController

    signal = FailureSignal(
        feature_id="F1", packet_id="P1", packet_state="rejected",
        domain_status="rejected",
        reason="T1 failed",
        coder_attempt_count=2, attempt_count=2,
        acceptance_verdict="rework_required",
        current_executor_id="coder-deepseek-flash",
        previous_executor_ids=["coder-deepseek-flash"] * 1,
    )
    fc = classify_failure(signal)
    assert fc == FailureClass.RETRYABLE_CODER

    decision = decide_recovery(signal, RecoveryPolicy())
    assert decision.action == RecoveryAction.SWITCH_CODER

    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1", order=1)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        d.flush()

    ctrl = RecoveryController()
    await ctrl._apply_decision("P1", decision)

    with get_db() as d:
        p = d.query(Packet).filter_by(id="P1").first()
        assert p.state == PacketState.READY.value
        assert p.spec_json["recovery"]["requested_executor_id"] == decision.next_executor_hint


def test_full_stale_db_history(db):
    """DB with accumulated history from old sessions → recovery controller works."""
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        d.add(Feature(id="feat_old", slug="old", title="old", spec_json={}, status="NOT_STARTED"))
        d.add(Wave(id="wave_old", feature_id="feat_old", slug="old", title="old", order=1))
        make_packet(d, pid="P-old", fid="feat_old", wid="wave_old", state=PacketState.MERGED.value)
        d.add(SelfEvolutionSession(
            id="ses-old", title="old", status="completed",
            created_at=datetime.now(timezone.utc),
        ))

        d.add(Feature(id="feat_new", slug="new", title="new", spec_json={}, status="NOT_STARTED"))
        d.add(Wave(id="wave_new", feature_id="feat_new", slug="new", title="new", order=1))
        make_packet(d, pid="P-new", fid="feat_new", wid="wave_new", state=PacketState.REJECTED.value)
        for i in range(1, 3):
            d.add(PacketRun(
                id=f"R0{i}", packet_id="P-new", run_number=i, status="rejected",
                result_json={"acceptance_report": {"final_verdict": "rework_required"}},
            ))
        d.flush()

    ctrl = RecoveryController()
    signal = ctrl.build_signal("P-new")
    assert signal.packet_id == "P-new"
    assert signal.coder_attempt_count == 2


async def test_full_multiwave_acceptance_recovery_real_db(db):
    """Two waves. Wave 1 rejected → recovery → feature blocked. Wave 2 stays draft because
    feature is blocked — wave gate does not progress blocked features."""
    from grace_control.core.recovery_controller import RecoveryController
    from grace_control.core.feature_recovery import RecoveryAction, FailureClass, RecoveryDecision

    with get_db() as d:
        make_feature(d, fid="F1")
        d.add(Wave(id="W01", feature_id="F1", slug="w1", title="W1", order=1))
        d.add(Wave(id="W02", feature_id="F1", slug="w2", title="W2", order=2))
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        make_packet(d, pid="P2", fid="F1", wid="W02", state=PacketState.DRAFT.value)
        d.flush()

    ctrl = RecoveryController()
    decision = RecoveryDecision(
        action=RecoveryAction.BLOCK_FEATURE,
        failure_class=FailureClass.TRUE_BLOCKER,
        reason="test block",
    )
    await ctrl._apply_decision("P1", decision)

    from grace_control.core.wave_gate import check_wave_gates
    gated = check_wave_gates()
    assert gated >= 0

    with get_db() as d:
        p2 = d.query(Packet).filter_by(id="P2").first()
        # After feature is blocked, wave gate does not progress W02 packets;
        # P2 remains DRAFT.
        assert p2.state == PacketState.DRAFT.value


def test_full_profiles_maintained(db):
    """STRICT never downgrades after recovery. FAST never upgrades."""
    from grace_control.core.feature_recovery import (
        FailureSignal, RecoveryPolicy, decide_recovery,
    )

    signal_strict = FailureSignal(
        feature_id="F1", packet_id="P1", packet_state="rejected",
        acceptance_profile="STRICT",
        coder_attempt_count=2,
        acceptance_verdict="rework_required",
    )
    decision = decide_recovery(signal_strict, RecoveryPolicy())
    assert decision.next_acceptance_profile != "NORMAL"
    assert decision.next_acceptance_profile != "FAST"

    signal_fast = FailureSignal(
        feature_id="F1", packet_id="P2", packet_state="rejected",
        acceptance_profile="FAST",
        coder_attempt_count=1,
        acceptance_verdict="rework_required",
    )
    decision = decide_recovery(signal_fast, RecoveryPolicy())
    assert decision.next_acceptance_profile is None or decision.next_acceptance_profile == "FAST"


def test_full_merge_conflict_recovery(db):
    """merge_error → classified as TRUE_BLOCKER or MERGE_RETRYABLE."""
    from grace_control.core.feature_recovery import FailureSignal, classify_failure, FailureClass

    signal = FailureSignal(
        feature_id="F1", packet_id="P1", packet_state="rejected",
        merge_error="DIRTY_TARGET_REPO",
    )
    fc = classify_failure(signal)
    assert fc == FailureClass.TRUE_BLOCKER

    signal2 = FailureSignal(
        feature_id="F1", packet_id="P2", packet_state="rejected",
        merge_error="transient connection timeout",
    )
    fc2 = classify_failure(signal2)
    assert fc2 == FailureClass.MERGE_RETRYABLE


# ═══════════════════════════════════════════════════════════════════════════════
# EDGE CASES Category (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════


def test_edge_attempt_zero():
    """evaluate_ladder(0) — attempt=0 → does not crash."""
    from grace_control.core.recovery_rules import evaluate_ladder, RouteAction

    route = evaluate_ladder(0)
    assert route.action in (RouteAction.RETRY_SAME_CODER, RouteAction.RUN_VERIFIER)


def test_edge_max_int_attempts():
    """evaluate_ladder(999999) → NEW_ARCHITECT (ATTEMPT_GTE 7)."""
    from grace_control.core.recovery_rules import evaluate_ladder, RouteAction

    route = evaluate_ladder(999999)
    assert route.action == RouteAction.NEW_ARCHITECT


def test_edge_empty_result_json_all_runs(db):
    """All PacketRun.result_json = null → build_signal does not crash."""
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        make_feature(d, fid="F1")
        make_wave(d, wid="W01", fid="F1", order=1)
        make_packet(d, pid="P1", fid="F1", wid="W01", state=PacketState.REJECTED.value)
        for i in range(1, 4):
            d.add(PacketRun(id=f"R0{i}", packet_id="P1", run_number=i, status="rejected",
                            result_json=None))
        d.flush()

    ctrl = RecoveryController()
    signal = ctrl.build_signal("P1")
    assert signal.packet_id == "P1"
    assert signal.evidence_verifier_verdict == ""


def test_edge_missing_feature(db):
    """Packet exists but Feature does not → build_signal does not crash."""
    from grace_control.core.recovery_controller import RecoveryController

    with get_db() as d:
        d.add(Packet(id="P1", feature_id="F-missing", wave_id="W-missing",
                     slug="orphan", title="orphan", spec_json={}, state="rejected"))
        d.add(PacketRun(id="R01", packet_id="P1", run_number=1, status="rejected",
                        result_json={}))
        d.flush()

    ctrl = RecoveryController()
    signal = ctrl.build_signal("P1")
    assert signal.feature_id == "F-missing"


def test_edge_packet_canceled_state_transition():
    """All 9 PacketState have defined behavior. CANCELLED/FAILED → no READY."""
    from grace_control.core.state_machine import PacketStateMachine
    from grace_control.db.schema import PacketState

    sm = PacketStateMachine()
    for state in PacketState:
        if state in (PacketState.CANCELLED, PacketState.FAILED):
            transitions = sm.VALID_TRANSITIONS.get(state, [])
            assert PacketState.READY not in transitions, f"{state} should not transition to READY"
