# ############################################################################
# AI_HEADER: admin_control_local_helpers — local control identity, audit and OpenAPI safety
# ROLE: Supplies the project-local control router with canonical runtime identity,
#       strict audit gates and exact discovered OpenAPI parameter materialization.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Keep local control identity/audit/OpenAPI helpers bounded and
#          reusable without letting browser values select project state.
# inputs: Authenticated FastAPI requests, bounded JSON mappings and an optional
#         event recorder used by deterministic tests.
# returns: Safe identity/audit DTOs and same-app OpenAPI route/query values.
# side_effects: Reads runtime identity and persists canonical Event rows.
# emitted_logs: admin_audit_persist_failed.
# error_behavior: Identity and parameter uncertainty fail closed; strict audit
#                 persistence returns an explicit failure to the caller.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: _local_identity
#   - function: _audit_identity
#   - function: _record_admin_event
#   - function: _audit_failure_response
#   - function: _materialize_openapi_request
# END_MODULE_MAP

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from grace_control.config.runtime_identity import get_runtime_identity
from grace_control.core.event_recorder import record_event as _default_record_event
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_security import mask_operator_data

_log = GraceLogger("admin_control_local_helpers")


# START_BLOCK_IDENTITY
# START_FUNCTION_CONTRACT
# name: _optional_text
# purpose: Normalize an optional scalar JSON value into bounded text.
# inputs: value — arbitrary JSON-compatible value.
# returns: Bounded text or None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Mapping/list values become None.
# END_FUNCTION_CONTRACT
def _optional_text(value: Any) -> str | None:
    if value is None or isinstance(value, (Mapping, list, tuple)):
        return None
    text = str(value).strip()
    return text[:240] if text else None


# START_FUNCTION_CONTRACT
# name: _local_identity
# purpose: Derive the canonical local runtime key and reject a forged body key.
# inputs: body — control body; request — authenticated local request.
# returns: Runtime-local project key.
# side_effects: Reads app-scoped runtime identity or local identity config.
# emitted_logs: None.
# error_behavior: Missing identity raises HTTPException 503; mismatch raises
#                 HTTPException 409 before mutation or audit.
# END_FUNCTION_CONTRACT
def _local_identity(body: Mapping[str, Any], request: Request) -> str:
    state = request.app.__dict__.get("state")
    runtime = getattr(state, "runtime_identity", None)
    if not isinstance(runtime, Mapping):
        try:
            runtime = get_runtime_identity()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="local runtime identity unavailable") from exc
    canonical = _optional_text(runtime.get("project_key"))
    if not canonical or "/" in canonical or "\\" in canonical:
        raise HTTPException(status_code=503, detail="local runtime identity unavailable")
    supplied = _optional_text(body.get("project_key"))
    if supplied and supplied != canonical:
        raise HTTPException(status_code=409, detail="project identity does not match local runtime")
    return canonical


# START_FUNCTION_CONTRACT
# name: _audit_identity
# purpose: Build bounded canonical identity fields for every local admin event.
# inputs: body/request and optional action/entity overrides.
# returns: Audit identity mapping.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Identity mismatch/unavailability propagates HTTPException.
# END_FUNCTION_CONTRACT
def _audit_identity(
    body: Mapping[str, Any],
    request: Request,
    *,
    action: str | None = None,
    entity_type: str | None = None,
) -> dict[str, Any]:
    request_id = _optional_text(body.get("request_id"))
    if not request_id or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,120}", request_id):
        request_id = f"admin-{uuid.uuid4().hex}"
    actor = request.headers.get("x-grace-actor") or request.headers.get("x-admin-actor") or "operator"
    return {
        "project_key": _local_identity(body, request),
        "action": action or str(body.get("action") or "unknown")[:120],
        "entity_type": entity_type or str(body.get("entity_type") or "project")[:80],
        "entity_id": _optional_text(body.get("entity_id")),
        "actor": mask_operator_data(str(actor)[:120]),
        "request_id": request_id,
    }


# END_BLOCK_IDENTITY


# START_BLOCK_AUDIT
# START_FUNCTION_CONTRACT
# name: _record_admin_event
# purpose: Persist one secret-safe canonical local admin event in strict mode.
# inputs: event type/audit fields, reason/result and optional recorder.
# returns: True when persisted; False when persistence failed.
# side_effects: Inserts one Event row and emits a failure log on error.
# emitted_logs: admin_audit_persist_failed.
# error_behavior: Never raises persistence errors to the router.
# END_FUNCTION_CONTRACT
def _record_admin_event(
    event_type: str,
    audit: Mapping[str, Any],
    *,
    reason: str,
    result: str = "success",
    recorder: Callable[..., Any] | None = None,
) -> bool:
    payload = mask_operator_data({
        **dict(audit),
        "result": result if result in {"success", "failed", "unknown_after_timeout"} else "failed",
        "reason": reason[:240],
    })
    try:
        (recorder or _default_record_event)(
            event_type,
            str(audit.get("entity_type") or "project"),
            str(audit.get("entity_id") or audit.get("project_key") or "project"),
            payload,
            raise_on_error=True,
        )
    except Exception as exc:
        _log.error(
            "admin_audit_persist_failed",
            event_type=event_type,
            reason=exc.__class__.__name__,
        )
        return False
    return True


