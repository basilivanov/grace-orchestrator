# ############################################################################
# AI_HEADER: admin_git_router — safe project-local Git read API
# ROLE: Binds AdminGitReadService to read-only repository, worktree, commit,
#       changed-file, diff and tracked-file endpoints. Repository selection is
#       server-side and never comes from a browser query parameter.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Expose validated, bounded Git read primitives for one project.
# inputs: HTTP request plus validated ref/path/limit query values.
# returns: JSON Git DTOs or typed non-500 read errors.
# side_effects: Runs read-only Git commands through the service boundary.
# emitted_logs: None.
# error_behavior: GitReadError becomes its declared HTTP status.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - router: APIRouter
#     routes:
#       - GET /api/admin/git/repository
#       - GET /api/admin/git/status
#       - GET /api/admin/git/worktrees
#       - GET /api/admin/git/commits
#       - GET /api/admin/git/changed-files
#       - GET /api/admin/git/diff-stat
#       - GET /api/admin/git/diff
#       - GET /api/admin/git/tracked-files
#       - GET /api/admin/git/show
# END_MODULE_MAP

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_git_read_service import (
    AdminGitReadService,
    GitReadError,
)

router = APIRouter()
_log = GraceLogger("admin_git_router")


# START_BLOCK_ROUTES
def _service(request: Request) -> AdminGitReadService:
    state = request.app.__dict__["state"]
    service = getattr(state, "project_git_read_service", None)
    if service is None:
        raise GitReadError("SERVICE_UNAVAILABLE", 503, "Git read service is unavailable")
    return service


def _error(exc: GitReadError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.to_dict()})


# START_FUNCTION_CONTRACT
# name: repository
# purpose: Return repository identity, branches, remote and clean/dirty status.
# inputs: request — FastAPI request carrying the project-local Git service.
# returns: JSON repository DTO.
# side_effects: Runs read-only Git commands.
# emitted_logs: None.
# error_behavior: Typed non-500 Git errors.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/git/repository")
@router.get("/api/admin/git/status")
def repository(request: Request) -> Any:
    try:
        result = _service(request).repository()
        return {**result, "data": result}
    except GitReadError as exc:
        return _error(exc)


# START_FUNCTION_CONTRACT
# name: worktrees
# purpose: Return Git worktree metadata from porcelain output.
# inputs: request.
# returns: JSON worktree list.
# side_effects: Runs one read-only Git command.
# emitted_logs: None.
# error_behavior: Typed non-500 Git errors.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/git/worktrees")
def worktrees(request: Request) -> Any:
    try:
        result = _service(request).worktrees()
        return {"worktrees": result, "data": result}
    except GitReadError as exc:
        return _error(exc)


# START_FUNCTION_CONTRACT
# name: commits
# purpose: Return bounded commits for a validated ref.
# inputs: request, optional ref, limit 1..200.
# returns: JSON commit list.
# side_effects: Runs one read-only Git command.
# emitted_logs: None.
# error_behavior: Typed non-500 Git errors.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/git/commits")
def commits(
    request: Request,
    ref: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> Any:
    try:
        result = _service(request).commits(ref=ref, limit=limit)
        return {"commits": result, "data": result}
    except (GitReadError, ValueError) as exc:
        return _error(exc if isinstance(exc, GitReadError) else GitReadError("INVALID_REF", 400, str(exc)))


# START_FUNCTION_CONTRACT
# name: changed_files
# purpose: Return changed files between a validated ref and HEAD.
# inputs: request, optional ref.
# returns: JSON changed-file list.
# side_effects: Runs one read-only Git diff command.
# emitted_logs: None.
# error_behavior: Typed non-500 Git errors.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/git/changed-files")
def changed_files(
    request: Request,
    ref: str | None = Query(None),
) -> Any:
    try:
        result = _service(request).changed_files(ref=ref)
        return {"changed_files": result, "data": result}
    except (GitReadError, ValueError) as exc:
        return _error(exc if isinstance(exc, GitReadError) else GitReadError("INVALID_REF", 400, str(exc)))


# START_FUNCTION_CONTRACT
# name: diff_stat
# purpose: Return bounded diff statistics for a validated ref/path.
# inputs: request, optional ref/path.
# returns: JSON diff-stat DTO.
# side_effects: Runs one read-only Git diff command.
# emitted_logs: None.
# error_behavior: Typed non-500 Git errors.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/git/diff-stat")
def diff_stat(
    request: Request,
    ref: str | None = Query(None),
    path: str | None = Query(None),
) -> Any:
    try:
        result = _service(request).diff_stat(ref=ref, path=path)
        return {**result, "data": result}
    except (GitReadError, ValueError) as exc:
        return _error(exc if isinstance(exc, GitReadError) else GitReadError("INVALID_INPUT", 400, str(exc)))


# START_FUNCTION_CONTRACT
# name: diff
# purpose: Return bounded unified diff for a validated ref/path.
# inputs: request, optional ref/path.
# returns: JSON unified-diff DTO.
# side_effects: Runs one read-only Git diff command.
# emitted_logs: None.
# error_behavior: Typed non-500 Git errors.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/git/diff")
def diff(
    request: Request,
    ref: str | None = Query(None),
    path: str | None = Query(None),
) -> Any:
    try:
        result = _service(request).diff(ref=ref, path=path)
        return {**result, "data": result}
    except (GitReadError, ValueError) as exc:
        return _error(exc if isinstance(exc, GitReadError) else GitReadError("INVALID_INPUT", 400, str(exc)))


# START_FUNCTION_CONTRACT
# name: tracked_files
# purpose: Return bounded Git-tracked paths under an optional safe prefix.
# inputs: request, optional relative path.
# returns: JSON tracked-file DTO.
# side_effects: Runs one read-only Git command.
# emitted_logs: None.
# error_behavior: Typed non-500 Git errors.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/git/tracked-files")
def tracked_files(
    request: Request,
    path: str | None = Query(None),
) -> Any:
    try:
        result = _service(request).tracked_files(path=path)
        return {**result, "data": result}
    except (GitReadError, ValueError) as exc:
        return _error(exc if isinstance(exc, GitReadError) else GitReadError("INVALID_PATH", 400, str(exc)))


# START_FUNCTION_CONTRACT
# name: show_file
# purpose: Read a bounded Git-tracked file at a validated ref/path.
# inputs: request, ref, path and optional max_bytes.
# returns: JSON text/binary-safe file DTO.
# side_effects: Runs one read-only Git show command.
# emitted_logs: None.
# error_behavior: Typed non-500 Git errors.
# END_FUNCTION_CONTRACT
@router.get("/api/admin/git/show")
@router.get("/api/admin/git/file")
def show_file(
    request: Request,
    ref: str = Query(...),
    path: str = Query(...),
    max_bytes: int | None = Query(None, gt=0),
) -> Any:
    try:
        result = _service(request).show_file(ref=ref, path=path, max_bytes=max_bytes)
        return {**result, "data": result}
    except (GitReadError, ValueError) as exc:
        return _error(exc if isinstance(exc, GitReadError) else GitReadError("INVALID_INPUT", 400, str(exc)))


# END_BLOCK_ROUTES
