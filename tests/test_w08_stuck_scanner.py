# ############################################################################
# AI_HEADER: test_w08_stuck_scanner
# ROLE: W08 tests — recovery controller and proactive stuck scanner.
# ############################################################################

"""W08 Recovery Controller and Proactive Stuck Scanner.

Tests cover:
1. Stuck RUNNING packets with expired lease are recovered by scanner
2. Workers with stale heartbeat are marked inactive
3. Orphan leases (lease without RUNNING packet) are cleaned
4. Recoverable blocked packets emit recovery_waiting event
5. try_approve_or_repair_plan handles compiler rejection (repair path reachable)
6. Recovery scanner does not apply unsafe LLM repair by default
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from grace_control.core.stuck_scanner import (
    run_stuck_scan,
    _is_llm_repair_allowed,
    _STALE_WORKER_THRESHOLD_MINUTES,
)


# ─── Test 1: Stuck RUNNING with expired lease recovered by scanner ──────────

def test_stuck_running_with_expired_lease_recovered_by_scanner():
    """W08: A RUNNING packet with expired lease must be recovered by the
    stuck scanner — set packet to READY so it can be reclaimed."""
    from grace_control.db import get_db, init_db
    from grace_control.db.schema import Feature, Lease, Packet, PacketState, Worker

    # Use in-memory DB for test isolation
    init_db("sqlite:///:memory:")

    with get_db() as db:
        # Create a feature
        feature = Feature(
            id="feat-stuck-test",
            slug="stuck-test",
            title="Stuck Test",
            spec_json={"plan_json": {"waves": []}},
            status="IN_PROGRESS",
        )
        db.add(feature)

        # Create a RUNNING packet
        packet = Packet(
            id="pkt-stuck-running",
            feature_id="feat-stuck-test",
            wave_id="wave-1",
            slug="stuck-pkt",
            title="Stuck Packet",
            state=PacketState.RUNNING.value,
            attempt_count=1,
            spec_json={},
        )
        db.add(packet)

        # Create a worker
        worker = Worker(
            id="worker-stuck",
            status="active",
            current_packet_id="pkt-stuck-running",
            last_heartbeat=datetime.utcnow() - timedelta(minutes=10),
        )
        db.add(worker)

        # Create an EXPIRED lease (use naive UTC like the DB schema does)
        lease = Lease(
            packet_id="pkt-stuck-running",
            worker_id="worker-stuck",
            claimed_attempt=1,
            acquired_at=datetime.utcnow() - timedelta(hours=1),
            expires_at=datetime.utcnow() - timedelta(minutes=30),  # expired
            heartbeat_at=datetime.utcnow() - timedelta(minutes=30),
        )
        db.add(lease)
        db.commit()

    # Run the stuck scanner
    with patch("grace_control.core.stuck_scanner.record_event") as mock_record:
        counts = run_stuck_scan()

    # Verify: packet should be back to READY
    with get_db() as db:
        packet = db.query(Packet).filter_by(id="pkt-stuck-running").first()
        assert packet.state == PacketState.READY.value, \
            f"Stuck RUNNING packet should be recovered to READY, got: {packet.state}"

        # Lease should be deleted
        lease = db.query(Lease).filter_by(packet_id="pkt-stuck-running").first()
        assert lease is None, "Expired lease should be cleaned up"

        # Worker's current_packet_id should be cleared
        worker = db.query(Worker).filter_by(id="worker-stuck").first()
        assert worker.current_packet_id is None, \
            "Worker's current_packet_id should be cleared"

    # Verify event was recorded
    event_types = [call[0][0] for call in mock_record.call_args_list]
    assert "stuck_running_recovered" in event_types, \
        f"Expected stuck_running_recovered event, got: {event_types}"

    # Verify counts
    assert counts["stuck_running_recovered"] >= 1, \
        f"Expected at least 1 stuck_running_recovered, got: {counts}"


# ─── Test 2: Worker stale heartbeat marks worker inactive ───────────────────

def test_worker_stale_heartbeat_marks_worker_inactive():
    """W08: A worker with stale heartbeat must be marked as inactive."""
    from grace_control.db import get_db, init_db
    from grace_control.db.schema import Worker

    init_db("sqlite:///:memory:")

    with get_db() as db:
        # Create a worker with stale heartbeat (naive UTC like DB schema)
        stale_worker = Worker(
            id="worker-stale-hb",
            status="active",
            current_packet_id=None,
            last_heartbeat=datetime.utcnow() - timedelta(minutes=_STALE_WORKER_THRESHOLD_MINUTES + 5),
        )
        db.add(stale_worker)

        # Create a worker with recent heartbeat (should not be affected)
        fresh_worker = Worker(
            id="worker-fresh-hb",
            status="active",
            current_packet_id=None,
            last_heartbeat=datetime.utcnow(),
        )
        db.add(fresh_worker)
        db.commit()

    with patch("grace_control.core.stuck_scanner.record_event"):
        counts = run_stuck_scan()

    with get_db() as db:
        stale = db.query(Worker).filter_by(id="worker-stale-hb").first()
        assert stale.status == "inactive", \
            f"Stale worker should be inactive, got: {stale.status}"

        fresh = db.query(Worker).filter_by(id="worker-fresh-hb").first()
        assert fresh.status == "active", \
            f"Fresh worker should remain active, got: {fresh.status}"

    assert counts["stale_workers_deactivated"] >= 1


# ─── Test 3: Lease without RUNNING packet is cleaned ────────────────────────

def test_lease_without_running_packet_is_cleaned():
    """W08: An orphan lease (lease for a non-RUNNING packet) must be cleaned."""
    from grace_control.db import get_db, init_db
    from grace_control.db.schema import Feature, Lease, Packet, PacketState, Worker

    init_db("sqlite:///:memory:")

    with get_db() as db:
        feature = Feature(
            id="feat-orphan-test",
            slug="orphan-test",
            title="Orphan Test",
            spec_json={},
            status="IN_PROGRESS",
        )
        db.add(feature)

        # Create a READY packet (not RUNNING) with a lease — this is an orphan
        packet = Packet(
            id="pkt-orphan",
            feature_id="feat-orphan-test",
            wave_id="wave-1",
            slug="orphan-pkt",
            title="Orphan Packet",
            state=PacketState.READY.value,
            attempt_count=1,
            spec_json={},
        )
        db.add(packet)

        worker = Worker(
            id="worker-orphan",
            status="active",
            current_packet_id="pkt-orphan",
            last_heartbeat=datetime.utcnow(),
        )
        db.add(worker)

        # Create lease for non-RUNNING packet (naive UTC)
        lease = Lease(
            packet_id="pkt-orphan",
            worker_id="worker-orphan",
            claimed_attempt=1,
            acquired_at=datetime.utcnow() - timedelta(hours=1),
            expires_at=datetime.utcnow() + timedelta(minutes=30),  # not expired
            heartbeat_at=datetime.utcnow(),
        )
        db.add(lease)
        db.commit()

    with patch("grace_control.core.stuck_scanner.record_event"):
        counts = run_stuck_scan()

    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id="pkt-orphan").first()
        assert lease is None, "Orphan lease should be cleaned up"

        worker = db.query(Worker).filter_by(id="worker-orphan").first()
        assert worker.current_packet_id is None, \
            "Worker's current_packet_id should be cleared after orphan lease cleanup"

    assert counts["orphan_leases_cleaned"] >= 1


# ─── Test 4: Blocked recoverable emits recovery_waiting event ───────────────

def test_blocked_recoverable_emits_recovery_waiting_event():
    """W08: BLOCKED_RECOVERABLE packets must emit a recovery_waiting event
    with actionable diagnostics."""
    from grace_control.db import get_db, init_db
    from grace_control.db.schema import Feature, Packet, PacketState

    init_db("sqlite:///:memory:")

    with get_db() as db:
        feature = Feature(
            id="feat-blocked-test",
            slug="blocked-test",
            title="Blocked Test",
            spec_json={},
            status="IN_PROGRESS",
        )
        db.add(feature)

        # BLOCKED_RECOVERABLE packet
        packet = Packet(
            id="pkt-blocked-recov",
            feature_id="feat-blocked-test",
            wave_id="wave-1",
            slug="blocked-recov-pkt",
            title="Blocked Recoverable",
            state=PacketState.BLOCKED_RECOVERABLE.value,
            attempt_count=2,
            spec_json={},
        )
        db.add(packet)
        db.commit()

    with patch("grace_control.core.stuck_scanner.record_event") as mock_record:
        counts = run_stuck_scan()

    # Verify the event was recorded with correct type and diagnostics
    event_found = False
    for call in mock_record.call_args_list:
        if call[0][0] == "blocked_recoverable_waiting":
            event_found = True
            payload = call[0][3]
            assert payload.get("action") == "diagnostics_emitted"
            assert "architect_intervention" in payload.get("reason", "")
            assert payload.get("packet_state") == PacketState.BLOCKED_RECOVERABLE.value
            break

    assert event_found, "blocked_recoverable_waiting event should be emitted"
    assert counts["blocked_recoverable_events"] >= 1


# ─── Test 5: try_approve_or_repair_plan handles compiler rejection ─────────

def test_try_approve_or_repair_plan_handles_compiler_rejection():
    """W08: When approve_plan raises ValueError on compiler rejection,
    try_approve_or_repair_plan must catch it and route to the repair path
    instead of propagating the exception and leaving the feature stuck."""
    from grace_control.services.feature_planning_service import FeaturePlanningService

    # Create a mock service
    svc = FeaturePlanningService.__new__(FeaturePlanningService)
    svc.db = MagicMock()
    svc._trace_ctx = MagicMock()
    svc._trace_ctx.stage = "test"
    svc._artifact_store = MagicMock()
    svc._event_logger = MagicMock()

    # Create a feature mock
    feature_mock = MagicMock()
    feature_mock.id = "feat-compiler-test"
    feature_mock.status = "PLAN_FAILED"
    feature_mock.title = "Compiler Test"
    feature_mock.description = "Test description"
    feature_mock.spec_json = {
        "plan_json": {"waves": [{"title": "W1", "packets": []}]},
        "_plan_compiler": {
            "ok": False,
            "errors": [{"code": "E_SCOPE_PATH_NOT_CANONICAL", "message": "Scope path not canonical"}],
        },
    }

    svc.db.query.return_value.filter_by.return_value.first.return_value = feature_mock

    # Make approve_plan raise ValueError (simulating compiler rejection)
    with patch.object(svc, "approve_plan", side_effect=ValueError(
        "Plan compiler found 1 errors: E_SCOPE_PATH_NOT_CANONICAL: Scope path not canonical"
    )):
        # Mock the repair dependencies at their import locations
        with patch("grace_control.core.execution_environment.probe_execution_environment") as mock_env, \
             patch("grace_control.services.plan_autofix_service.SafePlanAutofixer") as mock_autofixer, \
             patch("grace_control.services.planning_recovery_service.classify_compiler_result") as mock_classify, \
             patch("grace_control.services.planning_recovery_service.is_repairable_error") as mock_is_repairable, \
             patch("grace_control.services.planning_recovery_service.run_architect_repair",
                   new_callable=AsyncMock) as mock_repair:

            mock_env.return_value = MagicMock()
            mock_classify.return_value = "repairable"
            mock_is_repairable.return_value = True

            # Autofixer returns no fix
            autofix_result = MagicMock()
            autofix_result.applied = False
            autofix_result.patched_plan = None
            autofix_result.fixes = []
            autofix_result.skipped = []
            mock_autofixer.return_value.apply.return_value = autofix_result

            # LLM repair returns error (simulating disabled LLM repair)
            mock_repair.return_value = (None, "LLM repair disabled")

            result = asyncio.run(svc.try_approve_or_repair_plan("feat-compiler-test"))

    # The result should be PLAN_FAILED (repair failed), NOT an exception
    assert result.get("status") == "PLAN_FAILED", \
        f"Expected PLAN_FAILED result, got: {result}"

    # Feature status should have been reset to PLAN_READY during repair attempt
    assert feature_mock.status == "PLAN_READY", \
        f"Feature should have been reset to PLAN_READY for repair, got: {feature_mock.status}"


# ─── Test 6: Recovery scanner does not apply unsafe LLM repair by default ──

def test_recovery_scanner_does_not_apply_unsafe_llm_repair_by_default():
    """W08: LLM-based repair must NOT be auto-applied by default.
    The _is_llm_repair_allowed() guard must return False unless
    GRACE_LLM_REPAIR_ENABLED=true is explicitly set."""

    # Default: LLM repair is NOT allowed
    with patch.dict("os.environ", {}, clear=True):
        # Remove the env var if it exists
        import os
        os.environ.pop("GRACE_LLM_REPAIR_ENABLED", None)
        assert not _is_llm_repair_allowed(), \
            "LLM repair should be disabled by default"

    # Explicitly enabled
    with patch.dict("os.environ", {"GRACE_LLM_REPAIR_ENABLED": "true"}):
        assert _is_llm_repair_allowed(), \
            "LLM repair should be enabled when GRACE_LLM_REPAIR_ENABLED=true"

    # Explicitly disabled
    with patch.dict("os.environ", {"GRACE_LLM_REPAIR_ENABLED": "false"}):
        assert not _is_llm_repair_allowed(), \
            "LLM repair should be disabled when GRACE_LLM_REPAIR_ENABLED=false"

    # Any other value = disabled
    with patch.dict("os.environ", {"GRACE_LLM_REPAIR_ENABLED": "yes"}):
        assert not _is_llm_repair_allowed(), \
            "LLM repair should be disabled for non-'true' values"


# ─── Regression: Lease for DRAFT packet is cleaned ──────────────────────────

def test_lease_for_draft_packet_is_cleaned():
    """W08 regression: A lease attached to a DRAFT packet must be cleaned.
    DRAFT was not in the original hard-coded allowlist, so the scanner
    would have silently left it in place. After switching to the invariant
    check (packet.state != RUNNING), DRAFT packets are correctly handled."""
    from grace_control.db import get_db, init_db
    from grace_control.db.schema import Feature, Lease, Packet, PacketState, Worker

    init_db("sqlite:///:memory:")

    with get_db() as db:
        feature = Feature(
            id="feat-draft-orphan",
            slug="draft-orphan-test",
            title="Draft Orphan Test",
            spec_json={},
            status="IN_PROGRESS",
        )
        db.add(feature)

        # Create a DRAFT packet with a lease — this is an orphan
        packet = Packet(
            id="pkt-draft-orphan",
            feature_id="feat-draft-orphan",
            wave_id="wave-1",
            slug="draft-orphan-pkt",
            title="Draft Orphan Packet",
            state=PacketState.DRAFT.value,
            attempt_count=0,
            spec_json={},
        )
        db.add(packet)

        worker = Worker(
            id="worker-draft-orphan",
            status="active",
            current_packet_id="pkt-draft-orphan",
            last_heartbeat=datetime.utcnow(),
        )
        db.add(worker)

        # Create lease for DRAFT packet (naive UTC)
        lease = Lease(
            packet_id="pkt-draft-orphan",
            worker_id="worker-draft-orphan",
            claimed_attempt=1,
            acquired_at=datetime.utcnow() - timedelta(hours=1),
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            heartbeat_at=datetime.utcnow(),
        )
        db.add(lease)
        db.commit()

    with patch("grace_control.core.stuck_scanner.record_event"):
        counts = run_stuck_scan()

    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id="pkt-draft-orphan").first()
        assert lease is None, "Orphan lease for DRAFT packet should be cleaned up"

        worker = db.query(Worker).filter_by(id="worker-draft-orphan").first()
        assert worker.current_packet_id is None, \
            "Worker's current_packet_id should be cleared after orphan lease cleanup"

    assert counts["orphan_leases_cleaned"] >= 1


# ─── Regression: Lease for legacy BLOCKED packet is cleaned ──────────────────

def test_lease_for_legacy_blocked_packet_is_cleaned():
    """W08 regression: A lease attached to a legacy BLOCKED (deprecated alias)
    packet must be cleaned. BLOCKED was not in the original hard-coded
    allowlist, so the scanner would have silently left it in place. After
    switching to the invariant check (packet.state != RUNNING), legacy
    BLOCKED packets are correctly handled."""
    from grace_control.db import get_db, init_db
    from grace_control.db.schema import Feature, Lease, Packet, PacketState, Worker

    init_db("sqlite:///:memory:")

    with get_db() as db:
        feature = Feature(
            id="feat-legacy-blocked",
            slug="legacy-blocked-test",
            title="Legacy Blocked Test",
            spec_json={},
            status="IN_PROGRESS",
        )
        db.add(feature)

        # Create a legacy BLOCKED packet with a lease — this is an orphan
        packet = Packet(
            id="pkt-legacy-blocked",
            feature_id="feat-legacy-blocked",
            wave_id="wave-1",
            slug="legacy-blocked-pkt",
            title="Legacy Blocked Packet",
            state=PacketState.BLOCKED.value,
            attempt_count=1,
            spec_json={},
        )
        db.add(packet)

        worker = Worker(
            id="worker-legacy-blocked",
            status="active",
            current_packet_id="pkt-legacy-blocked",
            last_heartbeat=datetime.utcnow(),
        )
        db.add(worker)

        # Create lease for legacy BLOCKED packet (naive UTC)
        lease = Lease(
            packet_id="pkt-legacy-blocked",
            worker_id="worker-legacy-blocked",
            claimed_attempt=1,
            acquired_at=datetime.utcnow() - timedelta(hours=1),
            expires_at=datetime.utcnow() + timedelta(minutes=30),
            heartbeat_at=datetime.utcnow(),
        )
        db.add(lease)
        db.commit()

    with patch("grace_control.core.stuck_scanner.record_event"):
        counts = run_stuck_scan()

    with get_db() as db:
        lease = db.query(Lease).filter_by(packet_id="pkt-legacy-blocked").first()
        assert lease is None, "Orphan lease for legacy BLOCKED packet should be cleaned up"

        worker = db.query(Worker).filter_by(id="worker-legacy-blocked").first()
        assert worker.current_packet_id is None, \
            "Worker's current_packet_id should be cleared after orphan lease cleanup"

    assert counts["orphan_leases_cleaned"] >= 1


# ─── Additional: run_stuck_scan is safe (never raises) ──────────────────────

def test_run_stuck_scan_never_raises():
    """W08: run_stuck_scan must never raise, even if DB operations fail."""
    with patch("grace_control.core.stuck_scanner.get_db", side_effect=Exception("DB error")):
        # Should not raise
        counts = run_stuck_scan()
        assert isinstance(counts, dict), "run_stuck_scan should return a dict even on error"


# ─── Additional: PLAN_FAILED repairable detected by scanner ─────────────────

def test_plan_failed_repairable_detected_by_scanner():
    """W08: The scanner must detect PLAN_FAILED features with repairable
    compiler errors and emit diagnostics events."""
    from grace_control.db import get_db, init_db
    from grace_control.db.schema import Feature

    init_db("sqlite:///:memory:")

    with get_db() as db:
        feature = Feature(
            id="feat-plan-failed-repairable",
            slug="plan-failed-repair",
            title="Plan Failed Repairable",
            spec_json={
                "plan_json": {"waves": [{"title": "W1", "packets": []}]},
                "_plan_compiler": {
                    "ok": False,
                    "errors": [
                        {"code": "E_SCOPE_PATH_NOT_CANONICAL", "message": "Scope path not canonical"},
                    ],
                },
            },
            status="PLAN_FAILED",
        )
        db.add(feature)
        db.commit()

    with patch("grace_control.core.stuck_scanner.record_event") as mock_record:
        counts = run_stuck_scan()

    # Verify the event was recorded
    event_found = False
    for call in mock_record.call_args_list:
        if call[0][0] == "plan_failed_repairable_detected":
            event_found = True
            payload = call[0][3]
            assert payload.get("error_class") == "repairable"
            assert payload.get("llm_repair_allowed") is False  # disabled by default
            break

    assert event_found, "plan_failed_repairable_detected event should be emitted"
    assert counts["plan_failed_repairable_events"] >= 1
