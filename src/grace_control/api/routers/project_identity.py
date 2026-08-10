# ############################################################################
# AI_HEADER: project_identity_router — project-local identity API endpoint
# ROLE: Exposes the current runtime identity to an Admin Hub through the
#       project-local API boundary. It does not select or switch projects.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Serve non-secret project identity/readiness metadata for Hub
#          registry/runtime comparison.
# inputs: HTTP GET request.
# returns: JSON identity DTO for this runtime process.
# side_effects: Reads project-local configuration through a config service.
# emitted_logs: None.
# error_behavior: Propagates malformed local configuration errors.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /api/admin/project-identity
# END_MODULE_MAP

from __future__ import annotations

from fastapi import APIRouter

from grace_control.config.runtime_identity import get_runtime_identity
from grace_control.core.structured_logger import GraceLogger

router = APIRouter()
_log = GraceLogger("project_identity_router")


# START_BLOCK_IDENTITY
# START_FUNCTION_CONTRACT
# name: project_identity
# purpose: Return this project-local runtime's non-secret identity/readiness.
# inputs: None.
# returns: JSON identity DTO.
# side_effects: Reads local configuration through get_runtime_identity.
# emitted_logs: None.
# error_behavior: Propagates malformed local configuration errors.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/project-identity")
def project_identity() -> dict:
    return get_runtime_identity()


# END_BLOCK_IDENTITY
