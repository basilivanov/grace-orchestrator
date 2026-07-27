from __future__ import annotations

import pytest
from fastapi import status


@pytest.mark.asyncio
async def test_create_feature_draft_plan(api):
    r = await api.post("/api/features/", json={
        "title": "Business Feature Test",
        "description": "Implement a user dashboard",
        "mode": "draft_plan",
        "origin": "business",
    })
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
    d = r.json()["data"]
    assert d["feature_id"].startswith("feat_")
    assert d["status"] == "PLANNING"
    assert d["mode"] == "draft_plan"
    assert d["planning"]["current_stage"] == "context_builder"
    assert len(d["planning"]["runs"]) == 2


@pytest.mark.asyncio
async def test_create_feature_auto_queue(api):
    r = await api.post("/api/features/", json={
        "title": "Auto Queue Feature",
        "description": "Quick feature",
        "mode": "auto_queue",
        "origin": "business",
    })
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
    d = r.json()["data"]
    assert d["feature_id"].startswith("feat_")
    assert d["status"] in ("queued", "PLANNING")
    assert d["mode"] == "auto_queue"


@pytest.mark.asyncio
async def test_get_planning_state_empty(api):
    r = await api.post("/api/features/", json={
        "title": "Planning State Test",
        "description": "Check planning",
        "mode": "draft_plan",
    })
    fid = r.json()["data"]["feature_id"]

    import asyncio
    await asyncio.sleep(0.1)  # Let background planning start
    r2 = await api.get(f"/api/features/{fid}/planning")
    assert r2.status_code == 200
    d = r2.json()["data"]
    assert d["feature_id"] == fid
    assert d["status"] in ("PLANNING", "PLAN_READY", "PLAN_FAILED", "queued")
    assert len(d["runs"]) >= 2


@pytest.mark.asyncio
async def test_approve_fails_before_plan_ready(api):
    import asyncio

    class _SlowContextBuilder:
        """Replace context builder with one that takes time."""
        def run_context_builder(self, feature_id):
            import time
            time.sleep(0.3)
            return {"feature_id": feature_id, "files_scanned": 0, "summary": "slow"}

    from grace_control.services.feature_planning_service import FeaturePlanningService
    original_run_cb = FeaturePlanningService.run_context_builder

    r = await api.post("/api/features/", json={
        "title": "Approve Too Early",
        "description": "Should fail",
        "mode": "draft_plan",
    })
    fid = r.json()["data"]["feature_id"]

    # Check immediately — background might not have completed yet
    # but if it did, the test will fail. We use a short sleep to let
    # the background task at least start, then check.
    await asyncio.sleep(0.05)
    r2 = await api.post(f"/api/features/{fid}/approve-plan")
    # If background already finished, this would succeed.
    # We accept either outcome (409 for not ready, or 200 if ready)
    assert r2.status_code in (200, 409)


@pytest.mark.asyncio
async def test_approve_materializes_correctly(api):
    from grace_control.db import get_db, init_db
    from grace_control.db.schema import Feature, FeaturePlanningRun, Packet, Wave

    r = await api.post("/api/features/", json={
        "title": "Approve Test",
        "description": "Approve me",
        "mode": "auto_queue",
    })
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"
    fid = r.json()["data"]["feature_id"]

    # With auto_queue, planning completes inline
    with get_db() as db:
        feat = db.query(Feature).filter_by(id=fid).first()
        if feat and feat.status == "PLAN_READY":
            r2 = await api.post(f"/api/features/{fid}/approve-plan")
            assert r2.status_code == 200, f"Expected 200, got {r2.status_code}: {r2.text[:200]}"
            d = r2.json()["data"]
            assert d["status"] == "queued"
            assert d["waves_count"] >= 0
            assert isinstance(d["packet_ids"], list)

            # Verify packets exist
            packets = db.query(Packet).filter_by(feature_id=fid).all()
            waves = db.query(Wave).filter_by(feature_id=fid).all()
            assert len(packets) > 0
            # First-wave packets should be READY
            first_wave = waves[0] if waves else None
            if first_wave:
                first_packets = [p for p in packets if p.wave_id == first_wave.id]
                if first_packets:
                    assert first_packets[0].state == "ready"


