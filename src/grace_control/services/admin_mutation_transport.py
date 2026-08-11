# ############################################################################
# AI_HEADER: admin_mutation_transport — guarded selected-project mutation I/O
# ROLE: Owns the single-attempt mutation transport and runtime identity guard.
#       It uses the accepted Hub registry/request/client seams and never retries
#       or falls back to another project.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify selected runtime identity and dispatch one bounded mutation.
# inputs: AdminMutationService-compatible Hub, project key, local path, payload,
#          request ID and actor.
# returns: Raw ProjectApiResult or compatible fake-client response.
# side_effects: At most one project-local mutation request after health verify.
# emitted_logs: admin_mutation_identity_rejected and client transport logs.
# error_behavior: Disabled/missing mutation support raises; identity failures
#                 return typed fail-closed ProjectApiResult.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminMutationTransportMixin
#     methods:
#       - _call_project
#   - function: _runtime_identity_present
# END_MODULE_MAP

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.project_client import ProjectApiResult

_log = GraceLogger("admin_mutation_transport")


# START_BLOCK_TRANSPORT
class AdminMutationTransportMixin:
    """Single-attempt identity-guarded mutation transport."""

    # START_FUNCTION_CONTRACT
    # name: _call_project
    # purpose: Call one selected project's mutation-capable client exactly once.
    # inputs: project key, local path, payload, request ID and actor.
    # returns: Raw compatible ProjectApiResult or fake-client response.
    # side_effects: One bounded project-local request.
    # emitted_logs: Project transport logs.
    # error_behavior: Missing mutation support raises a typed runtime error.
    # END_FUNCTION_CONTRACT
    async def _call_project(
        self,
        project_key: str,
        path: str,
        payload: Mapping[str, Any],
        request_id: str,
        actor: str,
    ) -> Any:
        context = self._hub._registry.get(project_key)
        if not context.enabled:
            raise RuntimeError("project is disabled")
        identity = await self._hub._request(
            context,
            "/api/admin/system/health",
            operation="health",
        )
        identity_known = _runtime_identity_present(identity.payload)
        if not identity.ok or not identity_known:
            mismatch = identity.error_class == "identity_mismatch"
            error_code = "PROJECT_IDENTITY_MISMATCH" if mismatch else "PROJECT_IDENTITY_UNAVAILABLE"
            status = 409 if mismatch else 503
            _log.warn(
                "admin_mutation_identity_rejected",
                project_key=project_key,
                reason="identity_mismatch" if mismatch else "identity_unavailable",
            )
            return ProjectApiResult(
                project_key=project_key,
                ok=False,
                payload={"error_code": error_code},
                error_class=error_code,
                error="selected runtime identity could not be verified",
                http_status=status,
            )
        client = self._hub._client_factory(context)
        mutate = getattr(client, "mutate_json", None)
        if callable(mutate):
            kwargs: dict[str, Any] = {"method": "POST", "payload": payload}
            try:
                signature = inspect.signature(mutate)
                if "request_id" in signature.parameters:
                    kwargs["request_id"] = request_id
                if "actor" in signature.parameters:
                    kwargs["actor"] = str(actor)[:120]
            except (TypeError, ValueError):
                pass
            return await mutate(path, **kwargs)
        request_json = getattr(client, "request_json", None)
        if not callable(request_json):
            raise RuntimeError("project runtime does not advertise mutation transport")
        kwargs = {"method": "POST", "payload": payload}
        try:
            signature = inspect.signature(request_json)
            if "request_id" in signature.parameters:
                kwargs["request_id"] = request_id
            if "extra_headers" in signature.parameters:
                kwargs["extra_headers"] = {
                    "x-grace-admin-request-id": request_id,
                    "x-grace-admin-actor": str(actor)[:120],
                }
        except (TypeError, ValueError):
            pass
        return await request_json(path, **kwargs)


# END_BLOCK_TRANSPORT


# START_BLOCK_HELPERS
# START_FUNCTION_CONTRACT
# name: _runtime_identity_present
# purpose: Require a non-empty runtime identity field before a mutation may be
#          sent through a registry-selected client.
# inputs: payload — normalized project health mapping.
# returns: True when a top-level or nested identity field is present.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Malformed/non-mapping payloads return False.
# END_FUNCTION_CONTRACT
def _runtime_identity_present(payload: Mapping[str, Any] | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    candidates: list[Mapping[str, Any]] = [payload]
    for key in ("identity", "project", "runtime", "data"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            candidates.append(nested)
    return any(
        candidate.get(key) not in (None, "")
        for candidate in candidates
        for key in ("project_key", "project_name", "project_root", "target_repo_root")
    )


# END_BLOCK_HELPERS
