"""Verify all 4 inspector tabs have real data via API."""
import httpx
import pytest

API = "http://localhost:8042"


@pytest.fixture
def packet_with_runs():
    c = httpx.Client(base_url=API, timeout=5)
    r = c.get("/api/packets/")
    pkts = [p for p in r.json()["data"] if p["attempt_count"] > 0]
    if not pkts:
        pytest.skip("No packets with runs — run at least one packet first")
    pid = pkts[0]["id"]
    r = c.get(f"/api/packets/{pid}")
    return r.json()["data"], pid


def test_overview_tab_has_state(packet_with_runs):
    d, _ = packet_with_runs
    assert "state" in d
    assert d["state"] in ("merged", "accepted", "running", "failed", "rejected", "cancelled", "ready")
    assert "attempt_count" in d
    assert "acceptance_profile" in d
    assert "feature_id" in d
    assert "wave_id" in d


def test_runs_tab_has_entries(packet_with_runs):
    d, _ = packet_with_runs
    runs = d.get("runs", [])
    assert len(runs) > 0, f"No runs for packet"
    for run in runs:
        assert "run_number" in run
        assert "status" in run


def test_events_tab_has_data(packet_with_runs):
    _, pid = packet_with_runs
    c = httpx.Client(base_url=API, timeout=5)
    r = c.get(f"/api/events?entity_type=packet&entity_id={pid}")
    events = r.json()["data"]
    assert len(events) > 0, "No events — packet needs claim/release/merge history"


def test_artifacts_endpoint_reachable(packet_with_runs):
    d, pid = packet_with_runs
    runs = d.get("runs", [])
    if not runs:
        pytest.skip("No runs")
    c = httpx.Client(base_url=API, timeout=5)
    run_num = runs[-1]["run_number"]
    r = c.get(f"/api/packets/{pid}/runs/R{run_num:02d}/artifacts")
    assert r.status_code == 200
