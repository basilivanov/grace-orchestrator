"""Block H: Packets API tests — 14 tests."""
import pytest
import uuid


def _uniq():
    return uuid.uuid4().hex[:6]


async def _plan(api, title=None, waves=None):
    if title is None:
        title = f"T{_uniq()}"
    if waves is None:
        wid = f"W{_uniq()}"
        waves = [{"title": wid, "packets": [{"title": f"P{_uniq()}", "scope": ["x.py"]}]}]
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": title, "waves": waves}
    })
    return r


@pytest.mark.asyncio
async def test_list_empty(api):
    r = await api.get("/api/packets/")
    assert r.status_code == 200
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_list_filter_by_state(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})

    r = await api.get("/api/packets/?state=running")
    assert len(r.json()["data"]) == 1
    r = await api.get("/api/packets/?state=ready")
    assert len(r.json()["data"]) == 0


@pytest.mark.asyncio
async def test_list_filter_by_feature(api):
    r = await _plan(api, title=f"FA{_uniq()}")
    fid_a = r.json()["data"]["features"][0] if "features" in r.json()["data"] else r.json()["data"]["feature_id"]
    await _plan(api, title=f"FB{_uniq()}")
    r = await api.get(f"/api/packets/?feature_id={fid_a}")
    for p in r.json()["data"]:
        assert p["feature_id"] == fid_a


