# ############################################################################
# AI_HEADER: admin_controls_openapi — safe local OpenAPI control owner
# ROLE: Owns exact same-app OpenAPI operation validation and dispatch while the
#       admin-controls facade retains route registration and compatibility seams.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate and invoke one discovered non-read OpenAPI operation in the
#          current ASGI application with canonical audit and masked output.
# inputs: Authenticated request, bounded path/method/parameter/body payload and
#          explicit facade callbacks.
# returns: Audited JSONResponse with downstream status and safe response data.
# side_effects: One bounded request to the same project ASGI app.
# emitted_logs: Supplied canonical admin audit events.
# error_behavior: Rejected operations, downstream errors and timeouts remain
#                 explicit failed/unknown outcomes.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: local_openapi_control_impl
#   - function: openapi_operation_allowed
#   - function: decode_response
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_security import mask_operator_data
from grace_control.services.admin_mutation_service import UNKNOWN_OUTCOME_MESSAGE

_log = GraceLogger("admin_controls_openapi")

_DANGEROUS_OPENAPI_PREFIXES = (
    "/api/admin/control",
    "/api/admin/lifecycle",
    "/api/packets/claim",
    "/api/admin/shutdown",
)


# START_BLOCK_OPENAPI
# START_FUNCTION_CONTRACT
# name: local_openapi_control_impl
# purpose: Validate one exact local OpenAPI mutation and invoke it through ASGI.
# inputs: Authenticated request, bounded body and facade safety/audit callbacks.
# returns: Masked downstream status/body plus canonical audit identity.
# side_effects: Performs one bounded request to the current ASGI app.
# emitted_logs: Supplied admin_action_requested/completed/failed events.
# error_behavior: Rejected paths return 400; downstream failure is 502 and a
#                 timeout returns the explicit unknown outcome 504.
# END_FUNCTION_CONTRACT
async def local_openapi_control_impl(
    request: Request,
    body: dict[str, Any],
    *,
    require_control_request: Callable[[Request], Any],
    audit_identity: Callable[..., dict[str, Any]],
    audit_or_failure: Callable[..., JSONResponse | None],
    confirmation_allowed: Callable[..., bool],
    openapi_operation_allowed: Callable[[Request, str, str], bool],
    materialize_openapi_request: Callable[..., tuple[str | None, dict[str, Any]]],
    decode_response: Callable[[httpx.Response], dict[str, Any]],
    mask_data: Callable[[Any], Any] = mask_operator_data,
    unknown_outcome_message: str = UNKNOWN_OUTCOME_MESSAGE,
) -> JSONResponse:
    require_control_request(request)
    audit = audit_identity(body, request, action="openapi", entity_type="api_operation")
    path = str(body.get("path") or "")
    method = str(body.get("method") or "").upper()
    if failure := audit_or_failure(
        "admin_action_requested", audit, reason="OpenAPI mutation requested", phase="before mutation",
    ):
        return failure
    if not confirmation_allowed("openapi", audit["project_key"], "api_operation", path, body.get("confirmation")):
        failure = {
            **audit, "ok": False, "result": "failed",
            "error_code": "CONFIRMATION_REQUIRED", "retry_allowed": False,
        }
        if audit_failure := audit_or_failure(
            "admin_action_failed", audit, reason="OpenAPI confirmation was missing or invalid", phase="failure outcome",
        ):
            return audit_failure
        return JSONResponse(status_code=400, content=failure)
    if not openapi_operation_allowed(request, path, method):
        failure = {
            **audit, "ok": False, "result": "failed",
            "error_code": "API_PATH_OR_METHOD_REJECTED", "retry_allowed": False,
        }
        if audit_failure := audit_or_failure(
            "admin_action_failed", audit, reason="OpenAPI operation rejected", phase="failure outcome",
        ):
            return audit_failure
        return JSONResponse(status_code=400, content=failure)
    headers: dict[str, str] = {"x-grace-admin-request-id": audit["request_id"]}
    for name in ("authorization", "x-grace-api-token"):
        value = request.headers.get(name)
        if value:
            headers[name] = value
    params = body.get("parameters") if isinstance(body.get("parameters"), Mapping) else {}
    content_body = body.get("body") if isinstance(body.get("body"), Mapping) else None
    materialized_path, query_params = materialize_openapi_request(request.app, path, method, params)
    if not materialized_path:
        failure = {
            **audit, "ok": False, "result": "failed",
            "error_code": "API_PATH_PARAM_REQUIRED", "retry_allowed": False,
        }
        if audit_failure := audit_or_failure(
            "admin_action_failed", audit, reason="OpenAPI path parameters rejected", phase="failure outcome",
        ):
            return audit_failure
        return JSONResponse(status_code=400, content=failure)
    try:
        transport = httpx.ASGITransport(app=request.app)
        async with httpx.AsyncClient(transport=transport, base_url=str(request.base_url)) as client:
            response = await client.request(
                method,
                materialized_path,
                params=query_params,
                json=content_body,
                headers=headers,
            )
        downstream = decode_response(response)
    except (httpx.TimeoutException, httpx.NetworkError):
        failure = {
            **audit, "ok": False, "result": "unknown_after_timeout",
            "error": unknown_outcome_message, "retry_allowed": False,
        }
        if audit_failure := audit_or_failure(
            "admin_action_failed", audit, reason=unknown_outcome_message,
            phase="failure outcome", outcome=failure,
        ):
            return audit_failure
        return JSONResponse(status_code=504, content=failure)
    except Exception as exc:
        failure = {
            **audit, "ok": False, "result": "failed",
            "error": mask_data(str(exc)[:240]), "retry_allowed": False,
        }
        if audit_failure := audit_or_failure(
            "admin_action_failed", audit, reason="OpenAPI downstream failure",
            phase="failure outcome", outcome=failure,
        ):
            return audit_failure
        return JSONResponse(status_code=502, content=failure)
    success = 200 <= response.status_code < 300
    result = {
        **audit,
        "ok": success,
        "result": "success" if success else "failed",
        "status": response.status_code,
        "response": downstream,
        "retry_allowed": False,
    }
    if audit_failure := audit_or_failure(
        "admin_action_completed" if success else "admin_action_failed",
        audit,
        reason="OpenAPI downstream completed" if success else "OpenAPI downstream failed",
        result=result["result"],
        phase="after mutation",
        outcome=result,
    ):
        return audit_failure
    return JSONResponse(status_code=response.status_code if not success else 200, content=result)


