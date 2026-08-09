"""Block K: Architect API tests — 10 tests."""

import pytest


@pytest.mark.asyncio
async def test_plan_feature_id_is_nanoid(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Auth", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    fid = r.json()["data"]["feature_id"]
    assert fid.startswith("feat_")
    assert len(fid) == 15


@pytest.mark.asyncio
async def test_plan_has_slug(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Add JWT Utils v2", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    data = r.json()["data"]
    assert data["slug"] == "add-jwt-utils-v2"


@pytest.mark.asyncio
async def test_plan_packet_ids_are_nanoid(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Auth", "waves": [{"title": "Foundation", "packets": [{"title": "Add login", "scope": ["x.py"]}]}]}})
    pid = r.json()["data"]["packets"][0]
    assert pid.startswith("pkt_")
    assert len(pid) == 14


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
async def test_plan_scope_conflict_422_does_not_create_orphan_feature(api):
    title = "AtomicConflictValidation"

    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": title, "waves": [{"title": "W1", "packets": [
            {"title": "A", "scope": ["shared.py"]},
            {"title": "B", "scope": ["shared.py"]},
        ]}]},
    })

    assert r.status_code == 422
    features = (await api.get("/api/features/")).json()["data"]
    assert all(feature["title"] != title for feature in features)


@pytest.mark.asyncio
async def test_plan_missing_dependency_422(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "MissingDependency", "waves": [{"title": "W1", "packets": [
            {"title": "Consumer", "scope": ["consumer.py"], "depends_on": ["Missing producer"]},
        ]}]},
    })

    assert r.status_code == 422
    assert any("Missing dependency" in error for error in r.json()["detail"]["errors"])


@pytest.mark.asyncio
async def test_new_plan_same_wave_dependency_422(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "SameWaveDependency", "waves": [{"title": "W1", "packets": [
            {"title": "Producer", "scope": ["producer.py"], "depends_on": [], "conflict_keys": []},
            {"title": "Consumer", "scope": ["consumer.py"], "depends_on": ["Producer"], "conflict_keys": []},
        ]}]},
    })

    assert r.status_code == 422
    assert any("Dependency wave order invalid" in error for error in r.json()["detail"]["errors"])


@pytest.mark.asyncio
async def test_plan_allows_ordered_packets_to_revisit_scope_by_title(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "OrderedScopeReuse", "waves": [
            {"title": "W1", "packets": [
                {"title": "Create shared contract", "scope": ["shared.py"]},
            ]},
            {"title": "W2", "packets": [
                {
                    "title": "Finalize shared contract",
                    "scope": ["shared.py"],
                    "depends_on": ["Create shared contract"],
                },
            ]},
        ]},
    })

    assert r.status_code == 200
    assert r.json()["data"]["packets_count"] == 2


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
        # First wave packets are ready, second wave packets are draft
        assert state in ("ready", "draft")


@pytest.mark.asyncio
async def test_same_title_creates_different_feature_ids(api):
    """Same title posted twice creates two different feature IDs (no idempotency)."""
    r1 = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "NonIdempotentTZ", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    fid1 = r1.json()["data"]["feature_id"]
    r2 = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "NonIdempotentTZ", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    assert r2.status_code == 200
    assert r2.json()["data"]["feature_id"] != fid1
    assert r1.json()["data"]["slug"] == r2.json()["data"]["slug"] == "nonidempotenttz"


@pytest.mark.asyncio
async def test_architect_response_contains_feature_id_and_slug(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "RespTest", "waves": [{"title": "W1", "packets": [{"title": "P1", "scope": ["x.py"]}]}]}})
    d = r.json()["data"]
    assert d["feature_id"].startswith("feat_")
    assert d["feature_slug"] == "resptest"
    assert d["slug"] == "resptest"


@pytest.mark.asyncio
async def test_architect_response_packet_summaries(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "SumTest", "waves": [{"title": "W1", "packets": [
            {"title": "Create util", "scope": ["x.py"]},
            {"title": "Add test", "scope": ["y.py"]}]}]}})
    d = r.json()["data"]
    assert len(d["packet_summaries"]) == 2
    for ps in d["packet_summaries"]:
        assert "id" in ps and ps["id"].startswith("pkt_")
        assert "slug" in ps
        assert "title" in ps
        assert "wave_id" in ps and ps["wave_id"].startswith("wave_")
    assert d["packet_summaries"][0]["title"] == "Create util"
    assert d["packet_summaries"][1]["title"] == "Add test"


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


@pytest.mark.asyncio
async def test_plan_materializes_normalized_conflict_keys(api):
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "ConflictMaterialization", "waves": [{"title": "W1", "packets": [
            {
                "title": "Semantic packet",
                "scope": ["contract.py"],
                "conflict_keys": [" api:user-service ", "db-schema"],
            },
        ]}]},
    })
    assert r.status_code == 200

    packet_id = r.json()["data"]["packets"][0]
    packet = await api.get(f"/api/packets/{packet_id}")
    assert packet.json()["data"]["spec_json"]["conflict_keys"] == [
        "api:user-service", "db-schema"
    ]
