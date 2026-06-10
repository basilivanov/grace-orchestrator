# ############################################################################
# AI_HEADER: api_routers_health
# ROLE: Health router — /health, /health/liveness, /health/readiness, /health/diagnostic.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Serve lightweight and diagnostic health probes.
#
#   GET /health            — lightweight liveness (no DB, no cleanup)
#   GET /health/liveness   — same lightweight liveness alias
#   GET /health/readiness  — DB readiness (200 ready / 503 not ready)
#   GET /health/diagnostic — legacy full diagnostic (workers, queue, leases)
#                            DEB-backed, NOT safe for frequent polling.
#
# Excluded from the OpenAPI schema because consumed by orchestrators.
# inputs: none.
# returns: dict — lightweight or diagnostic depending on route.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns HTTPException 503 on readiness fail.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /health
#       - GET /health/liveness
#       - GET /health/readiness
#       - GET /health/diagnostic
# END_MODULE_MAP

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from grace_control.core.health import check_health

router = APIRouter(tags=["health"])


def _liveness_payload() -> dict:
    return {"status": "ok"}


@router.get("/health/liveness", include_in_schema=False)
async def liveness() -> dict:
    return _liveness_payload()


@router.get("/health/readiness", include_in_schema=False)
async def readiness() -> dict:
    from grace_control.db import engine
    if engine is None:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}


@router.get("/health", include_in_schema=False)
async def health() -> dict:
    return _liveness_payload()


@router.get("/health/diagnostic", include_in_schema=False)
async def health_diagnostic() -> dict:
    return await check_health()
