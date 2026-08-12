# ############################################################################
# AI_HEADER: test_architect_running_timer
# ROLE: Tests for architect running state with live timer — elapsed_seconds
#       and is_running for currently-executing and completed packet runs.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify that packets in RUNNING state report a live timer via
#          elapsed_seconds (growing) and is_running=True, and that
#          completed packets stop the timer and report is_running=False.
# inputs: Uses DB fixtures + AdminAggregationService.
# verifies: elapsed_seconds > 0 for live runs, elapsed_seconds fixed for
#           finished runs, is_running flag transitions correctly.
# emitted_logs: None (uses mock DB, no log capture).
# error_behavior: Each test independent; no cross-test state leak.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: _seed_running_packet
#   - function: test_running_packet_live_timer_detail
#   - function: test_running_packet_is_running_flag
#   - function: test_finished_packet_timer_stops
#   - function: test_no_started_at_returns_none_elapsed
# END_MODULE_MAP

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import (
    Event,
    Feature,
    Packet,
    PacketRun,
    Wave,
)
from grace_control.db import get_db, init_db
from grace_control.services.admin_aggregation_service import (
    AdminAggregationService,
    _elapsed_seconds,
    _is_running,
)

_log = GraceLogger("test_architect_running_timer")

#START_BLOCK_FIXTURES