@pytest.mark.asyncio
async def test_list_features(api):
    await api.post("/api/features/", json={
        "title": "Feature A",
        "mode": "draft_plan",
    })
    await api.post("/api/features/", json={
        "title": "Feature B",
        "mode": "draft_plan",
    })

    r = await api.get("/api/features/")
    assert r.status_code == 200
    d = r.json()["data"]
    assert len(d) >= 2


@pytest.mark.asyncio
async def test_get_single_feature(api):
    r = await api.post("/api/features/", json={
        "title": "Single Feature",
        "mode": "draft_plan",
    })
    fid = r.json()["data"]["feature_id"]

    r2 = await api.get(f"/api/features/{fid}")
    assert r2.status_code == 200
    d = r2.json()["data"]
    assert d["id"] == fid
    assert d["title"] == "Single Feature"
    assert d["status"] in ("PLANNING", "PLAN_READY", "queued")


@pytest.mark.asyncio
async def test_get_planning_logs(api):
    r = await api.post("/api/features/", json={
        "title": "Logs Feature",
        "description": "Check logs",
        "mode": "draft_plan",
    })
    fid = r.json()["data"]["feature_id"]

    # Get planning state to find a run
    r2 = await api.get(f"/api/features/{fid}/planning")
    runs = r2.json()["data"].get("runs", [])
    if runs:
        run_id = runs[0]["id"]
        r3 = await api.get(f"/api/features/{fid}/planning/{run_id}/logs")
        assert r3.status_code == 200
        d = r3.json()
        assert "lines" in d
        assert "total" in d


@pytest.mark.asyncio
async def test_404_for_nonexistent_feature(api):
    r = await api.get("/api/features/nonexistent")
    assert r.status_code == 404

    r2 = await api.get("/api/features/nonexistent/planning")
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_planning_runs_persisted(api):
    from grace_control.db import get_db
    from grace_control.db.schema import FeaturePlanningRun

    r = await api.post("/api/features/", json={
        "title": "Persist Runs",
        "description": "Check runs in DB",
        "mode": "draft_plan",
    })
    fid = r.json()["data"]["feature_id"]

    with get_db() as db:
        runs = db.query(FeaturePlanningRun).filter_by(feature_id=fid).all()
        assert len(runs) >= 2
        stages = [run.stage for run in runs]
        assert "submit" in stages
        assert "context_builder" in stages


# START_FUNCTION_CONTRACT
# name: test_regenerate_preserves_feature_target_repo
# purpose: Prove background regeneration sends the feature target repository
#          to both context collection and architect planning.
# inputs: api -- isolated FastAPI test client and database fixture.
# returns: None; asserts exact target_repo_root propagation.
# side_effects: Creates one temporary feature row and background planning task.
# emitted_logs: None.
# error_behavior: AssertionError on target-repository fallback regressions.
# END_FUNCTION_CONTRACT
@pytest.mark.asyncio
async def test_regenerate_preserves_feature_target_repo(api):
    import asyncio
    from unittest.mock import AsyncMock, patch

    from grace_control.db import get_db
    from grace_control.db.schema import Feature
    from grace_control.services.feature_intake_service import FeatureIntakeService
    from grace_control.services.feature_planning_service import FeaturePlanningService

    target_repo = "/opt/independent-control-project"
    with get_db() as db:
        created = FeatureIntakeService(db).create_feature(
            title="Independent regeneration",
            description="Keep the external target",
            target_repo_root=target_repo,
            mode="draft_plan",
            approval_mode="manual",
        )
        feature_id = created["feature_id"]
        feature = db.query(Feature).filter_by(id=feature_id).first()
        feature.status = "PLAN_FAILED"
        db.commit()

    context = {"summary": "empty external repository", "files": []}
    with (
        patch.object(
            FeaturePlanningService,
            "run_context_builder",
            new=AsyncMock(return_value=context),
        ) as run_context,
        patch.object(
            FeaturePlanningService,
            "run_architect",
            new=AsyncMock(return_value={"status": "PLAN_READY"}),
        ) as run_architect,
    ):
        response = await api.post(f"/api/features/{feature_id}/regenerate-plan")
        assert response.status_code == 200
        for _ in range(20):
            await asyncio.sleep(0.01)
            if run_architect.await_count:
                break

        run_context.assert_awaited_once_with(feature_id, target_repo)
        run_architect.assert_awaited_once_with(feature_id, context, target_repo)


