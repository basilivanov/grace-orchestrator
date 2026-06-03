"""Block K: Architect API tests — 8 tests."""
import pytest


@pytest.mark.asyncio
async def test_plan_returns_feature_id(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Auth", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    assert r.json()["data"]["feature_id"] == "FEAT-AUTH"


@pytest.mark.asyncio
async def test_plan_slug_from_title(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Add JWT Utils v2", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    assert "ADD-JWT-UTILS-V2" in r.json()["data"]["feature_id"]


@pytest.mark.asyncio
async def test_plan_packet_ids_format(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Auth", "waves": [{"title": "Foundation", "packets": [{"title": "Add login", "scope": ["x.py"]}]}]}})
    pid = r.json()["data"]["packets"][0]
    assert "FEAT-AUTH-AUTH-W01-P01" in pid


@pytest.mark.asyncio
async def test_plan_creates_packets_in_ready(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Z", "waves": [{"title": "W1", "packets": [
            {"title": "A", "scope": ["a.py"]}, {"title": "B", "scope": ["b.py"]}]}]}})
    assert r.json()["data"]["packets_count"] == 2
    r = await api.get("/api/packets/?state=ready")
    assert len(r.json()["data"]) >= 2


@pytest.mark.asyncio
async def test_plan_scope_conflict_422(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "CF", "waves": [{"title": "W1", "packets": [
            {"title": "A", "scope": ["shared.py"]}, {"title": "B", "scope": ["shared.py"]}]}]}})
    assert r.status_code == 422
    assert "errors" in r.json()["detail"]


@pytest.mark.asyncio
async def test_plan_dag_cycle_422(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "CY", "waves": [{"title": "W1", "packets": [
            {"title": "Add A", "scope": ["a.py"], "depends_on": ["ADD-B"]},
            {"title": "Add B", "scope": ["b.py"], "depends_on": ["ADD-A"]}]}]}})
    assert r.status_code == 422
    assert "cycles" in r.json()["detail"]


@pytest.mark.asyncio
async def test_plan_multiwave_wave2_starts_draft(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "MW", "waves": [
            {"title": "W1", "packets": [{"title": "A", "scope": ["a.py"]}]},
            {"title": "W2", "packets": [{"title": "B", "scope": ["b.py"]}]}]}})
    pids = r.json()["data"]["packets"]
    for pid in pids:
        r2 = await api.get(f"/api/packets/{pid}")
        state = r2.json()["data"]["state"]
        if "W01" in pid:
            assert state == "ready"
        else:
            assert state == "draft"


@pytest.mark.asyncio
async def test_plan_idempotent_feature_id(api):
    """Second plan with same title returns same feature_id (idempotent)."""
    r1 = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "IdempotentTest", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    fid1 = r1.json()["data"]["feature_id"]
    r2 = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "IdempotentTest", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    assert r2.status_code == 200
    assert r2.json()["data"]["feature_id"] == fid1


@pytest.mark.asyncio
async def test_plan_propagates_root_verification_into_packets(api):
    """P0-1: root-level verification and constraints.frozen_scope propagate into packet spec_json."""
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {
            "title": "PropTest",
            "verification": ["pytest tests/ -x"],
            "constraints": {"frozen_scope": ["src/secret/"]},
            "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}],
        }})
    pid = r.json()["data"]["packets"][0]
    r2 = await api.get(f"/api/packets/{pid}")
    spec = r2.json()["data"]["spec_json"]
    assert "verification" in spec
    assert "pytest" in str(spec["verification"])
    assert spec.get("frozen_scope", []) == ["src/secret/"]


@pytest.mark.asyncio
async def test_plan_packet_level_verification_overrides_root(api):
    """P0-1: packet-level verification takes precedence over root-level."""
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {
            "title": "OverrideTest",
            "verification": ["root command"],
            "waves": [{"title": "W1", "packets": [
                {"title": "P1", "scope": ["x.py"], "verification": ["packet command"]}
            ]}],
        }})
    pid = r.json()["data"]["packets"][0]
    r2 = await api.get(f"/api/packets/{pid}")
    spec = r2.json()["data"]["spec_json"]
    assert spec["verification"] == ["packet command"]



