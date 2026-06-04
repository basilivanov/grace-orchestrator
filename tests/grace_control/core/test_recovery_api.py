"""Tests for Phase 3 Recovery API endpoints (no real DB/git/LLMs)."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from grace_control.api.main import app
from grace_control.core.feature_recovery import (
    FailureClass,
    FailureSignal,
    RecoveryAction,
    RecoveryDecision,
)

client = TestClient(app)


async def _async_decision(decision):
    return decision


@patch("grace_control.core.recovery_controller.RecoveryController")
def test_evaluate_endpoint_returns_decision(MockCtrl):
    decision = RecoveryDecision(
        action=RecoveryAction.RETRY_SAME_CODER,
        failure_class=FailureClass.RETRYABLE_CODER,
        reason="T1 failed",
        next_executor_hint="coder-flash",
    )
    mock_ctrl = MockCtrl.return_value
    mock_ctrl.evaluate.return_value = _async_decision(decision)

    resp = client.post("/api/recovery/evaluate/pkt_test", json={"apply": False})

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["packet_id"] == "pkt_test"
    assert data["action"] == "retry_same_coder"
    assert data["failure_class"] == "retryable_coder"
    assert data["status"] == "proposed"


@patch("grace_control.core.recovery_controller.RecoveryController")
def test_evaluate_endpoint_applied(MockCtrl):
    decision = RecoveryDecision(
        action=RecoveryAction.SWITCH_CODER,
        failure_class=FailureClass.RETRYABLE_CODER,
        reason="switch model",
        next_executor_hint="coder-sonnet",
    )
    mock_ctrl = MockCtrl.return_value
    mock_ctrl.evaluate.return_value = _async_decision(decision)

    resp = client.post("/api/recovery/evaluate/pkt_test", json={"apply": True})

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["status"] == "applied"
    assert data["next_executor_hint"] == "coder-sonnet"


@patch("grace_control.db.get_db")
def test_get_packet_recovery_endpoint(mock_db):
    mock_ctx = mock_db.return_value.__enter__.return_value
    mock_query = mock_ctx.query.return_value
    mock_query.filter_by.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = []

    resp = client.get("/api/recovery/packets/pkt_test")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["packet_id"] == "pkt_test"
    assert data["total"] == 0


@patch("grace_control.db.get_db")
def test_get_feature_recovery_endpoint(mock_db):
    mock_ctx = mock_db.return_value.__enter__.return_value
    mock_query = mock_ctx.query.return_value
    mock_query.filter_by.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = []

    resp = client.get("/api/recovery/features/feat_test")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["feature_id"] == "feat_test"
    assert data["packets_with_recovery"] == 0


@patch("grace_control.core.recovery_controller.RecoveryController")
def test_evaluate_endpoint_blocker(MockCtrl):
    decision = RecoveryDecision(
        action=RecoveryAction.BLOCK_FEATURE,
        failure_class=FailureClass.TRUE_BLOCKER,
        reason="dirty target repo",
        max_attempts_reached=True,
    )
    mock_ctrl = MockCtrl.return_value
    mock_ctrl.evaluate.return_value = _async_decision(decision)

    resp = client.post("/api/recovery/evaluate/pkt_test", json={"apply": False})

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["action"] == "block_feature"
    assert data["max_attempts_reached"] is True
