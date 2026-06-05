"""W4 acceptance tests for source/codex/tz-api-first-cleanup-waves-w0-w11.md §W4.

Asserts:
1. /api/trace/packets/{id} returns state, runs, timeline, last_failure.
2. /api/trace/features/{id} groups packets by wave.
3. /api/trace/search?q=... returns matching packets.
4. /api/events supports filtering + pagination.
5. /api/diagnostics/state returns counts.
6. OpenAPI contains all four trace endpoints.
7. 404 for missing packet/feature/run.
"""
from datetime import datetime
import os

import pytest
from fastapi.testclient import TestClient

from grace_control.api.main import app
from grace_control.db import get_db, init_db
from grace_control.db.schema import (
    Event,
    Feature,
    Packet,
    PacketRun,
    PacketState,
    Wave,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path, monkeypatch):
    os.environ["GRACE_CONTEXT_DISABLED"] = "true"
    db_url = f"sqlite:///{tmp_path}/w4_test.db"
    os.environ["GRACE_DB_URL"] = db_url
    init_db(db_url)
    return TestClient(app)


def _seed_trace_data():
    """Seed a feature/wave/packet/run/event tree for trace queries."""
    with get_db() as db:
        db.add(Feature(id="F1", slug="f1", title="Feature 1", spec_json={}, status="IN_PROGRESS"))
        db.add(Wave(id="W01", feature_id="F1", slug="w01", title="Wave 1", order=1, status="IN_PROGRESS"))
        db.add(Packet(
            id="pkt_1", feature_id="F1", wave_id="W01", slug="p1", title="Packet 1",
            spec_json={}, state=PacketState.RUNNING.value,
            attempt_count=1, max_attempts=3, acceptance_profile="NORMAL",
        ))
        db.add(PacketRun(
            id="run_1", packet_id="pkt_1", run_number=1, executor_id="executor-A",
            worker_id="w-1", status="rejected", duration_ms=1234,
            started_at=datetime(2026, 6, 5, 10, 0, 0),
            finished_at=datetime(2026, 6, 5, 10, 0, 1),
            evidence_path="/tmp/evidence/pkt_1/0001",
            result_json={
                "acceptance_report": {
                    "final_verdict": "rejected",
                    "summary": "ruff failed on src/x.py",
                    "stages": [
                        {"name": "T0", "status": "passed"},
                        {"name": "T1", "status": "failed",
                         "blocking_issues": ["ruff: E501 line too long"]},
                    ],
                }
            },
        ))
        db.add(Event(
            event_type="packet_claimed", entity_type="packet", entity_id="pkt_1",
            payload_json={"action": "claim", "reason": "ready"},
            trace_id="trace-001",
            timestamp=datetime(2026, 6, 5, 10, 0, 0),
        ))
        db.commit()


# ── 1. /api/trace/packets/{id} ──────────────────────────────────────────────


def test_packet_trace_returns_state_runs_timeline(client):
    _seed_trace_data()
    resp = client.get("/api/trace/packets/pkt_1")
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["packet_id"] == "pkt_1"
    assert body["current_state"] == "running"
    assert body["attempt_count"] == 1
    assert body["max_attempts"] == 3
    assert len(body["runs"]) == 1
    assert body["runs"][0]["status"] == "rejected"
    assert body["runs"][0]["executor_id"] == "executor-A"
    assert body["runs"][0]["duration_ms"] == 1234
    assert len(body["timeline"]) == 1
    assert body["timeline"][0]["event_type"] == "packet_claimed"
    assert body["last_failure"] is not None
    assert body["last_failure"]["stage"] == "acceptance"
    assert "ruff failed" in body["last_failure"]["summary"]
    assert any("ruff: E501" in issue for issue in body["last_failure"]["blocking_issues"])
    assert body["recommended_next_action"] == "retry"


def test_packet_trace_404_for_missing(client):
    resp = client.get("/api/trace/packets/pkt_does_not_exist")
    assert resp.status_code == 404


# ── 2. /api/trace/features/{id} ─────────────────────────────────────────────


def test_feature_trace_groups_packets_by_wave(client):
    _seed_trace_data()
    resp = client.get("/api/trace/features/F1")
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["feature_id"] == "F1"
    assert body["status"] == "IN_PROGRESS"
    assert len(body["waves"]) == 1
    w = body["waves"][0]
    assert w["wave_id"] == "W01"
    assert len(w["packets"]) == 1
    assert w["packets"][0]["packet_id"] == "pkt_1"


def test_feature_trace_404_for_missing(client):
    resp = client.get("/api/trace/features/F-missing")
    assert resp.status_code == 404


# ── 3. /api/trace/search ────────────────────────────────────────────────────


def test_trace_search_finds_packet_by_title(client):
    _seed_trace_data()
    resp = client.get("/api/trace/search", params={"q": "Packet 1"})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert any(r["id"] == "pkt_1" and r["kind"] == "packet" for r in body["results"])


def test_trace_search_finds_run_by_executor(client):
    _seed_trace_data()
    resp = client.get("/api/trace/search", params={"q": "executor-A"})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert any(r["kind"] == "run" and r["executor_id"] == "executor-A" for r in body["results"])


# ── 4. /api/events ──────────────────────────────────────────────────────────


def test_events_supports_filtering_and_pagination(client):
    _seed_trace_data()
    # Add a second event for the same entity.
    with get_db() as db:
        db.add(Event(
            event_type="packet_released", entity_type="packet", entity_id="pkt_1",
            payload_json={"action": "release", "reason": "rejected"},
            timestamp=datetime(2026, 6, 5, 10, 0, 1),
        ))
        db.commit()

    resp = client.get("/api/events", params={"entity_id": "pkt_1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert body["total"] == 2
    assert len(body["events"]) == 2
    assert body["limit"] == 100

    # Filter by event_type
    resp = client.get("/api/events", params={"event_type": "packet_claimed"})
    body = resp.json()["data"]
    assert body["total"] == 1
    assert body["events"][0]["event_type"] == "packet_claimed"

    # Pagination
    resp = client.get("/api/events", params={"limit": 1, "offset": 1})
    body = resp.json()["data"]
    assert body["total"] == 2
    assert len(body["events"]) == 1


# ── 5. /api/diagnostics/state ──────────────────────────────────────────────


def test_diagnostics_state_returns_counts(client):
    _seed_trace_data()
    resp = client.get("/api/diagnostics/state")
    assert resp.status_code == 200, resp.text
    body = resp.json()["data"]
    assert "packets_by_state" in body
    assert body["packets_by_state"]["running"] == 1
    assert body["runs_total"] == 1
    assert body["workers"]["total"] == 0


# ── 6. OpenAPI contains the new endpoints ──────────────────────────────────


def test_openapi_contains_w4_endpoints(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    for path in (
        "/api/trace/packets/{packet_id}",
        "/api/trace/features/{feature_id}",
        "/api/trace/runs/{run_id}",
        "/api/trace/search",
        "/api/events",
        "/api/diagnostics/state",
    ):
        assert path in paths, f"OpenAPI missing {path}"
