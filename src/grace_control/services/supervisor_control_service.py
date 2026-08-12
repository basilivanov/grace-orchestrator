# ############################################################################
# AI_HEADER: supervisor_control_service — typed supervisor mutation port
# ROLE: Guards and delegates lifecycle restart/reload operations to the
#      existing SupervisorClient while keeping transport errors out of FastAPI.
#      Admin and lifecycle adapters translate the explicit domain exceptions.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Perform one guarded supervisor restart or reload through the
#          existing HTTP-over-UDS SupervisorClient.
# inputs: RuntimeStateStore and SupervisorClient collaborators.
# returns: Supervisor response dictionaries for successful operations.
# side_effects: Sends one supervisor control request; never retries mutations.
# emitted_logs: None.
# error_behavior: Raises typed not-running, unavailable, remote, or ValueError
#                 exceptions without importing FastAPI.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: SupervisorNotRunningError
#   - class: SupervisorUnavailableError
#   - class: SupervisorRemoteError
#   - class: SupervisorControlService
#     methods:
#       - __init__
#       - restart
#       - reload
# END_MODULE_MAP

from __future__ import annotations

from typing import Any

import httpx

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.runtime_state_store import RuntimeStateStore
from grace_control.supervisor_client import SupervisorClient, SupervisorConnectionError

_log = GraceLogger("supervisor_control_service")

_NOT_RUNNING_MESSAGE = (
    "supervisor not running — start it with `scripts/live_supervisor.sh`; "
    "use the HTTP API after bootstrap."
)


# START_BLOCK_SUPERVISOR_ERRORS
class SupervisorNotRunningError(RuntimeError):
    """The supervisor state file is not present for the target runtime."""


class SupervisorUnavailableError(RuntimeError):
    """The supervisor control socket or transport cannot be reached."""


class SupervisorRemoteError(RuntimeError):
    """The supervisor returned an HTTP error that should preserve its status."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Preserve remote HTTP status and response detail as a domain
    #          exception for the HTTP adapter.
    # inputs: status_code — remote HTTP status; detail — response text.
    # returns: None.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Stores both values and exposes detail as the exception
    #                 message.
    # END_FUNCTION_CONTRACT
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


# END_BLOCK_SUPERVISOR_ERRORS


# START_BLOCK_SUPERVISOR_CONTROL_SERVICE
class SupervisorControlService:
    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind supervisor controls to an explicit state store and client.
    # inputs: state_store — runtime state presence port; client — existing
    #          SupervisorClient control port.
    # returns: None.
    # side_effects: None.
    # error_behavior: Collaborators are stored without global lookup.
    # END_FUNCTION_CONTRACT
    def __init__(self, state_store: RuntimeStateStore, client: SupervisorClient) -> None:
        self._state_store = state_store
        self._client = client

    # START_FUNCTION_CONTRACT
    # name: restart
    # purpose: Validate and execute one supervisor restart operation.
    # inputs: target — api, workers, or all.
    # returns: Supervisor response dictionary.
    # side_effects: Sends one POST restart request; no retry occurs.
    # emitted_logs: None.
    # error_behavior: Raises ValueError for invalid target and typed supervisor
    #                 exceptions for availability/remote failures.
    # END_FUNCTION_CONTRACT
    async def restart(self, target: str) -> dict[str, Any]:
        if target not in {"api", "workers", "all"}:
            raise ValueError(f"target must be api|workers|all, got {target!r}")
        self._require_running()
        return await self._invoke("restart", target)

    # START_FUNCTION_CONTRACT
    # name: reload
    # purpose: Execute one supervisor watcher reload operation.
    # inputs: None.
    # returns: Supervisor response dictionary.
    # side_effects: Sends one POST reload request; no retry occurs.
    # emitted_logs: None.
    # error_behavior: Raises typed supervisor exceptions for availability or
    #                 remote failures.
    # END_FUNCTION_CONTRACT
    async def reload(self) -> dict[str, Any]:
        self._require_running()
        return await self._invoke("reload")

    # START_FUNCTION_CONTRACT
    # name: _require_running
    # purpose: Preserve the historical state-file-exists mutation gate.
    # inputs: None.
    # returns: None.
    # side_effects: Checks state-file physical presence and socket metadata.
    # emitted_logs: None.
    # error_behavior: Raises typed not-running or unavailable errors.
    # END_FUNCTION_CONTRACT
    def _require_running(self) -> None:
        if not self._state_store.exists():
            raise SupervisorNotRunningError(_NOT_RUNNING_MESSAGE)
        socket_path = getattr(self._client, "socket_path", None)
        if socket_path is not None and not socket_path.exists():
            raise SupervisorUnavailableError(
                f"supervisor state present but socket missing: {socket_path}"
            )

    # START_FUNCTION_CONTRACT
    # name: _invoke
    # purpose: Invoke exactly one existing SupervisorClient mutation and map
    #          transport/remote failures into domain exceptions.
    # inputs: operation — restart or reload; target — restart target or None.
    # returns: Supervisor response dictionary.
    # side_effects: Sends one request through SupervisorClient.
    # emitted_logs: None.
    # error_behavior: HTTP status errors preserve status/detail; all known
    #                 connectivity failures become unavailable errors.
    # END_FUNCTION_CONTRACT
    async def _invoke(self, operation: str, target: str | None = None) -> dict[str, Any]:
        try:
            if operation == "restart":
                return await self._client.restart(str(target))
            return await self._client.reload()
        except httpx.HTTPStatusError as exc:
            raise SupervisorRemoteError(exc.response.status_code, exc.response.text) from exc
        except SupervisorConnectionError as exc:
            raise SupervisorUnavailableError(str(exc)) from exc
        except (TimeoutError, httpx.TimeoutException, httpx.TransportError, OSError) as exc:
            raise SupervisorUnavailableError(str(exc)) from exc
        except Exception as exc:
            # Preserve the previous proxy's 502 behavior for an unexpected
            # client/transport failure without retrying an ambiguous mutation.
            raise SupervisorUnavailableError(str(exc)) from exc


# END_BLOCK_SUPERVISOR_CONTROL_SERVICE
