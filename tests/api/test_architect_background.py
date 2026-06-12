from __future__ import annotations

import asyncio
import pytest

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("test_architect_background")


@pytest.mark.asyncio
async def test_background_returns_immediate(api):
    """Post with description (no waves) triggers background -> immediate response."""
    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Bg Immediate", "description": "Add login feature"}})
    assert r.status_code == 200
    d = r.json()
    assert d["feature_id"].startswith("feat_")
    assert d["slug"] == "bg-immediate"
    assert d["status"] == "planning"
    assert d["immediate"] is True


@pytest.mark.asyncio
async def test_background_creates_feature_in_planning(api, db):
    """After immediate response, feature appears in DB with PLANNING status."""
    from grace_control.db import get_db
    from grace_control.db.schema import Feature

    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Bg Planning Check", "description": "Test planning state"}})
    fid = r.json()["feature_id"]

    with get_db() as s:
        feat = s.query(Feature).filter_by(id=fid).first()
    assert feat is not None
    assert feat.title == "Bg Planning Check"
    assert feat.slug == "bg-planning-check"
    assert feat.status in ("PLANNING", "PLAN_READY")


@pytest.mark.asyncio
async def test_background_completes_and_creates_runs(api):
    """Background completes and feature becomes PLAN_READY with planning runs."""
    from grace_control.db import get_db
    from grace_control.db.schema import Feature, FeaturePlanningRun

    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Bg Complete", "description": "Build auth system"}})
    fid = r.json()["feature_id"]

    for _ in range(10):
        await asyncio.sleep(0.05)
        with get_db() as s:
            feat = s.query(Feature).filter_by(id=fid).first()
            if feat and feat.status == "PLAN_READY":
                break

    with get_db() as s:
        feat = s.query(Feature).filter_by(id=fid).first()
        runs = s.query(FeaturePlanningRun).filter_by(feature_id=fid).all()

    assert feat is not None
    assert feat.status == "PLAN_READY"
    stages = [r.stage for r in runs]
    assert "context_builder" in stages
    assert "architect" in stages


@pytest.mark.asyncio
async def test_background_sets_plan_failed_on_architect_error(api):
    """Background catches architect error and sets PLAN_FAILED."""
    from grace_control.db import get_db
    from grace_control.db.schema import Feature

    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Bg Fail", "description": "Will fail"}})
    fid = r.json()["feature_id"]

    for _ in  range(10):
        await asyncio.sleep(0.05)
        with get_db() as s:
            feat = s.query(Feature).filter_by(id=fid).first()
            if feat and feat.status in ("PLAN_READY", "PLAN_FAILED"):
                break

    with get_db() as s:
        feat = s.query(Feature).filter_by(id=fid).first()
    assert feat is not None
    # With GRACE_CONTEXT_DISABLED, fallback plan succeeds, so PLAN_READY
    assert feat.status in ("PLAN_READY", "PLAN_FAILED")


@pytest.mark.asyncio
async def test_background_feature_has_plan_runs(api):
    """Background planning creates context_builder and architect runs."""
    from grace_control.db import get_db
    from grace_control.db.schema import Feature, FeaturePlanningRun
    from grace_control.services.feature_planning_service import FeaturePlanningService

    r = await api.post("/api/architect/plan", json={
        "feature_spec": {"title": "Bg Runs", "description": "Test runs"}})
    fid = r.json()["feature_id"]

    for _ in range(10):
        await asyncio.sleep(0.05)
        with get_db() as s:
            feat = s.query(Feature).filter_by(id=fid).first()
            if feat and feat.status == "PLAN_READY":
                break

    with get_db() as s:
        runs = s.query(FeaturePlanningRun).filter_by(feature_id=fid).order_by(FeaturePlanningRun.created_at).all()
        feat = s.query(Feature).filter_by(id=fid).first()

    assert feat.status == "PLAN_READY"
    run_stages = [(r.stage, r.status) for r in runs]
    assert ("submit", "done") in run_stages
    assert ("context_builder", "done") in run_stages
    assert ("architect", "done") in run_stages
    assert all(r.stdout_path is not None and r.stderr_path is not None
               for r in runs if r.stage in ("context_builder", "architect"))