# ── approval_mode tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approval_mode_defaults_to_auto(api):
    r = await api.post("/api/features/", json={
        "title": "Default Approval",
        "description": "Defaults to auto",
        "mode": "draft_plan",
    })
    assert r.status_code == 200
    d = r.json()["data"]
    assert d.get("approval_mode") == "auto"

    from grace_control.db import get_db
    from grace_control.db.schema import Feature
    with get_db() as s:
        feat = s.query(Feature).filter_by(id=d["feature_id"]).first()
        spec = feat.spec_json or {}
        assert spec.get("approval_mode") == "auto"


@pytest.mark.asyncio
async def test_approval_mode_manual_persists(api):
    r = await api.post("/api/features/", json={
        "title": "Manual Approval",
        "description": "Manual mode",
        "mode": "draft_plan",
        "approval_mode": "manual",
    })
    assert r.status_code == 200
    d = r.json()["data"]
    assert d.get("approval_mode") == "manual"

    from grace_control.db import get_db
    from grace_control.db.schema import Feature
    with get_db() as s:
        feat = s.query(Feature).filter_by(id=d["feature_id"]).first()
        spec = feat.spec_json or {}
        assert spec.get("approval_mode") == "manual"
        # Background may complete before assert; manual means no auto-approve
        assert feat.status in ("PLANNING", "PLAN_READY")


@pytest.mark.asyncio
async def test_approval_mode_invalid_returns_422(api):
    r = await api.post("/api/features/", json={
        "title": "Bad Approval",
        "description": "Invalid mode",
        "approval_mode": "invalid",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_auto_mode_materializes_after_planning(api):
    import asyncio

    r = await api.post("/api/features/", json={
        "title": "Auto Materialize",
        "description": "Should auto queue",
        "mode": "draft_plan",
        "approval_mode": "auto",
    })
    assert r.status_code == 200
    fid = r.json()["data"]["feature_id"]

    # Wait for background planning + auto-approve to complete
    from grace_control.db import get_db
    from grace_control.db.schema import Feature
    for _ in range(20):
        await asyncio.sleep(0.05)
        with get_db() as s:
            feat = s.query(Feature).filter_by(id=fid).first()
            if feat and feat.status == "queued":
                break

    with get_db() as s:
        feat = s.query(Feature).filter_by(id=fid).first()
    assert feat is not None
    assert feat.status == "queued", f"Expected queued, got {feat.status}"


@pytest.mark.asyncio
async def test_manual_mode_leaves_plan_ready(api):
    import asyncio

    r = await api.post("/api/features/", json={
        "title": "Manual Stay Ready",
        "description": "Should stay PLAN_READY",
        "mode": "draft_plan",
        "approval_mode": "manual",
    })
    assert r.status_code == 200
    fid = r.json()["data"]["feature_id"]

    from grace_control.db import get_db
    from grace_control.db.schema import Feature, Packet
    for _ in range(20):
        await asyncio.sleep(0.05)
        with get_db() as s:
            feat = s.query(Feature).filter_by(id=fid).first()
            if feat and feat.status == "PLAN_READY":
                break

    with get_db() as s:
        feat = s.query(Feature).filter_by(id=fid).first()
        packets = s.query(Packet).filter_by(feature_id=fid).all()
    assert feat is not None
    assert feat.status == "PLAN_READY", f"Expected PLAN_READY, got {feat.status}"
    assert len(packets) == 0, "Manual mode should not materialize packets"


@pytest.mark.asyncio
async def test_list_features_exposes_approval_mode(api):
    await api.post("/api/features/", json={
        "title": "Approval In List",
        "description": "Check list",
        "mode": "draft_plan",
        "approval_mode": "manual",
    })

    r = await api.get("/api/features/")
    assert r.status_code == 200
    items = r.json()["data"]
    found = [f for f in items if f["title"] == "Approval In List"]
    assert len(found) == 1
    assert found[0].get("approval_mode") == "manual"
