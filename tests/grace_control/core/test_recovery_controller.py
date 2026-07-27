"""Tests for Phase 3 RecoveryController (no real DB/git/LLMs)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from grace_control.core.recovery_controller import RecoveryController
from grace_control.core.feature_recovery import (
    FailureClass,
    FailureSignal,
    RecoveryAction,
    RecoveryDecision,
    RecoveryPolicy,
    classify_failure,
    decide_recovery,
)


# ── build_signal tests (mocked DB) ───────────────────────────────────────────


class MockPacket:
    id = "pkt_test"
    feature_id = "feat_test"
    state = "rejected"
    acceptance_profile = "NORMAL"
    attempt_count = 2


class MockRun:
    def __init__(self, status="rejected", run_number=1, result_json=None):
        self.status = status
        self.run_number = run_number
        self.result_json = result_json or {}


def test_build_signal_from_latest_run():
    runs = [
        MockRun("rejected", 2, {
            "executor_id": "coder-flash",
            "legacy_result": {"domain_status": "rejected"},
            "acceptance_report": {"final_verdict": "rework_required"},
            "reason": "T1 failed",
        }),
        MockRun("rejected", 1, {"executor_id": "coder-flash"}),
    ]

    with patch("grace_control.db.get_db") as mock_db:
        mock_ctx = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_ctx
        mock_query = MagicMock()
        mock_ctx.query.return_value = mock_query

        mock_filter_packet = MagicMock()
        mock_filter_run = MagicMock()
        mock_query.filter_by.side_effect = [mock_filter_packet, mock_filter_run]

        mock_filter_packet.first.return_value = MockPacket

        mock_order = MagicMock()
        mock_filter_run.order_by.return_value = mock_order
        mock_order.limit.return_value = MagicMock()
        mock_order.limit.return_value.all.return_value = runs

        ctrl = RecoveryController()
        signal = ctrl.build_signal("pkt_test")

    assert signal.packet_id == "pkt_test"
    assert signal.feature_id == "feat_test"
    assert signal.coder_attempt_count == 2
    assert signal.current_executor_id == "coder-flash"


def test_build_signal_counts_previous_attempts():
    runs = [
        MockRun("rejected", 3, {"executor_id": "coder-flash", "domain_status": "rejected"}),
        MockRun("failed", 2, {"executor_id": "coder-flash", "domain_status": "rejected"}),
        MockRun("rejected", 1, {"executor_id": "coder-sonnet", "domain_status": "rejected"}),
    ]

    with patch("grace_control.db.get_db") as mock_db:
        mock_ctx = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_ctx
        mock_query = MagicMock()
        mock_ctx.query.return_value = mock_query

        mock_filter_packet = MagicMock()
        mock_filter_run = MagicMock()
        mock_query.filter_by.side_effect = [mock_filter_packet, mock_filter_run]

        mock_filter_packet.first.return_value = MockPacket

        mock_order = MagicMock()
        mock_filter_run.order_by.return_value = mock_order
        mock_order.limit.return_value = MagicMock()
        mock_order.limit.return_value.all.return_value = runs

        ctrl = RecoveryController()
        signal = ctrl.build_signal("pkt_test")

    assert signal.coder_attempt_count == 3
    assert len(signal.previous_executor_ids) == 3


def test_build_signal_preserves_blocked_reviewer_context():
    runs = [
        MockRun("blocked", 1, {
            "legacy_result": {
                "domain_status": "blocked",
                "evidence": {"executor_id": "coder-mini-swe"},
            },
            "acceptance_report": {"final_verdict": "accepted"},
            "evidence_verifier_report": {"verdict": "PASS"},
            "reviewer_report": {
                "verdict": "RETURN_TO_ARCHITECT",
                "summary": "Packet scope freezes required production behavior.",
            },
        }),
    ]

    with patch("grace_control.db.get_db") as mock_db:
        mock_ctx = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_ctx
        mock_query = MagicMock()
        mock_ctx.query.return_value = mock_query

        mock_filter_packet = MagicMock()
        mock_filter_run = MagicMock()
        mock_query.filter_by.side_effect = [mock_filter_packet, mock_filter_run]
        mock_filter_packet.first.return_value = MockPacket

        mock_order = MagicMock()
        mock_filter_run.order_by.return_value = mock_order
        mock_order.limit.return_value = MagicMock()
        mock_order.limit.return_value.all.return_value = runs

        signal = RecoveryController().build_signal("pkt_test")

    assert signal.coder_attempt_count == 1
    assert signal.current_executor_id == "coder-mini-swe"
    assert signal.reason == "Packet scope freezes required production behavior."
    assert signal.reviewer_verdict == "RETURN_TO_ARCHITECT"


def test_build_signal_keeps_unresolved_reviewer_context_across_retry():
    runs = [
        MockRun("rejected", 2, {
            "reason": "Worktree disappeared during the later coder retry.",
            "legacy_result": {
                "domain_status": "rejected",
                "evidence": {"executor_id": "coder-deepseek"},
            },
            "acceptance_report": {"final_verdict": "rejected"},
            "evidence_verifier_report": {
                "verdict": "REWORK_TO_CODER",
                "summary": "Agent changed a production file outside scope.",
            },
            "reviewer_report": {
                "verdict": "REWORK_TO_CODER",
                "summary": "Agent changed a production file outside scope.",
            },
        }),
        MockRun("blocked", 1, {
            "legacy_result": {
                "domain_status": "blocked",
                "evidence": {"executor_id": "coder-flash"},
            },
            "acceptance_report": {"final_verdict": "accepted"},
            "evidence_verifier_report": {"verdict": "PASS"},
            "reviewer_report": {
                "verdict": "RETURN_TO_ARCHITECT",
                "summary": "Production scope must be expanded.",
            },
        }),
    ]

    with patch("grace_control.db.get_db") as mock_db:
        mock_ctx = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_ctx
        mock_query = MagicMock()
        mock_ctx.query.return_value = mock_query
        mock_filter_packet = MagicMock()
        mock_filter_run = MagicMock()
        mock_query.filter_by.side_effect = [mock_filter_packet, mock_filter_run]
        mock_filter_packet.first.return_value = MockPacket
        mock_order = MagicMock()
        mock_filter_run.order_by.return_value = mock_order
        mock_order.limit.return_value = MagicMock()
        mock_order.limit.return_value.all.return_value = runs

        signal = RecoveryController().build_signal("pkt_test")

    assert signal.coder_attempt_count == 2
    assert signal.current_executor_id == "coder-deepseek"
    assert signal.evidence_verifier_verdict == "REWORK_TO_CODER"
    assert signal.reviewer_verdict == "RETURN_TO_ARCHITECT"
    assert signal.reason == "Production scope must be expanded."


def test_build_signal_latest_reviewer_pass_supersedes_historical_return():
    runs = [
        MockRun("blocked", 2, {
            "legacy_result": {
                "domain_status": "completed",
                "evidence": {"executor_id": "coder-deepseek"},
            },
            "acceptance_report": {"final_verdict": "accepted"},
            "evidence_verifier_report": {"verdict": "PASS"},
            "reviewer_report": {
                "verdict": "PASS",
                "summary": "Expanded architect-approved scope is now correct.",
            },
        }),
        MockRun("blocked", 1, {
            "legacy_result": {
                "domain_status": "blocked",
                "evidence": {"executor_id": "coder-flash"},
            },
            "acceptance_report": {"final_verdict": "accepted"},
            "evidence_verifier_report": {"verdict": "PASS"},
            "reviewer_report": {
                "verdict": "RETURN_TO_ARCHITECT",
                "summary": "Production scope must be expanded.",
            },
        }),
    ]

    with patch("grace_control.db.get_db") as mock_db:
        mock_ctx = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_ctx
        mock_query = MagicMock()
        mock_ctx.query.return_value = mock_query
        mock_filter_packet = MagicMock()
        mock_filter_run = MagicMock()
        mock_query.filter_by.side_effect = [mock_filter_packet, mock_filter_run]
        mock_filter_packet.first.return_value = MockPacket
        mock_order = MagicMock()
        mock_filter_run.order_by.return_value = mock_order
        mock_order.limit.return_value = MagicMock()
        mock_order.limit.return_value.all.return_value = runs

        signal = RecoveryController().build_signal("pkt_test")

    assert signal.reviewer_verdict == "PASS"
    assert signal.reason == "Expanded architect-approved scope is now correct."


# ── evaluate tests (async) ───────────────────────────────────────────────────


async def test_evaluate_retry_same_coder():
    ctrl = RecoveryController()
    signal = FailureSignal(
        packet_id="pkt_test", feature_id="feat_test", packet_state="rejected",
        domain_status="rejected", reason="T1 failed", coder_attempt_count=0,
        current_executor_id="coder-flash",
    )
    with patch.object(ctrl, "build_signal", return_value=signal):
        with patch.object(ctrl, "_persist_decision", return_value="recd_001"):
            with patch.object(ctrl, "_emit_recovery_events"):
                with patch.object(ctrl, "_apply_decision"):
                    decision = await ctrl.evaluate("pkt_test", allow_apply=False)

    assert decision.action == RecoveryAction.RETRY_SAME_CODER
    assert decision.failure_class == FailureClass.RETRYABLE_CODER


async def test_evaluate_switch_coder():
    ctrl = RecoveryController()
    signal = FailureSignal(
        packet_id="pkt_test", feature_id="feat_test", packet_state="rejected",
        domain_status="rejected", reason="T1 failed", coder_attempt_count=2,
        current_executor_id="coder-flash",
        previous_executor_ids=["coder-flash", "coder-flash"],
    )
    with patch.object(ctrl, "build_signal", return_value=signal):
        with patch.object(ctrl, "_persist_decision", return_value="recd_001"):
            with patch.object(ctrl, "_emit_recovery_events"):
                decision = await ctrl.evaluate("pkt_test", allow_apply=False)

    assert decision.action == RecoveryAction.SWITCH_CODER
    assert decision.next_executor_hint is not None


async def test_evaluate_return_architect():
    ctrl = RecoveryController()
    signal = FailureSignal(
        packet_id="pkt_test", feature_id="feat_test", packet_state="rejected",
        domain_status="rejected", reason="T1 failed", coder_attempt_count=5,
        current_executor_id="coder-flash",
    )
    with patch.object(ctrl, "build_signal", return_value=signal):
        with patch.object(ctrl, "_persist_decision", return_value="recd_001"):
            with patch.object(ctrl, "_emit_recovery_events"):
                decision = await ctrl.evaluate("pkt_test", allow_apply=False)

    assert decision.action == RecoveryAction.RETURN_TO_ARCHITECT
    assert decision.max_attempts_reached is True


async def test_evaluate_true_blocker():
    ctrl = RecoveryController()
    signal = FailureSignal(
        packet_id="pkt_test", feature_id="feat_test", packet_state="accepted",
        domain_status="accepted", reason="", merge_error="DIRTY_TARGET_REPO",
    )
    with patch.object(ctrl, "build_signal", return_value=signal):
        with patch.object(ctrl, "_persist_decision", return_value="recd_001"):
            with patch.object(ctrl, "_emit_recovery_events"):
                decision = await ctrl.evaluate("pkt_test", allow_apply=False)

    assert decision.action == RecoveryAction.BLOCK_FEATURE
    assert decision.max_attempts_reached is True


# ── apply action tests ───────────────────────────────────────────────────────


def test_apply_retry_same_coder_sets_READY():
    ctrl = RecoveryController()
    mock_packet = MagicMock()
    mock_packet.id = "pkt_test"
    mock_packet.state = "rejected"
    mock_packet.spec_json = {}
    mock_packet.attempt_count = 2
    mock_packet.max_attempts = 2

    with patch("grace_control.db.get_db") as mock_db:
        mock_ctx = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_ctx
        mock_query = MagicMock()
        mock_ctx.query.return_value = mock_query
        mock_query.filter_by.return_value = mock_query
        mock_query.first.return_value = mock_packet

        ctrl._apply_retry_same_coder("pkt_test")

    assert mock_packet.state == "ready"
    assert mock_packet.max_attempts == 3


def test_apply_switch_coder_stores_requested_executor():
    ctrl = RecoveryController()
    mock_packet = MagicMock()
    mock_packet.id = "pkt_test"
    mock_packet.state = "rejected"
    mock_packet.spec_json = {}
    mock_packet.attempt_count = 3
    mock_packet.max_attempts = 3

    decision = RecoveryDecision(
        action=RecoveryAction.SWITCH_CODER,
        failure_class=FailureClass.RETRYABLE_CODER,
        reason="switch",
        next_executor_hint="coder-sonnet",
    )

    with patch("grace_control.db.get_db") as mock_db:
        mock_ctx = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_ctx
        mock_query = MagicMock()
        mock_ctx.query.return_value = mock_query
        mock_query.filter_by.return_value = mock_query
        mock_query.first.return_value = mock_packet

        ctrl._apply_switch_coder("pkt_test", decision)

    assert mock_packet.spec_json.get("recovery", {}).get("requested_executor_id") == "coder-sonnet"
    assert mock_packet.max_attempts == 4


def test_apply_return_architect_sets_BLOCKED():
    ctrl = RecoveryController()
    mock_packet = MagicMock()
    mock_packet.id = "pkt_test"
    mock_packet.state = "rejected"
    mock_packet.spec_json = {}

    decision = RecoveryDecision(
        action=RecoveryAction.RETURN_TO_ARCHITECT,
        failure_class=FailureClass.ARCHITECT_REPACK_NEEDED,
        reason="scope impossible",
        architect_instruction="repack the packet",
    )

    with patch("grace_control.db.get_db") as mock_db:
        mock_ctx = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_ctx
        mock_query = MagicMock()
        mock_ctx.query.return_value = mock_query
        mock_query.filter_by.return_value = mock_query
        mock_query.first.return_value = mock_packet

        ctrl._apply_return_to_architect("pkt_test", decision)

    assert mock_packet.state == "blocked_final"
    assert mock_packet.spec_json.get("architect_repair", {}).get("reason") == "scope impossible"


def test_apply_block_feature_blocks_packet():
    ctrl = RecoveryController()
    mock_packet = MagicMock()
    mock_packet.id = "pkt_test"
    mock_packet.feature_id = "feat_test"
    mock_packet.state = "rejected"
    mock_packet.spec_json = {}

    mock_feature = MagicMock()

    decision = RecoveryDecision(
        action=RecoveryAction.BLOCK_FEATURE,
        failure_class=FailureClass.TRUE_BLOCKER,
        reason="dirty target repo",
    )

    with patch("grace_control.db.get_db") as mock_db:
        mock_ctx = MagicMock()
        mock_db.return_value.__enter__.return_value = mock_ctx
        mock_query = MagicMock()
        mock_ctx.query.return_value = mock_query
        mock_query.filter_by.return_value = mock_query
        mock_query.first.side_effect = [mock_packet, mock_feature]

        ctrl._apply_block_feature("pkt_test", decision)

    assert mock_packet.state == "blocked_final"


# ── feature flag tests ───────────────────────────────────────────────────────


def test_controller_disabled_by_default():
    if "GRACE_RECOVERY_CONTROLLER_ENABLED" in os.environ:
        del os.environ["GRACE_RECOVERY_CONTROLLER_ENABLED"]
    ctrl = RecoveryController()
    assert ctrl._enabled is False


def test_controller_honors_feature_flag():
    os.environ["GRACE_RECOVERY_CONTROLLER_ENABLED"] = "true"
    ctrl = RecoveryController()
    assert ctrl._enabled is True
    del os.environ["GRACE_RECOVERY_CONTROLLER_ENABLED"]


# ── persist decision tests ───────────────────────────────────────────────────


async def test_evaluate_persists_decision():
    ctrl = RecoveryController()
    signal = FailureSignal(
        packet_id="pkt_test", packet_state="rejected",
        domain_status="rejected", reason="T1 failed", coder_attempt_count=0,
    )
    with patch.object(ctrl, "build_signal", return_value=signal):
        with patch.object(ctrl, "_emit_recovery_events"):
            with patch.object(ctrl, "_apply_decision"):
                with patch("grace_control.db.get_db") as mock_db:
                    mock_ctx = MagicMock()
                    mock_db.return_value.__enter__.return_value = mock_ctx
                    mock_query = MagicMock()
                    mock_ctx.query.return_value = mock_query
                    mock_query.filter_by.return_value = mock_query
                    mock_query.order_by.return_value = mock_query
                    mock_query.limit.return_value = mock_query
                    mock_query.all.return_value = []
                    decision = await ctrl.evaluate("pkt_test", allow_apply=False)

    assert "decision_id" in decision.audit_payload
    assert decision.audit_payload["decision_id"].startswith("recd-")


async def test_evaluate_emits_events():
    ctrl = RecoveryController()
    signal = FailureSignal(
        packet_id="pkt_test", packet_state="rejected",
        domain_status="rejected", reason="T1 failed", coder_attempt_count=0,
    )
    emitted_events = []

    def fake_emit(pid, sig, dec, **kw):
        emitted_events.append(("emit", pid))

    with patch.object(ctrl, "build_signal", return_value=signal):
        with patch.object(ctrl, "_persist_decision", return_value="recd_001"):
            with patch.object(ctrl, "_emit_recovery_events", side_effect=fake_emit):
                with patch.object(ctrl, "_apply_decision"):
                    await ctrl.evaluate("pkt_test", allow_apply=False)

    assert len(emitted_events) == 1


def test_strict_never_downgraded():
    from grace_control.core.feature_recovery import _safe_next_profile
    assert _safe_next_profile("STRICT", "NORMAL", RecoveryPolicy(never_downgrade_strict=True)) == "STRICT"
    assert _safe_next_profile("STRICT", "FAST", RecoveryPolicy(never_downgrade_strict=True)) == "STRICT"
    assert _safe_next_profile("STRICT", "STRICT", RecoveryPolicy(never_downgrade_strict=True)) == "STRICT"


def test_custom_recovery_policy_changes_decision():
    signal = FailureSignal(
        packet_id="pkt_test", packet_state="rejected",
        domain_status="rejected", reason="T1 failed", coder_attempt_count=3,
    )
    default = decide_recovery(signal, RecoveryPolicy(max_total_coder_attempts=3))
    custom = decide_recovery(signal, RecoveryPolicy(max_total_coder_attempts=5))
    assert default.action == RecoveryAction.RETURN_TO_ARCHITECT
    assert custom.action == RecoveryAction.SWITCH_CODER
