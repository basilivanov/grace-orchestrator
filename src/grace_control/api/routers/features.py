# ############################################################################
# AI_HEADER: features_router
# ROLE: FastAPI router for /api/features/ endpoints — intake, planning, approval.
# ############################################################################

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from grace_control.config.settings import settings
from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.db.schema import Feature, FeaturePlanningRun
from grace_control.services.feature_intake_service import FeatureIntakeService
from grace_control.services.feature_planning_service import FeaturePlanningService

_LOG_ROOT = Path(settings.planning_logs_root)
_TAIL_MIN = 10
_TAIL_MAX = 10000

_log = GraceLogger("features_router")

router = APIRouter()


class FeatureCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    target_repo_root: str | None = None
    mode: Literal["draft_plan", "auto_queue"] = "draft_plan"
    origin: str = "business"
    self_improvement: bool = False
    approval_mode: Literal["auto", "manual"] = "auto"


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
                    "approval_mode": f.spec_json.get("approval_mode", "auto") if isinstance(f.spec_json, dict) else "auto",
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
            approval_mode=request.approval_mode,
        )

        feature_id = result["feature_id"]

        if request.mode == "draft_plan":
            _approval_mode = request.approval_mode
            # Background: run context builder + architect
            async def _background_planning():
                try:
                    with get_db() as bg_db:
                        planning = FeaturePlanningService(bg_db)
                        context = await planning.run_context_builder(feature_id, request.target_repo_root)
                        await planning.run_architect(feature_id, context, request.target_repo_root)
                        _log.info("draft_plan_completed", feature_id=feature_id)
                    if _approval_mode == "auto":
                        with get_db() as auto_db:
                            auto_planning = FeaturePlanningService(auto_db)
                            result = auto_planning.approve_plan(feature_id)
                            _log.info("plan_auto_approved", feature_id=feature_id,
                                      approval_mode="auto", status=result.get("status"))
                except Exception as e:
                    _log.error("draft_plan_failed", feature_id=feature_id, error=str(e)[:200])
                    with get_db() as err_db:
                        feat = err_db.query(Feature).filter_by(id=feature_id).first()
                        if feat:
                            feat.status = "PLAN_FAILED"

            asyncio.create_task(_background_planning())
            return {"data": result}

        # auto_queue is the only other valid mode (Literal enforces this)
        planning = FeaturePlanningService(db)
        context = await planning.run_context_builder(feature_id, request.target_repo_root)
        await planning.run_architect(feature_id, context, request.target_repo_root)
        approval = planning.approve_plan(feature_id)
        return {"data": {
            "feature_id": feature_id,
            "status": approval["status"],
            "mode": request.mode,
        }}


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

    # Read approval_mode from feature spec for regenerate
    with get_db() as _reg_db:
        _reg_feat = _reg_db.query(Feature).filter_by(id=feature_id).first()
        _reg_spec = _reg_feat.spec_json or {} if _reg_feat else {}
        _reg_approval_mode = _reg_spec.get("approval_mode", "auto") if isinstance(_reg_spec, dict) else "auto"

    # Start background planning (same as create_feature draft_plan)
    async def _bg_regenerate():
        try:
            with get_db() as bg_db:
                planning = FeaturePlanningService(bg_db)
                context = await planning.run_context_builder(feature_id)
                await planning.run_architect(feature_id, context)
                _log.info("regenerate_completed", feature_id=feature_id)
            if _reg_approval_mode == "auto":
                with get_db() as auto_db:
                    auto_planning = FeaturePlanningService(auto_db)
                    result = auto_planning.approve_plan(feature_id)
                    _log.info("regenerate_auto_approved", feature_id=feature_id,
                              approval_mode="auto", status=result.get("status"))
        except Exception as e:
            _log.error("regenerate_failed", feature_id=feature_id, error=str(e)[:200])
            with get_db() as err_db:
                feat = err_db.query(Feature).filter_by(id=feature_id).first()
                if feat:
                    feat.status = "PLAN_FAILED"

    asyncio.create_task(_bg_regenerate())
    return {"data": state}


# ── Planning logs ──────────────────────────────────────────────────────────

@router.get("/{feature_id}/planning/{run_id}/logs")
async def get_planning_logs(
    feature_id: str,
    run_id: str,
    stream: Literal["stdout", "stderr"] = Query("stdout"),
    tail: int = Query(200, ge=_TAIL_MIN, le=_TAIL_MAX),
) -> dict:
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
    if not path_str:
        return {"lines": [], "total": 0, "source_file": None, "truncated": False}

    resolved = Path(path_str).resolve()
    if not str(resolved).startswith(str(_LOG_ROOT)):
        raise HTTPException(status_code=403, detail="Log path outside allowed root")

    if not resolved.exists():
        return {"lines": [], "total": 0, "source_file": str(resolved), "truncated": False}

    with open(resolved, "r", encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()
        total = len(all_lines)
        lines = all_lines[-tail:]

    return {"lines": lines, "total": total, "source_file": str(resolved), "truncated": total > tail}