# START_FUNCTION_CONTRACT
# name: _audit_failure_response
# purpose: Surface audit integrity loss without claiming an ordinary success.
# inputs: audit identity, failure phase and optional mutation outcome.
# returns: HTTP 503 JSONResponse with an attention DTO.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for bounded mappings.
# END_FUNCTION_CONTRACT
def _audit_failure_response(
    audit: Mapping[str, Any],
    *,
    phase: str,
    outcome: Mapping[str, Any] | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {
        **dict(audit),
        "ok": False,
        "result": "failed",
        "error_code": "AUDIT_INTEGRITY_FAILURE",
        "reason": f"canonical audit persistence failed {phase}",
        "retry_allowed": False,
        "attention": True,
    }
    if outcome is not None:
        content["mutation_outcome"] = mask_operator_data(dict(outcome))
    return JSONResponse(status_code=503, content=content)


# END_BLOCK_AUDIT


# START_BLOCK_OPENAPI
# START_FUNCTION_CONTRACT
# name: _materialize_openapi_request
# purpose: Substitute only declared path placeholders and preserve declared
#          scalar query values for one same-app OpenAPI operation.
# inputs: app, exact discovered path/method and parameter mapping.
# returns: Materialized path and bounded query mapping, or empty path on error.
# side_effects: Reads the app OpenAPI document only.
# emitted_logs: None.
# error_behavior: Missing/undeclared/unsafe parameters fail closed.
# END_FUNCTION_CONTRACT
def _materialize_openapi_request(
    app: Any,
    path: str,
    method: str,
    parameters: Mapping[str, Any],
) -> tuple[str, dict[str, str]]:
    document = app.openapi()
    paths = document.get("paths", {}) if isinstance(document, Mapping) else {}
    if not isinstance(paths, Mapping) or path not in paths:
        return "", {}
    operations = paths.get(path)
    operation = operations.get(method.casefold()) if isinstance(operations, Mapping) else None
    if not isinstance(operation, Mapping):
        return "", {}
    definitions: dict[str, tuple[str, bool]] = {}
    common = operations.get("parameters", []) if isinstance(operations, Mapping) else []
    declared_rows = list(common) if isinstance(common, list) else []
    if isinstance(operation.get("parameters"), list):
        declared_rows.extend(operation["parameters"])
    for item in declared_rows[:100]:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        location = str(item.get("in") or "").casefold()
        schema = item.get("schema")
        if (
            not isinstance(name, str)
            or not name
            or location not in {"path", "query"}
            or not isinstance(schema, Mapping)
            or str(schema.get("type") or "string").casefold() in {"array", "object"}
        ):
            continue
        definitions[name] = (location, bool(item.get("required")) or location == "path")
    if any(key not in definitions for key in parameters):
        return "", {}
    materialized = path
    placeholders = re.findall(r"\{([^{}]+)\}", path)
    for name in placeholders:
        definition = definitions.get(name)
        if definition is None or definition[0] != "path":
            return "", {}
        value = parameters.get(name)
        if value is None or isinstance(value, (Mapping, list, tuple)):
            return "", {}
        text = str(value)
        if not text or len(text) > 500 or "/" in text or "\\" in text or ".." in text:
            return "", {}
        materialized = materialized.replace("{" + name + "}", quote(text, safe="-_.~"))
    if "{" in materialized or "}" in materialized:
        return "", {}
    for name, (_location, required) in definitions.items():
        if name not in parameters:
            if required:
                return "", {}
            continue
        if isinstance(parameters[name], (Mapping, list, tuple)):
            return "", {}
        if required and not str(parameters[name]):
            return "", {}
    query = {
        str(key)[:100]: str(value)[:500]
        for key, value in parameters.items()
        if definitions.get(str(key), ("", False))[0] == "query"
    }
    return materialized, _bounded_params(query)


# START_FUNCTION_CONTRACT
# name: _bounded_params
# purpose: Bound scalar OpenAPI query parameters before same-app dispatch.
# inputs: Query parameter mapping.
# returns: Bounded scalar mapping.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Excessive mappings become empty.
# END_FUNCTION_CONTRACT
def _bounded_params(value: Mapping[str, Any]) -> dict[str, str]:
    if len(value) > 20:
        return {}
    return {
        str(key)[:100]: str(item)[:500]
        for key, item in value.items()
        if not isinstance(item, (Mapping, list, tuple))
    }


# END_BLOCK_OPENAPI
