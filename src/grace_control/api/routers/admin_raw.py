# ############################################################################
# AI_HEADER: admin_raw_router — packet/run/stage diagnostic drill-down
# ROLE: Exposes complete project-local raw read models through the existing
#       Admin namespace. Stage output columns are returned as logical resources;
#       physical reads remain behind the safe filesystem service.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Bind AdminRawReadService to packet/run/stage read-only endpoints.
# inputs: Entity IDs and the local DB session.
# returns: Complete JSON diagnostic DTOs.
# side_effects: Reads project-local ORM rows only.
# emitted_logs: None.
# error_behavior: 404 for missing packet/run/stage.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /api/admin/packet/{packet_id}/raw
#       - GET /api/admin/packet/{packet_id}/runs/{run_id}/raw
#       - GET /api/admin/stage/{stage_run_id}/raw
#       - GET /api/admin/stages/{stage_run_id}
# END_MODULE_MAP

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from grace_control.core.structured_logger import GraceLogger
from grace_control.db import get_db
from grace_control.services.admin_raw_read_service import AdminRawReadService

router = APIRouter()
_service = AdminRawReadService()
_log = GraceLogger("admin_raw_router")


# START_BLOCK_ROUTES
# START_FUNCTION_CONTRACT
# name: packet_raw
# purpose: Return complete raw packet spec, runs, stages and recovery data.
# inputs: packet_id (str).
# returns: Complete packet diagnostic DTO.
# side_effects: Reads the local database.
# emitted_logs: None.
# error_behavior: 404 when packet is missing.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/packet/{packet_id}/raw")
def packet_raw(packet_id: str) -> dict:
    with get_db() as db:
        result = _service.packet_raw(db, packet_id)
    if result is None:
        raise HTTPException(status_code=404, detail="packet not found")
    return result


# START_FUNCTION_CONTRACT
# name: run_raw
# purpose: Return persisted prompt/command/evidence metadata and full result JSON.
# inputs: packet_id (str), run_id (str).
# returns: Complete run diagnostic DTO.
# side_effects: Reads the local database.
# emitted_logs: None.
# error_behavior: 404 when run is missing or belongs to another packet.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/packet/{packet_id}/runs/{run_id}/raw")
def run_raw(packet_id: str, run_id: str) -> dict:
    with get_db() as db:
        result = _service.run_raw(db, packet_id, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="run not found")
    return result


# START_FUNCTION_CONTRACT
# name: stage_raw
# purpose: Return StageRun metadata and logical output resources.
# inputs: stage_run_id (str).
# returns: Complete stage diagnostic DTO.
# side_effects: Reads the local database; never reads a stage file.
# emitted_logs: None.
# error_behavior: 404 when stage is missing.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/stage/{stage_run_id}/raw")
@router.get("/api/admin/stages/{stage_run_id}")
def stage_raw(stage_run_id: str) -> dict:
    with get_db() as db:
        result = _service.stage_raw(db, stage_run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="stage not found")
    return result


# END_BLOCK_ROUTES