# START_FUNCTION_CONTRACT
# name: openapi_operation_allowed
# purpose: Validate an exact discovered same-project OpenAPI operation and
#          reject dangerous generic control paths and read-only methods.
# inputs: request, path, HTTP method and dangerous-prefix policy.
# returns: True only for a discovered safe non-read operation.
# side_effects: Reads the current app OpenAPI document.
# error_behavior: Malformed or missing documents return False.
# END_FUNCTION_CONTRACT
def openapi_operation_allowed(
    request: Request,
    path: str,
    method: str,
    *,
    dangerous_prefixes: Collection[str] = _DANGEROUS_OPENAPI_PREFIXES,
) -> bool:
    if not path.startswith("/") or path.startswith("//") or "\\" in path or "#" in path:
        return False
    path_only = path.split("?", 1)[0]
    if any(path_only.startswith(prefix) for prefix in dangerous_prefixes):
        return False
    document = request.app.openapi()
    operations = document.get("paths", {}).get(path_only)
    return isinstance(operations, Mapping) and method.casefold() in operations and method.casefold() not in {
        "get", "head", "options",
    }


# START_FUNCTION_CONTRACT
# name: decode_response
# purpose: Decode and recursively mask a same-app OpenAPI response body and
#          bounded safe headers.
# inputs: HTTPX response.
# returns: Safe status/body/headers mapping.
# side_effects: None.
# error_behavior: Non-JSON response becomes bounded masked text.
# END_FUNCTION_CONTRACT
def decode_response(response: httpx.Response) -> dict[str, Any]:
    try:
        body: Any = response.json()
    except (ValueError, TypeError):
        body = response.text[:4000]
    return {
        "status": response.status_code,
        "body": mask_operator_data(body),
        "headers": mask_operator_data({
            key: value for key, value in response.headers.items()
            if key.casefold() in {"content-type", "content-length", "date"}
        }),
    }


# END_BLOCK_OPENAPI
