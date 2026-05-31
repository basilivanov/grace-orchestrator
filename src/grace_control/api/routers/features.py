# ############################################################################
# AI_HEADER: features_router
# ROLE: FastAPI router for /api/features/ endpoints.
# ############################################################################

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException

from grace_control.db import get_db
from grace_control.db.schema import Feature

router = APIRouter()


@router.get("/")
async def list_features() -> dict:
    with get_db() as db:
        features = db.query(Feature).all()
        return {
            "data": [
                {
                    "id": f.id,
                    "slug": f.slug,
                    "title": f.title,
                    "description": f.description or "",
                    "status": f.status,
                    "created_at": f.created_at.isoformat() + "Z",
                    "updated_at": f.updated_at.isoformat() + "Z",
                }
                for f in features
            ],
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


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
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
