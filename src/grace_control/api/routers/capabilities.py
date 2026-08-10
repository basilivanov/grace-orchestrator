# ############################################################################
# AI_HEADER: capabilities_router — project-local optional feature discovery
# ROLE: Exposes CapabilityService through the Admin API so the Hub can discover
#       optional project features without assuming every table or endpoint exists.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Serve the project-local capability document.
# inputs: HTTP GET request.
# returns: JSON capabilities document with unavailable optional features.
# side_effects: Reads the local database schema.
# emitted_logs: None.
# error_behavior: Returns HTTP 200 with unavailable flags when optional schema
#                 components are absent.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /api/admin/capabilities
#       - GET /api/capabilities
# END_MODULE_MAP

from __future__ import annotations

from fastapi import APIRouter

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.services.capability_service import CapabilityService

router = APIRouter()
_service = CapabilityService()
_log = GraceLogger("capabilities_router")


# START_BLOCK_ROUTES
# START_FUNCTION_CONTRACT
# name: capabilities
# purpose: Return optional project-local feature availability.
# inputs: None.
# returns: JSON capability document.
# side_effects: Inspects the local database schema.
# emitted_logs: None.
# error_behavior: Missing optional tables are reported as unavailable.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/capabilities")
@router.get("/api/capabilities")
def capabilities() -> dict:
    with get_db() as db:
        return _service.document(db)


# END_BLOCK_ROUTES
