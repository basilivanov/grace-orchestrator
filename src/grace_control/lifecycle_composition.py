# ############################################################################
# AI_HEADER: lifecycle_composition — explicit runtime lifecycle composition
# ROLE: Resolves the current runtime target and constructs one lifecycle service
#      graph per request/dispatch. It is a narrow composition root, not a
#      service locator or mutable global registry.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build the explicit lifecycle service graph using the current runtime
#          target directory and the existing supervisor/DB/Git boundaries.
# inputs: Runtime target-dir configuration values at call time.
# returns: A newly composed LifecycleService with four explicit collaborators.
# side_effects: Reads environment/settings; no files or network calls occur
#               until a returned service method is invoked.
# emitted_logs: None.
# error_behavior: Uses the configured local runtime default when no target
#                 directory is supplied.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: build_lifecycle_service
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from grace_control.config.lifecycle_settings import get_lifecycle_target_dir
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.lifecycle_service import LifecycleService
from grace_control.services.runtime_state_store import RuntimeStateStore
from grace_control.services.supervisor_control_service import SupervisorControlService
from grace_control.services.version_provider import VersionProvider
from grace_control.services.worker_read_service import WorkerReadService
from grace_control.supervisor_client import SupervisorClient

_log = GraceLogger("lifecycle_composition")

SUPERVISOR_TIMEOUT_SECONDS = 30.0


# START_FUNCTION_CONTRACT
# name: build_lifecycle_service
# purpose: Compose a fresh lifecycle service graph for the current runtime
#          target, preserving dynamic test/runtime environment changes.
# inputs: None.
# returns: LifecycleService with state, supervisor, worker, and version ports.
# side_effects: Reads runtime target configuration; constructs client objects
#               only.
# emitted_logs: None.
# error_behavior: Falls back to the config boundary's local runtime default
#                 when target configuration is empty.
# END_FUNCTION_CONTRACT
def build_lifecycle_service() -> LifecycleService:
    target_dir = get_lifecycle_target_dir()
    state_store = RuntimeStateStore(target_dir)
    client = SupervisorClient(
        target_dir / "supervisor.sock",
        timeout=SUPERVISOR_TIMEOUT_SECONDS,
    )
    supervisor = SupervisorControlService(state_store, client)
    workers = WorkerReadService()
    version = VersionProvider((target_dir, Path.cwd()))
    return LifecycleService(state_store, supervisor, workers, version)
