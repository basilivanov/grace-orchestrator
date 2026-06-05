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

from fastapi import APIRouter

from grace_control.core.health import check_health

router = APIRouter(tags=["health"])


# START_FUNCTION_CONTRACT
# name: health
# purpose: HTTP wrapper around core.health.check_health.
# inputs: none.
# returns: dict — health snapshot.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Whatever check_health raises / returns.
# END_FUNCTION_CONTRACT
@router.get("/health", include_in_schema=False)
async def health() -> dict:
    return await check_health()