@pytest.mark.asyncio
async def test_get_packet_structure(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    r = await api.get(f"/api/packets/{pid}")
    d = r.json()["data"]
    for field in ["id", "feature_id", "wave_id", "slug", "title", "state",
                  "acceptance_profile", "attempt_count", "max_attempts", "runs", "created_at"]:
        assert field in d, f"Missing field: {field}"
    assert d["state"] == "ready"


@pytest.mark.asyncio
async def test_get_packet_404(api):
    r = await api.get("/api/packets/NONEXISTENT")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_claim_returns_spec_and_lease(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    r = await api.post("/api/packets/claim", json={"worker_id": "w1"})
    data = r.json()["data"]
    assert data["packet_id"] == pid
    assert data["lease_id"] is not None
    assert data["expires_at"] is not None


@pytest.mark.asyncio
async def test_claim_no_packets_404(api):
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    r = await api.post("/api/packets/claim", json={"worker_id": "w1"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_release_accepted(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    r = await api.post(f"/api/packets/{pid}/release", json={
        "worker_id": "w1", "status": "accepted", "result": {"accepted": True}})
    assert r.json()["data"]["state"] == "accepted"


@pytest.mark.asyncio
async def test_release_rejected(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    r = await api.post(f"/api/packets/{pid}/release", json={
        "worker_id": "w1", "status": "rejected", "result": {}})
    assert r.json()["data"]["state"] == "rejected"


@pytest.mark.asyncio
async def test_release_unknown_status_is_failed(api):
    """API rejects unknown release status with 422."""
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    r = await api.post(f"/api/packets/{pid}/release", json={
        "worker_id": "w1", "status": "garbage", "result": {}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_cancel_ready(api):
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    r = await api.post(f"/api/packets/{pid}/cancel", json={"reason": "test"})
    assert r.status_code == 200
    assert r.json()["data"]["state"] == "cancelled"


@pytest.mark.asyncio
async def test_release_blocked(api):
    """API release with status=blocked moves packet to blocked_final state."""
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    r = await api.post(f"/api/packets/{pid}/release", json={
        "worker_id": "w1", "status": "blocked",
        "result": {"accepted": False, "domain_status": "blocked", "reason": "scope impossible"}})
    assert r.status_code == 200
    assert r.json()["data"]["state"] == "blocked_final"
    r2 = await api.get(f"/api/packets/{pid}")
    assert r2.json()["data"]["state"] == "blocked_final"


@pytest.mark.asyncio
async def test_cancel_invalid_state_is_400(api):
    """Cancel on a terminal or non-cancellable state returns 400/500."""
    r = await _plan(api)
    pid = r.json()["data"]["packets"][0]
    await api.post("/api/workers/register", json={"worker_id": "w1"})
    await api.post("/api/packets/claim", json={"worker_id": "w1"})
    await api.post(f"/api/packets/{pid}/release",
                   json={"worker_id": "w1", "status": "accepted", "result": {"accepted": True}})
    # ACCEPTED → CANCELLED not allowed by state machine
    r = await api.post(f"/api/packets/{pid}/cancel", json={"reason": "test"})
    assert r.status_code in (400, 500)


@pytest.mark.asyncio
async def test_merge_requires_worktree_and_branch(api):
    """Merge returns 400 without worktree_path/branch_name."""
    r = await api.post("/api/packets/any/merge", json={})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_runtime_diagnostics_no_runs(api):
    from grace_control.db import get_db
    from grace_control.db.schema import Packet

    with get_db() as db:
        db.add(Packet(id="pkt-diag-001", feature_id="f1", wave_id="w1",
                       slug="pkt-diag-001", title="Diag",
                       spec_json={}, state="draft"))
        db.commit()

    r = await api.get("/api/packets/pkt-diag-001/runtime-diagnostics")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "no_runs"


@pytest.mark.asyncio
async def test_runtime_diagnostics_scope_failure(api):
    from grace_control.db import get_db
    from grace_control.db.schema import Packet, PacketRun

    with get_db() as db:
        db.add(Packet(id="pkt-scope-001", feature_id="f1", wave_id="w1",
                       slug="pkt-scope-001", title="Scope Fail",
                       spec_json={}, state="failed"))
        run = PacketRun(
            id="pkt-scope-001-R01", packet_id="pkt-scope-001",
            run_number=1, worker_id="w1", status="failed",
            result_json={
                "diagnostics": {
                    "evidence": {
                        "failure_code": "AGENT_CHANGED_OUT_OF_SCOPE",
                        "scope_enforcement": {
                            "ok": False,
                            "out_of_scope_files": ["outside/x.py"],
                            "summary": "Agent changed files outside allowed scope",
                        },
                        "diff_inspection": {"ok": True, "changed_files": ["outside/x.py"]},
                        "changed_files": ["outside/x.py"],
                    }
                }
            },
        )
        db.add(run)
        db.commit()

    r = await api.get("/api/packets/pkt-scope-001/runtime-diagnostics")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["failure_code"] == "AGENT_CHANGED_OUT_OF_SCOPE"
    assert "outside" in data["details"]
    assert "outside/x.py" in data["changed_files"]


@pytest.mark.asyncio
async def test_runtime_diagnostics_success(api):
    from grace_control.db import get_db
    from grace_control.db.schema import Packet, PacketRun

    with get_db() as db:
        db.add(Packet(id="pkt-ok-001", feature_id="f1", wave_id="w1",
                       slug="pkt-ok-001", title="OK Packet",
                       spec_json={}, state="accepted"))
        run = PacketRun(
            id="pkt-ok-001-R01", packet_id="pkt-ok-001",
            run_number=1, worker_id="w1", status="accepted",
            result_json={
                "diagnostics": {
                    "evidence": {
                        "failure_code": None,
                        "changed_files": ["src/ok.py"],
                        "scope_enforcement": {"ok": True, "out_of_scope_files": [],
                                              "frozen_touched_files": []},
                        "diff_inspection": {"ok": True, "changed_files": ["src/ok.py"]},
                        "artifact_refs": ["runtime_diagnostics.json", "scope_enforcement.json"],
                    }
                }
            },
        )
        db.add(run)
        db.commit()

    r = await api.get("/api/packets/pkt-ok-001/runtime-diagnostics")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["failure_code"] is None
    assert "runtime_diagnostics.json" in data.get("artifact_refs", [])
    assert "src/ok.py" in data["changed_files"]


@pytest.mark.asyncio
async def test_runtime_diagnostics_top_level_failure_code(api):
    """Endpoint must also read failure_code from top-level diagnostics
    (not only from diagnostics.evidence), because _fast_reject writes it there."""
    from grace_control.db import get_db
    from grace_control.db.schema import Packet, PacketRun

    with get_db() as db:
        db.add(Packet(id="pkt-nochange-001", feature_id="f1", wave_id="w1",
                       slug="pkt-nochange-001", title="No Change",
                       spec_json={}, state="failed"))
        run = PacketRun(
            id="pkt-nochange-001-R01", packet_id="pkt-nochange-001",
            run_number=1, worker_id="w1", status="rejected",
            result_json={
                "diagnostics": {
                    "failure_code": "AGENT_NO_CHANGES_PRODUCED",
                    "failure_stage": "post_execution_inspection",
                }
            },
        )
        db.add(run)
        db.commit()

    r = await api.get("/api/packets/pkt-nochange-001/runtime-diagnostics")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["failure_code"] == "AGENT_NO_CHANGES_PRODUCED", \
        f"expected AGENT_NO_CHANGES_PRODUCED, got {data.get('failure_code')}"
