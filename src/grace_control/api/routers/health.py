# ############################################################################
# AI_HEADER: api_routers_health
# ROLE: Health router — /health.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Serve the /health probe. Excluded from the OpenAPI schema because
#          it is consumed by orchestrators (k8s, load balancers), not clients.
# inputs: none.
# returns: dict — see core.health.check_health.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Whatever check_health raises / returns.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /health
# END_MODULE_MAP

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from grace_control.core.health import check_health

router = APIRouter(tags=["health"])


@router.get("/health/liveness", include_in_schema=False)
async def liveness() -> dict:
    return {"status": "ok"}


@router.get("/health/readiness", include_in_schema=False)
async def readiness() -> dict:
    from grace_control.db import engine
    if engine is None:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}


@router.get("/health", include_in_schema=False)
async def health() -> dict:
    return await check_health()
