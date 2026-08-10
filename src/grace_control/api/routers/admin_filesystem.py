# ############################################################################
# AI_HEADER: admin_filesystem_router — safe project-local filesystem API
# ROLE: Exposes named-root metadata and bounded reads through
#       SafeFilesystemService. The browser supplies no absolute root and the
#       router never performs direct Path reads.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Bind safe filesystem service methods to project-local Admin routes.
# inputs: HTTP request, named root, relative path and bounded read parameters.
# returns: JSON metadata/content or typed non-500 error responses.
# side_effects: Reads only service-approved operational roots.
# emitted_logs: None.
# error_behavior: FilesystemReadError becomes its declared HTTP status.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /api/admin/fs/roots
#       - GET /api/admin/fs/list
#       - GET /api/admin/fs/stat
#       - GET /api/admin/fs/file
#       - GET /api/admin/fs/tail
# END_MODULE_MAP

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.safe_filesystem_service import (
    FilesystemReadError,
    SafeFilesystemService,
)

router = APIRouter()
_log = GraceLogger("admin_filesystem_router")


# START_BLOCK_ROUTES
def _service(request: Request) -> SafeFilesystemService:
    state = request.app.__dict__["state"]
    service = getattr(state, "project_filesystem_service", None)
    if service is None:
        raise FilesystemReadError("SERVICE_UNAVAILABLE", 503, "filesystem service is unavailable")
    return service


def _error(exc: FilesystemReadError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.to_dict()})


# START_FUNCTION_CONTRACT
# name: roots
# purpose: List server-resolved filesystem root identifiers.
# inputs: request — FastAPI request carrying the project-local service.
# returns: JSON root metadata.
# side_effects: Reads root directory metadata.
# emitted_logs: None.
# error_behavior: 503 if the service is unavailable.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/fs/roots")
def roots(request: Request) -> Any:
    try:
        return {"roots": _service(request).list_roots()}
    except FilesystemReadError as exc:
        return _error(exc)


# START_FUNCTION_CONTRACT
# name: list_entries
# purpose: List bounded entries beneath one named root and relative path.
# inputs: request, root and optional relative path.
# returns: JSON directory listing.
# side_effects: Reads directory metadata.
# emitted_logs: None.
# error_behavior: Typed non-500 filesystem errors.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/fs/list")
def list_entries(
    request: Request,
    root: str = Query(...),
    path: str = Query(""),
) -> Any:
    try:
        return _service(request).list_entries(root, path)
    except FilesystemReadError as exc:
        return _error(exc)


# START_FUNCTION_CONTRACT
# name: stat
# purpose: Return metadata for one named-root relative resource.
# inputs: request, root and relative path.
# returns: JSON file/directory metadata.
# side_effects: Reads path metadata.
# emitted_logs: None.
# error_behavior: Typed non-500 filesystem errors.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/fs/stat")
def stat(
    request: Request,
    root: str = Query(...),
    path: str = Query(""),
) -> Any:
    try:
        return _service(request).stat(root, path)
    except FilesystemReadError as exc:
        return _error(exc)


# START_FUNCTION_CONTRACT
# name: file
# purpose: Return a bounded text or binary-safe file preview.
# inputs: request, root, relative path and optional max_bytes.
# returns: JSON content DTO.
# side_effects: Reads a bounded file prefix.
# emitted_logs: None.
# error_behavior: Typed non-500 filesystem errors.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/fs/file")
def file(
    request: Request,
    root: str = Query(...),
    path: str = Query(...),
    max_bytes: int | None = Query(None, gt=0),
) -> Any:
    try:
        return _service(request).read_file(root, path, max_bytes=max_bytes)
    except FilesystemReadError as exc:
        return _error(exc)


# START_FUNCTION_CONTRACT
# name: tail
# purpose: Return a bounded text tail or binary-safe tail payload.
# inputs: request, root, relative path, lines and optional max_bytes.
# returns: JSON tail content DTO.
# side_effects: Reads a bounded file suffix.
# emitted_logs: None.
# error_behavior: Typed non-500 filesystem errors.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/fs/tail")
def tail(
    request: Request,
    root: str = Query(...),
    path: str = Query(...),
    lines: int = Query(200, gt=0),
    max_bytes: int | None = Query(None, gt=0),
) -> Any:
    try:
        return _service(request).tail_file(root, path, lines=lines, max_bytes=max_bytes)
    except FilesystemReadError as exc:
        return _error(exc)


# END_BLOCK_ROUTES