#START_FUNCTION_CONTRACT
# name: db_url
# purpose: Create a temporary SQLite DB URL and disable context collection.
# inputs: tmp_path, monkeypatch (pytest fixtures).
# returns: DB URL string.
# side_effects: Creates SQLite DB file, sets env vars.
# emitted_logs: None.
# error_behavior: None.
#END_FUNCTION_CONTRACT
@pytest.fixture
def db_url(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/arch_running_test.db"
    monkeypatch.setenv("GRACE_DB_URL", url)
    monkeypatch.setenv("GRACE_CONTEXT_DISABLED", "true")
    init_db(url)
    return url


#START_FUNCTION_CONTRACT
# name: svc
# purpose: Provide an AdminAggregationService instance.
# inputs: None.
# returns: AdminAggregationService.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
#END_FUNCTION_CONTRACT
@pytest.fixture
def svc():
    return AdminAggregationService()


#START_FUNCTION_CONTRACT
# name: session
# purpose: Provide a SQLAlchemy DB session for test setup/queries.
# inputs: None.
# returns: SQLAlchemy Session.
# side_effects: Opens/closes DB connection.
# emitted_logs: None.
# error_behavior: None.
#END_FUNCTION_CONTRACT
@pytest.fixture
def session():
    with get_db() as db:
        yield db


#END_BLOCK_FIXTURES

#START_BLOCK_HELPERS


def _ensure_tz_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _seed_running_packet(
    session,
    run_status: str = "running",
    finished_at: datetime | None = None,
    duration_ms: int | None = None,
):
    """Seed Feature/Wave/Packet/PacketRun for a currently-running packet."""
    session.add(Feature(id="F_RUN", slug="f-run", title="Running Feature", spec_json={}, status="IN_PROGRESS"))
    session.add(Wave(id="W_RUN", feature_id="F_RUN", slug="w-run", title="Running Wave", order=1, status="IN_PROGRESS"))
    session.add(Packet(
        id="pkt_run", feature_id="F_RUN", wave_id="W_RUN", slug="p-run",
        title="Running Packet", spec_json={"scope": ["src/x.py"]},
        state="running", attempt_count=1, max_attempts=3, acceptance_profile="NORMAL",
    ))
    started = datetime(2026, 6, 10, 14, 30, 0, tzinfo=UTC)
    session.add(PacketRun(
        id="pkt_run-1", packet_id="pkt_run", run_number=1,
        executor_id="exec-A", worker_id="w-1",
        model="deepseek/deepseek-v4-flash",
        status=run_status, duration_ms=duration_ms,
        command_preview=["agy", "run", "--model", "deepseek-v4-flash"],
        prompt="Implement feature X",
        started_at=started,
        finished_at=finished_at,
    ))
    session.commit()


#END_BLOCK_HELPERS


#START_BLOCK_TESTS


#START_FUNCTION_CONTRACT
# name: test_running_packet_live_timer_detail
# purpose: Verify get_packet_detail returns elapsed_seconds > 0 for a
#          running packet with no finished_at (live timer).
# inputs: db_url, svc, session fixtures.
# verifies: elapsed_seconds is not None and > 0.
# emitted_logs: None.
# error_behavior: AssertionError on mismatch.
#END_FUNCTION_CONTRACT
def test_running_packet_live_timer_detail(db_url, svc, session):
    """A running packet with active PacketRun shows elapsed_seconds > 0."""
    _seed_running_packet(session)
    out = svc.get_packet_detail(session, "pkt_run")
    assert out is not None
    assert out["packet"]["state"] == "running"
    assert out["is_running"] is True
    assert out["elapsed_seconds"] is not None
    assert out["elapsed_seconds"] > 0
    _log.info("running_timer_detail", packet_id="pkt_run", elapsed=out["elapsed_seconds"])


#START_FUNCTION_CONTRACT
# name: test_running_packet_is_running_flag
# purpose: Verify get_packet_runs returns is_running=True for active
#          run and elapsed_seconds with no finished_at.
# inputs: db_url, svc, session fixtures.
# verifies: is_running=True, elapsed_seconds computed from started_at to now.
# emitted_logs: None.
# error_behavior: AssertionError on mismatch.
#END_FUNCTION_CONTRACT
def test_running_packet_is_running_flag(db_url, svc, session):
    """PacketRun with no finished_at has is_running=True and live elapsed."""
    _seed_running_packet(session)
    out = svc.get_packet_runs(session, "pkt_run")
    assert len(out["runs"]) == 1
    r = out["runs"][0]
    assert r["is_running"] is True
    assert r["elapsed_seconds"] is not None
    assert r["elapsed_seconds"] > 0
    assert r["finished_at"] is None
    _log.info("running_flag", packet_id="pkt_run", elapsed=r["elapsed_seconds"])


#START_FUNCTION_CONTRACT
# name: test_finished_packet_timer_stops
# purpose: Verify a finished PacketRun has is_running=False and
#          elapsed_seconds matches the fixed duration.
# inputs: db_url, svc, session fixtures.
# verifies: is_running=False, elapsed_seconds equals finished - started.
# emitted_logs: None.
# error_behavior: AssertionError on mismatch.
#END_FUNCTION_CONTRACT
def test_finished_packet_timer_stops(db_url, svc, session):
    """Completed PacketRun has is_running=False and exact elapsed duration."""
    started = datetime(2026, 6, 10, 14, 30, 0, tzinfo=UTC)
    finished = datetime(2026, 6, 10, 14, 35, 0, tzinfo=UTC)
    _seed_running_packet(session, run_status="accepted", finished_at=finished, duration_ms=300_000)
    out = svc.get_packet_runs(session, "pkt_run")
    assert len(out["runs"]) == 1
    r = out["runs"][0]
    assert r["is_running"] is False
    assert r["elapsed_seconds"] == 300  # 5 minutes
    assert r["finished_at"] is not None
    _log.info("timer_stopped", packet_id="pkt_run", elapsed=r["elapsed_seconds"])


#START_FUNCTION_CONTRACT
# name: test_no_started_at_returns_none_elapsed
# purpose: Verify _elapsed_seconds returns None when started_at is None.
# inputs: None (pure unit test).
# verifies: _elapsed_seconds(None, None) is None.
# emitted_logs: None.
# error_behavior: AssertionError on mismatch.
#END_FUNCTION_CONTRACT
def test_no_started_at_returns_none_elapsed():
    """No started_at means no elapsed_seconds (None)."""
    assert _elapsed_seconds(None, None) is None


#START_FUNCTION_CONTRACT
# name: test_is_running_false_when_finished
# purpose: Verify _is_running returns False when status is a terminal
#          run status like "accepted" or "rejected".
# inputs: None (pure unit test).
# verifies: _is_running correct for various status/timestamp combos.
# emitted_logs: None.
# error_behavior: AssertionError on mismatch.
#END_FUNCTION_CONTRACT
def test_is_running_false_when_finished():
    """Terminal run statuses yield is_running=False even if finished_at is None."""
    now = datetime.now(UTC)
    assert _is_running("accepted", now, None) is False
    assert _is_running("rejected", now, None) is False
    assert _is_running("failed", now, None) is False


#START_FUNCTION_CONTRACT
# name: test_live_timer_grows_over_time
# purpose: Verify that _elapsed_seconds with no finished_at returns a
#          positive value that increases over time (live timer).
# inputs: None (pure unit test).
# verifies: elapsed > 0 for started_at in the past.
# emitted_logs: None.
# error_behavior: AssertionError on mismatch.
#END_FUNCTION_CONTRACT
def test_live_timer_grows_over_time():
    """_elapsed_seconds with only started_at returns live duration."""
    started = datetime.now(UTC) - timedelta(seconds=10)
    elapsed = _elapsed_seconds(started, None)
    assert elapsed is not None
    assert elapsed >= 9  # at least ~10 seconds have passed


#END_BLOCK_TESTS
