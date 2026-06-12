# ############################################################################
# AI_HEADER: features_router
# ROLE: FastAPI router for /api/features/ endpoints — intake, planning, approval.
# ############################################################################

from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from grace_control.db import get_db
from grace_control.db.schema import Feature, FeaturePlanningRun
from grace_control.services.feature_intake_service import FeatureIntakeService
from grace_control.services.feature_planning_service import FeaturePlanningService

router = APIRouter()


class FeatureCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    target_repo_root: str | None = None
    mode: str = "draft_plan"
    origin: str = "business"
    self_improvement: bool = False


# ── List ───────────────────────────────────────────────────────────────────

@router.get("/")
async def list_features() -> dict:
    with get_db() as db:
        features = db.query(Feature).order_by(Feature.created_at.desc()).all()
        return {
            "data": [
                {
                    "id": f.id,
                    "slug": f.slug,
                    "title": f.title,
                    "description": f.description or "",
                    "status": f.status,
                    "mode": f.spec_json.get("mode", "draft_plan") if isinstance(f.spec_json, dict) else "draft_plan",
                    "origin": f.spec_json.get("origin", "business") if isinstance(f.spec_json, dict) else "business",
                    "created_at": f.created_at.isoformat() + "Z",
                    "updated_at": f.updated_at.isoformat() + "Z",
                }
                for f in features
            ],
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }


# ── Get single ─────────────────────────────────────────────────────────────

@router.get("/{feature_id}")
async def get_feature(feature_id: str) -> dict:
    with get_db() as db:
        f = db.query(Feature).filter_by(id=feature_id).first()
        if not f:
            raise HTTPException(status_code=404, detail="Feature not found")
        return {
            "data": {
                "id": f.id,
                "slug": f.slug,
                "title": f.title,
                "description": f.description or "",
                "status": f.status,
                "spec_json": f.spec_json,
                "created_at": f.created_at.isoformat() + "Z",
                "updated_at": f.updated_at.isoformat() + "Z",
            },
            "timestamp": datetime.now(UTC).isoformat() + "Z",
        }


# ── Create ─────────────────────────────────────────────────────────────────

@router.post("/")
async def create_feature(request: FeatureCreateRequest) -> dict:
    with get_db() as db:
        service = FeatureIntakeService(db)
        result = service.create_feature(
            title=request.title,
            description=request.description,
            target_repo_root=request.target_repo_root,
            mode=request.mode,
            origin=request.origin,
            self_improvement=request.self_improvement,
        )

        if request.mode == "auto_queue":
            planning = FeaturePlanningService(db)
            context = planning.run_context_builder(result["feature_id"])
            planning.run_architect(result["feature_id"], context)
            approval = planning.approve_plan(result["feature_id"])
            return {"data": {
                "feature_id": result["feature_id"],
                "status": approval["status"],
                "mode": request.mode,
            }}

        return {"data": result}


# ── Planning state ─────────────────────────────────────────────────────────

@router.get("/{feature_id}/planning")
async def get_planning_state(feature_id: str) -> dict:
    with get_db() as db:
        service = FeaturePlanningService(db)
        try:
            state = service.get_planning_state(feature_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return {"data": state}


# ── Approve plan ───────────────────────────────────────────────────────────

@router.post("/{feature_id}/approve-plan")
async def approve_plan(feature_id: str) -> dict:
    with get_db() as db:
        service = FeaturePlanningService(db)
        try:
            result = service.approve_plan(feature_id)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg.lower():
                raise HTTPException(status_code=404, detail=msg)
            raise HTTPException(status_code=409, detail=msg)
        return {"data": result}


# ── Regenerate plan ────────────────────────────────────────────────────────

@router.post("/{feature_id}/regenerate-plan")
async def regenerate_plan(feature_id: str) -> dict:
    with get_db() as db:
        service = FeaturePlanningService(db)
        try:
            state = service.regenerate_plan(feature_id)
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg.lower():
                raise HTTPException(status_code=404, detail=msg)
            raise HTTPException(status_code=409, detail=msg)
        return {"data": state}


# ── Planning logs ──────────────────────────────────────────────────────────

@router.get("/{feature_id}/planning/{run_id}/logs")
async def get_planning_logs(feature_id: str, run_id: str, stream: str = "stdout", tail: int = 200) -> dict:
    with get_db() as db:
        service = FeaturePlanningService(db)
        try:
            state = service.get_planning_state(feature_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    runs = state.get("runs", [])
    run = next((r for r in runs if r["id"] == run_id), None)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    path_str = run.get("stdout_path") if stream == "stdout" else run.get("stderr_path")
    if not path_str or not os.path.exists(path_str):
        return {"lines": [], "total": 0, "source_file": path_str, "truncated": False}

    tail = min(tail, 10000)
    with open(path_str, "r", encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()
        total = len(all_lines)
        lines = all_lines[-tail:]

    return {"lines": lines, "total": total, "source_file": path_str, "truncated": total > tail}
