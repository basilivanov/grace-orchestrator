# ############################################################################
# AI_HEADER: lifecycle_service — supervisor, worker, and version snapshots
# ROLE: Composes explicit lifecycle ports into the stable status, versions, and
#      health DTOs while delegating restart/reload controls to their service.
#      FastAPI authorization, confirmation, and audit remain outside this class.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build lifecycle read snapshots and delegate guarded supervisor
#          restart/reload operations through explicit collaborators.
# inputs: RuntimeStateStore, SupervisorControlService, WorkerReadService, and
#          VersionProvider instances.
# returns: Historical lifecycle response dictionaries or typed service errors.
# side_effects: Reads state/DB/Git through injected ports; control methods send
#               one supervisor request through the injected control service.
# emitted_logs: None.
# error_behavior: Missing status/version state raises LifecycleStateMissingError;
#                 control errors propagate typed supervisor domain exceptions.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: LifecycleStateMissingError
#   - class: LifecycleService
#     methods:
#       - __init__
#       - status
#       - versions
#       - health_full
#       - restart
#       - reload
# END_MODULE_MAP

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.runtime_state_store import RuntimeStateStore
from grace_control.services.supervisor_control_service import SupervisorControlService
from grace_control.services.version_provider import VersionProvider
from grace_control.services.worker_read_service import WorkerReadService

_log = GraceLogger("lifecycle_service")


# START_BLOCK_LIFECYCLE_ERRORS
class LifecycleStateMissingError(RuntimeError):
    """The lifecycle state cannot provide a required read snapshot."""


# END_BLOCK_LIFECYCLE_ERRORS


# START_BLOCK_LIFECYCLE_SERVICE
class LifecycleService:
    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Compose the four explicit lifecycle collaborators.
    # inputs: state_store — state-file port; supervisor — control port;
    #          workers — Worker projection port; version — Git version port.
    # returns: None.
    # side_effects: None.
    # error_behavior: Stores only the supplied collaborators; no global lookup.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        state_store: RuntimeStateStore,
        supervisor: SupervisorControlService,
        workers: WorkerReadService,
        version: VersionProvider,
    ) -> None:
        self._state_store = state_store
        self._supervisor = supervisor
        self._workers = workers
        self._version = version

    # START_FUNCTION_CONTRACT
    # name: status
    # purpose: Return the combined supervisor, DB-worker, version, and fetch
    #          timestamp snapshot.
    # inputs: None.
    # returns: Historical status DTO with supervisor_state, db_workers,
    #          code_sha, and fetched_at.
    # side_effects: Reads the state store, worker service, and version provider.
    # emitted_logs: None.
    # error_behavior: Raises LifecycleStateMissingError when state is absent or
    #                 unreadable.
    # END_FUNCTION_CONTRACT
    def status(self) -> dict[str, Any]:
        state = self._required_state(
            "supervisor state not found — is the supervisor running? "
            "Start it with `scripts/live_supervisor.sh`; use the HTTP API after bootstrap."
        )
        return {
            "supervisor_state": state,
            "db_workers": self._workers.snapshot(),
            "code_sha": self._version.current_sha(),
            "fetched_at": _now_iso(),
        }

    # START_FUNCTION_CONTRACT
    # name: versions
    # purpose: Return current API version and supervisor child version details.
    # inputs: None.
    # returns: Historical versions DTO with current_sha, api, workers, and
    #          recommendation fields.
    # side_effects: Reads state and invokes the version provider.
    # emitted_logs: None.
    # error_behavior: Raises LifecycleStateMissingError when state is absent or
    #                 unreadable.
    # END_FUNCTION_CONTRACT
    def versions(self) -> dict[str, Any]:
        state = self._required_state("supervisor not running")
        current_sha = self._version.current_sha()
        api_pid = (state.get("api") or {}).get("pid")
        workers = state.get("workers", [])
        return {
            "current_sha": current_sha,
            "api": {"pid": api_pid, "in_sync": True},
            "workers": [
                {"pid": worker.get("pid"), "started_at": worker.get("started_at")}
                for worker in workers
            ],
            "recommendation": (
                "POST /api/admin/lifecycle/restart/workers to bring children in sync"
                if workers else "no workers to restart"
            ),
        }

    # START_FUNCTION_CONTRACT
    # name: health_full
    # purpose: Return a degraded-safe full lifecycle health snapshot.
    # inputs: None.
    # returns: Health DTO with issue list, liveness flags, counts, version, and
    #          fetch timestamp; remains normal data even when unhealthy.
    # side_effects: Reads state, DB workers, and current version.
    # emitted_logs: None.
    # error_behavior: Missing or malformed state becomes the documented issue;
    #                 worker read/version errors propagate.
    # END_FUNCTION_CONTRACT
    def health_full(self) -> dict[str, Any]:
        state = self._state_store.read()
        db_workers = self._workers.snapshot()
        issues: list[str] = []
        if state is None:
            issues.append("supervisor state missing")
        if state and not state.get("api"):
            issues.append("api not running")
        if state and not state.get("workers"):
            issues.append("no workers running")
        if not db_workers:
            issues.append("no workers registered in DB")
        return {
            "healthy": not issues,
            "issues": issues,
            "supervisor_alive": state is not None,
            "api_alive": bool(state and state.get("api")),
            "workers_alive": len(state.get("workers", [])) if state else 0,
            "db_workers": len(db_workers),
            "code_sha": self._version.current_sha(),
            "fetched_at": _now_iso(),
        }

    # START_FUNCTION_CONTRACT
    # name: restart
    # purpose: Delegate one validated supervisor restart to the control port.
    # inputs: target — api, workers, or all.
    # returns: Supervisor response dictionary.
    # side_effects: One supervisor restart request through the collaborator.
    # emitted_logs: None.
    # error_behavior: Propagates typed supervisor domain errors.
    # END_FUNCTION_CONTRACT
    async def restart(self, target: str) -> dict[str, Any]:
        return await self._supervisor.restart(target)

    # START_FUNCTION_CONTRACT
    # name: reload
    # purpose: Delegate one supervisor watcher reload to the control port.
    # inputs: None.
    # returns: Supervisor response dictionary.
    # side_effects: One supervisor reload request through the collaborator.
    # emitted_logs: None.
    # error_behavior: Propagates typed supervisor domain errors.
    # END_FUNCTION_CONTRACT
    async def reload(self) -> dict[str, Any]:
        return await self._supervisor.reload()

    # START_FUNCTION_CONTRACT
    # name: _required_state
    # purpose: Read state and raise a typed error for required snapshots.
    # inputs: message — endpoint-specific missing-state detail.
    # returns: Parsed state mapping.
    # side_effects: Reads the runtime state store.
    # emitted_logs: None.
    # error_behavior: Raises LifecycleStateMissingError when read() is None.
    # END_FUNCTION_CONTRACT
    def _required_state(self, message: str) -> dict[str, Any]:
        state = self._state_store.read()
        if state is None:
            raise LifecycleStateMissingError(message)
        return state


# START_FUNCTION_CONTRACT
# name: _now_iso
# purpose: Preserve the lifecycle API's UTC timestamp representation.
# inputs: None.
# returns: Current UTC timestamp ending in Z.
# side_effects: Reads the system clock.
# emitted_logs: None.
# error_behavior: Never raises under normal datetime operation.
# END_FUNCTION_CONTRACT
def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# END_BLOCK_LIFECYCLE_SERVICE
