# ############################################################################
# AI_HEADER: runtime_adapter
# ROLE: Abstract runtime interface for workflow execution (Prefect, dry-run, etc).
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide pluggable runtime adapters for submitting packet runs.
# inputs: Packet data, runtime parameters, execution mode.
# returns: Run references, status, artifacts.
# side_effects: May create Prefect flow runs if PrefectRuntimeAdapter is used.
# emitted_logs: None.
# error_behavior: Returns structured errors for runtime failures.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: WorkflowRuntime
#   - class: DryRunRuntime
#   - class: PrefectRuntimeAdapter
#   - class: E2EPacketSubmitter
#   - class: ManagedPacketSubmitter
#   - function: create_runtime
# END_MODULE_MAP

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prefect_grace.runtime import PrefectAPIContext
from prefect_grace.runtime.async_helpers import run_async_safe

#START_BLOCK_RUNTIME_INTERFACE
@dataclass
class WorkflowRuntime(ABC):
    name: str

    # START_FUNCTION_CONTRACT
    # name: submit_packet_run
    # purpose: Submit a packet for execution in the workflow runtime.
    # inputs:
    #   packet: dict containing packet metadata.
    #   parameters: dict of runtime parameters.
    # returns: dict with run reference (run_id, url, etc).
    # side_effects: May create external workflow runs.
    # emitted_logs: None.
    # error_behavior: Raises RuntimeError on submission failure.
    # END_FUNCTION_CONTRACT
    @abstractmethod
    def submit_packet_run(self, packet: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        pass

    # START_FUNCTION_CONTRACT
    # name: publish_artifact
    # purpose: Publish an artifact to the runtime.
    # inputs:
    #   run_ref: dict with run reference.
    #   name: artifact name.
    #   body: artifact content (string or dict).
    # returns: None.
    # side_effects: May write artifacts to external storage.
    # emitted_logs: None.
    # error_behavior: Raises RuntimeError on publish failure.
    # END_FUNCTION_CONTRACT
    @abstractmethod
    def publish_artifact(self, run_ref: dict[str, Any], name: str, body: str | dict) -> None:
        pass

    # START_FUNCTION_CONTRACT
    # name: read_run_status
    # purpose: Read current status of a workflow run (sync version).
    # inputs:
    #   run_ref: dict with run reference.
    # returns: dict with status, state, timestamps.
    # side_effects: May query external runtime API.
    # emitted_logs: None.
    # error_behavior: Returns error dict if run not found or called from async context.
    # END_FUNCTION_CONTRACT
    @abstractmethod
    def read_run_status(self, run_ref: dict[str, Any]) -> dict[str, Any]:
        """
        Read run status from a synchronous context.

        Use this method when calling from sync code.
        If you're in an async context, use read_run_status_async() instead.
        """
        pass

    # START_FUNCTION_CONTRACT
    # name: read_run_status_async
    # purpose: Read current status of a workflow run (async version).
    # inputs:
    #   run_ref: dict with run reference.
    # returns: dict with status, state, timestamps.
    # side_effects: May query external runtime API.
    # emitted_logs: None.
    # error_behavior: Returns error dict if run not found.
    # END_FUNCTION_CONTRACT
    @abstractmethod
    async def read_run_status_async(self, run_ref: dict[str, Any]) -> dict[str, Any]:
        """
        Read run status from an asynchronous context.

        Use this method when calling from async code.
        If you're in a sync context, use read_run_status() instead.
        """
        pass

#END_BLOCK_RUNTIME_INTERFACE
#START_BLOCK_DRY_RUN_RUNTIME
class DryRunRuntime(WorkflowRuntime):
    def __init__(self):
        super().__init__(name="dry-run")
        self.submitted_runs: list[dict[str, Any]] = []
        self.artifacts: list[dict[str, Any]] = []

    def submit_packet_run(self, packet: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        run_id = f"dry-run-{uuid.uuid4().hex[:8]}"
        run_ref = {
            "run_id": run_id,
            "runtime": "dry-run",
            "packet_id": packet.get("packet_id"),
            "parameters": parameters,
            "url": f"dry-run://localhost/{run_id}",
        }
        self.submitted_runs.append(run_ref)
        return run_ref

    def publish_artifact(self, run_ref: dict[str, Any], name: str, body: str | dict) -> None:
        artifact = {
            "run_id": run_ref.get("run_id"),
            "name": name,
            "body": body,
        }
        self.artifacts.append(artifact)

    def read_run_status(self, run_ref: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": run_ref.get("run_id"),
            "state": "DRY_RUN",
            "status": "simulated",
        }

    async def read_run_status_async(self, run_ref: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": run_ref.get("run_id"),
            "state": "DRY_RUN",
            "status": "simulated",
        }

#END_BLOCK_DRY_RUN_RUNTIME
#START_BLOCK_PREFECT_RUNTIME_ADAPTER
class PrefectRuntimeAdapter(WorkflowRuntime):
    def __init__(self, work_pool: str | None = None, queue: str | None = None):
        super().__init__(name="prefect")
        self.work_pool = work_pool
        self.queue = queue

    def submit_packet_run(self, packet: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        try:
            from prefect_grace.tasks.prefect_submitter import (
                E2E_PACKET_DEPLOYMENT_NAME,
                e2e_packet_flow_parameters,
                submit_e2e_packet_flow_run,
            )
        except ImportError as e:
            raise RuntimeError(f"Prefect runtime unavailable: {e}")

        packet_id = packet.get("packet_id")
        feature_id = packet.get("feature_id")

        if not packet_id or not feature_id:
            raise ValueError("packet_id and feature_id are required")

        attempt = int(parameters.get("attempt") or packet.get("attempt") or 1)
        project_key = str(parameters.get("project_key") or packet.get("project_key") or "project")
        source_hash = str(parameters.get("source_hash") or packet.get("source_hash") or "").strip()
        idempotency_key = parameters.get("idempotency_key")
        if not idempotency_key and source_hash:
            idempotency_key = f"grace-packet:{project_key}:{packet_id}:attempt-{attempt:04d}:{source_hash}"

        flow_params = e2e_packet_flow_parameters(
            project_root=str(parameters.get("project_root") or parameters.get("repo_root") or packet.get("repo_root") or "."),
            packet_path=str(parameters.get("packet_path") or parameters.get("packet_file") or packet.get("packet_path") or packet.get("path") or ""),
            state_root=str(parameters.get("state_root") or parameters.get("runtime_state_root") or packet.get("runtime_state_root") or ".grace/state"),
            worktree_root=str(parameters.get("worktree_root") or packet.get("worktree_root") or ".grace/worktrees"),
            project_key=project_key,
            packet_id=str(packet_id),
            attempt=attempt,
            base_ref=str(parameters.get("base_ref") or "HEAD"),
            dry_run=bool(parameters.get("dry_run", not bool(parameters.get("execute_agent", False)))),
            execute_agent=bool(parameters.get("execute_agent", False)),
            timeout_seconds=parameters.get("timeout_seconds", 3600),
            keep_worktree=parameters.get("keep_worktree", True),
        )

        tags = ["grace", "packet", "e2e", f"packet:{packet_id}", f"feature:{feature_id}"]
        wave_id = str(packet.get("wave_id") or parameters.get("wave_id") or "").strip()
        if wave_id:
            tags.append(f"wave:{wave_id}")

        result = submit_e2e_packet_flow_run(
            parameters=flow_params,
            scheduled_for=parameters.get("scheduled_for"),
            tags=tags,
            idempotency_key=idempotency_key,
        )

        return {
            "run_id": result["flow_run_id"],
            "runtime": "prefect",
            "packet_id": packet_id,
            "feature_id": feature_id,
            "runner_kind": "e2e",
            "deployment_name": result.get("deployment_name", E2E_PACKET_DEPLOYMENT_NAME),
            "url": result.get("url") or f"/flow-runs/flow-run/{result['flow_run_id']}",
            "state": result.get("status", "UNKNOWN"),
        }

    def publish_artifact(self, run_ref: dict[str, Any], name: str, body: str | dict) -> None:
        try:
            from prefect.artifacts import create_markdown_artifact
            import json
        except ImportError as e:
            raise RuntimeError(f"Prefect artifacts unavailable: {e}")

        if isinstance(body, dict):
            import json as json_module
            content = f"```json\n{json_module.dumps(body, indent=2)}\n```"
        else:
            content = body

        create_markdown_artifact(
            key=name,
            markdown=content,
            description=f"Artifact for run {run_ref.get('run_id')}",
        )

    def read_run_status(self, run_ref: dict[str, Any]) -> dict[str, Any]:
        """
        Read run status from a synchronous context.

        This method uses run_async_safe() which will raise a clear error
        if called from within an async context. In that case, use
        read_run_status_async() instead.
        """
        run_id = run_ref.get("run_id")
        if not run_id:
            return {"error": "run_id missing"}

        try:
            from prefect.client.orchestration import get_client
        except ImportError as e:
            raise RuntimeError(f"Prefect client unavailable: {e}")

        async def _fetch():
            async with get_client() as client:
                flow_run = await client.read_flow_run(run_id)
                return {
                    "run_id": str(flow_run.id),
                    "state": flow_run.state.name if flow_run.state else "UNKNOWN",
                    "status": flow_run.state.type.value if flow_run.state else "UNKNOWN",
                }

        try:
            return run_async_safe(_fetch())
        except RuntimeError as e:
            # If called from async context, return error dict with guidance
            if "event loop" in str(e).lower():
                return {
                    "error": "Cannot call sync method from async context",
                    "guidance": "Use read_run_status_async() instead",
                    "details": str(e),
                }
            return {"error": str(e)}
        except Exception as e:
            return {"error": str(e)}

    async def read_run_status_async(self, run_ref: dict[str, Any]) -> dict[str, Any]:
        """
        Read run status from an asynchronous context.

        Use this method when calling from async code.
        """
        run_id = run_ref.get("run_id")
        if not run_id:
            return {"error": "run_id missing"}

        try:
            from prefect.client.orchestration import get_client
        except ImportError as e:
            raise RuntimeError(f"Prefect client unavailable: {e}")

        try:
            async with get_client() as client:
                flow_run = await client.read_flow_run(run_id)
                return {
                    "run_id": str(flow_run.id),
                    "state": flow_run.state.name if flow_run.state else "UNKNOWN",
                    "status": flow_run.state.type.value if flow_run.state else "UNKNOWN",
                }
        except Exception as e:
            return {"error": str(e)}

#END_BLOCK_PREFECT_RUNTIME_ADAPTER
#START_BLOCK_FEATURE_SUBMITTER
class FeatureSubmitter:
    """Submitter for feature flow runs via Prefect native submission."""

    def __init__(self):
        pass

    # START_FUNCTION_CONTRACT
    # name: __call__
    # purpose: Submit feature flow run to Prefect.
    # inputs:
    #   parameters: dict with feature_id, title, summary, etc.
    #   scheduled_for: optional ISO8601 scheduled time.
    #   tags: optional list of additional tags.
    #   idempotency_key: optional idempotency key.
    # returns: dict with flow_run_id, deployment_id, feature_id, title, status, scheduled_for, work_queue_name, tags.
    # side_effects: Creates Prefect flow run.
    # emitted_logs: None.
    # error_behavior: Raises RuntimeError on submission failure.
    # END_FUNCTION_CONTRACT
    def __call__(
        self,
        *,
        parameters: dict[str, Any],
        scheduled_for: str | None = None,
        tags: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        import os
        try:
            from prefect_grace.tasks.prefect_submitter import build_feature_submission_request
            from prefect.client.orchestration import get_client
            from prefect.states import Scheduled
        except ImportError as e:
            raise RuntimeError(f"Prefect unavailable: {e}")

        # Build submission request without Prefect calls
        request = build_feature_submission_request(
            parameters=parameters,
            scheduled_for=scheduled_for,
            tags=tags,
            idempotency_key=idempotency_key,
        )

        # Execute Prefect submission
        with PrefectAPIContext(request["api_url"]):
            with get_client(sync_client=True) as client:
                deployment = client.read_deployment_by_name(request["deployment_name"])
                flow_run = client.create_flow_run_from_deployment(
                    deployment_id=deployment.id,
                    parameters=request["parameters"],
                    state=Scheduled(scheduled_time=request["scheduled_time"]),
                    name=request["flow_run_name"],
                    work_queue_name=request["work_queue_name"],
                    idempotency_key=request["idempotency_key"],
                    labels=request["labels"],
                    tags=request["tags"],
                )

        return {
            "flow_run_id": str(flow_run.id),
            "deployment_id": str(deployment.id),
            "feature_id": request["feature_id"],
            "title": request["title"],
            "status": str(getattr(flow_run.state, "name", None) or getattr(flow_run, "state_name", "") or "Scheduled"),
            "scheduled_for": request["scheduled_time"].isoformat(),
            "work_queue_name": request["work_queue_name"],
            "tags": request["tags"],
        }

#END_BLOCK_FEATURE_SUBMITTER
#START_BLOCK_E2E_PACKET_SUBMITTER
class E2EPacketSubmitter:
    """Submitter for E2E packet flow runs via Prefect native submission."""

    def __init__(self, deployment_name: str | None = None):
        self.deployment_name = deployment_name

    # START_FUNCTION_CONTRACT
    # name: __call__
    # purpose: Submit E2E packet flow run to Prefect.
    # inputs:
    #   parameters: dict with project_root, packet_path, state_root, worktree_root, project_key, packet_id, attempt, base_ref, dry_run, execute_agent, timeout_seconds, keep_worktree.
    #   scheduled_for: optional ISO8601 scheduled time.
    #   tags: optional list of additional tags.
    #   idempotency_key: optional idempotency key.
    # returns: dict with flow_run_id, flow_run_name, deployment_name, work_queue_name, work_pool_name, url.
    # side_effects: Creates Prefect flow run.
    # emitted_logs: None.
    # error_behavior: Raises RuntimeError on submission failure.
    # END_FUNCTION_CONTRACT
    def __call__(
        self,
        *,
        parameters: dict[str, Any],
        scheduled_for: str | None = None,
        tags: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        import os
        try:
            from prefect_grace.tasks.prefect_submitter import (
                E2E_PACKET_DEPLOYMENT_NAME,
                build_e2e_packet_submission_request,
            )
            from prefect.client.orchestration import get_client
            from prefect.states import Scheduled
        except ImportError as e:
            raise RuntimeError(f"Prefect unavailable: {e}")

        request = build_e2e_packet_submission_request(
            parameters=parameters,
            scheduled_for=scheduled_for,
            tags=tags,
            idempotency_key=idempotency_key,
            deployment_name=self.deployment_name or E2E_PACKET_DEPLOYMENT_NAME,
        )

        with PrefectAPIContext(request["api_url"]):
            with get_client(sync_client=True) as client:
                deployment = client.read_deployment_by_name(request["deployment_name"])
                flow_run = client.create_flow_run_from_deployment(
                    deployment_id=deployment.id,
                    parameters=request["parameters"],
                    state=Scheduled(scheduled_time=request["scheduled_time"]),
                    name=request["flow_run_name"],
                    work_queue_name=request["work_queue_name"],
                    idempotency_key=request["idempotency_key"],
                    labels=request["labels"],
                    tags=request["tags"],
                )

        return {
            "flow_run_id": str(flow_run.id),
            "flow_run_name": request["flow_run_name"],
            "deployment_id": str(deployment.id),
            "deployment_name": request["deployment_name"],
            "packet_id": request["packet_id"],
            "project_key": request["project_key"],
            "runner_kind": "e2e",
            "status": str(getattr(flow_run.state, "name", None) or getattr(flow_run, "state_name", "") or "Scheduled"),
            "scheduled_for": request["scheduled_time"].isoformat(),
            "work_pool_name": request["work_pool_name"],
            "work_queue_name": request["work_queue_name"],
            "url": f"{request['api_url'].rstrip('/')}/flow-runs/flow-run/{flow_run.id}",
            "tags": request["tags"],
        }

#END_BLOCK_E2E_PACKET_SUBMITTER
#START_BLOCK_MANAGED_PACKET_SUBMITTER
class ManagedPacketSubmitter:
    """Submitter for managed packet flow runs via Prefect native submission."""

    def __init__(self):
        pass

    # START_FUNCTION_CONTRACT
    # name: __call__
    # purpose: Submit managed packet flow run to Prefect.
    # inputs:
    #   parameters: dict with packet_file, repo_root, worktree_root, project_key, packet_id, attempt, base_ref, dry_run, execute_agent, timeout_seconds.
    #   scheduled_for: optional ISO8601 scheduled time.
    #   tags: optional list of additional tags.
    #   idempotency_key: optional idempotency key.
    # returns: dict with flow_run_id, flow_run_name, deployment_name, work_queue_name, url.
    # side_effects: Creates Prefect flow run.
    # emitted_logs: None.
    # error_behavior: Raises RuntimeError on submission failure.
    # END_FUNCTION_CONTRACT
    def __call__(
        self,
        *,
        parameters: dict[str, Any],
        scheduled_for: str | None = None,
        tags: list[str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        import os
        try:
            from prefect_grace.tasks.prefect_submitter import build_managed_packet_submission_request
            from prefect.client.orchestration import get_client
            from prefect.states import Scheduled
        except ImportError as e:
            raise RuntimeError(f"Prefect unavailable: {e}")

        # Build submission request without Prefect calls
        request = build_managed_packet_submission_request(
            parameters=parameters,
            scheduled_for=scheduled_for,
            tags=tags,
            idempotency_key=idempotency_key,
        )

        # Execute Prefect submission
        with PrefectAPIContext(request["api_url"]):
            with get_client(sync_client=True) as client:
                deployment = client.read_deployment_by_name(request["deployment_name"])
                flow_run = client.create_flow_run_from_deployment(
                    deployment_id=deployment.id,
                    parameters=request["parameters"],
                    state=Scheduled(scheduled_time=request["scheduled_time"]),
                    name=request["flow_run_name"],
                    work_queue_name=request["work_queue_name"],
                    idempotency_key=request["idempotency_key"],
                    labels=request["labels"],
                    tags=request["tags"],
                )

        return {
            "flow_run_id": str(flow_run.id),
            "flow_run_name": request["flow_run_name"],
            "deployment_id": str(deployment.id),
            "deployment_name": request["deployment_name"],
            "packet_id": request["packet_id"],
            "project_key": request["project_key"],
            "status": str(getattr(flow_run.state, "name", None) or getattr(flow_run, "state_name", "") or "Scheduled"),
            "scheduled_for": request["scheduled_time"].isoformat(),
            "work_queue_name": request["work_queue_name"],
            "url": f"{request['api_url'].rstrip('/')}/flow-runs/flow-run/{flow_run.id}",
            "tags": request["tags"],
        }

#END_BLOCK_MANAGED_PACKET_SUBMITTER
#START_BLOCK_FACTORY
# START_FUNCTION_CONTRACT
# name: create_runtime
# purpose: Factory function to create runtime adapter instances.
# inputs:
#   runtime_type: string identifier (dry-run, prefect).
#   config: optional dict with runtime-specific configuration.
# returns: WorkflowRuntime instance.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises ValueError for unknown runtime types.
# END_FUNCTION_CONTRACT
def create_runtime(runtime_type: str, config: dict[str, Any] | None = None) -> WorkflowRuntime:
    config = config or {}

    if runtime_type == "dry-run":
        return DryRunRuntime()
    elif runtime_type == "prefect":
        return PrefectRuntimeAdapter(
            work_pool=config.get("work_pool"),
            queue=config.get("queue"),
        )
    else:
        raise ValueError(f"Unknown runtime type: {runtime_type}")

#END_BLOCK_FACTORY
#START_BLOCK_PREFECT_CLIENT_HELPER
# START_FUNCTION_CONTRACT
# name: create_prefect_sync_client
# purpose: Create a synchronous Prefect client for infrastructure validation.
# inputs: None.
# returns: Prefect sync client context manager (entered) or None if unavailable.
# side_effects: Creates Prefect client connection.
# emitted_logs: None.
# error_behavior: Returns None if Prefect unavailable or client creation fails.
# END_FUNCTION_CONTRACT
def create_prefect_sync_client() -> Any | None:
    """Create a synchronous Prefect client for infrastructure validation.

    Returns None if Prefect is not available (fail-closed).
    Caller is responsible for exiting the context manager if needed.
    """
    try:
        from prefect.client.orchestration import get_client
        return get_client(sync_client=True).__enter__()
    except (ImportError, Exception):
        return None

#END_BLOCK_PREFECT_CLIENT_HELPER
#START_BLOCK_DEPLOYMENT_HELPER
@dataclass
class DeploymentApplyResult:
    """Result of deployment apply operation with bounded before/after metadata."""
    success: bool
    deployment_name: str
    deployment_id: str | None
    work_pool_name: str
    work_queue_name: str
    entrypoint: str
    working_directory: str
    created: bool  # True if created, False if updated
    prefect_runs_created: int
    live_agents_started: int
    errors: list[dict[str, Any]]
    entrypoint_not_inspectable: bool = False  # True if entrypoint cannot be verified from existing deployment
    working_directory_not_inspectable: bool = False  # True if working_directory cannot be verified from existing deployment

    # START_FUNCTION_CONTRACT
    # Function: to_dict
    # Purpose: Serialize DeploymentApplyResult to dict for JSON output
    # Args: None (instance method)
    # Returns: Dict with all result fields
    # Inputs: self
    # Side_effects: None (pure function)
    # Emitted_logs: None
    # Error_behavior: Never raises
    # END_FUNCTION_CONTRACT
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON output."""
        return {
            "success": self.success,
            "deployment_name": self.deployment_name,
            "deployment_id": self.deployment_id,
            "work_pool_name": self.work_pool_name,
            "work_queue_name": self.work_queue_name,
            "entrypoint": self.entrypoint,
            "working_directory": self.working_directory,
            "created": self.created,
            "prefect_runs_created": self.prefect_runs_created,
            "live_agents_started": self.live_agents_started,
            "entrypoint_not_inspectable": self.entrypoint_not_inspectable,
            "working_directory_not_inspectable": self.working_directory_not_inspectable,
            "errors": self.errors,
        }

# START_FUNCTION_CONTRACT
# name: apply_managed_packet_deployment_helper
# purpose: Apply the managed packet runner deployment to Prefect.
# inputs:
#   - prefect_client: Prefect sync client
#   - api_url: Prefect API URL
#   - work_pool_name: Work pool name
#   - work_queue_name: Work queue name
# returns: DeploymentApplyResult with bounded before/after metadata
# side_effects: Creates or updates Prefect deployment.
# emitted_logs: None.
# error_behavior: Returns result with success=False and errors on failure.
# END_FUNCTION_CONTRACT
def apply_managed_packet_deployment_helper(
    prefect_client: Any,
    api_url: str,
    work_pool_name: str,
    work_queue_name: str,
) -> DeploymentApplyResult:
    """Apply the managed packet runner deployment.

    Returns DeploymentApplyResult with bounded before/after metadata.
    """
    from prefect_grace.tasks.prefect_submitter import MANAGED_PACKET_DEPLOYMENT_NAME
    from prefect_grace.runtime_config import load_runtime_config

    entrypoint = "prefect_grace/flows/managed_packet_runner_flow.py:managed_packet_runner_flow"
    runtime = load_runtime_config()
    working_directory = runtime.working_directory

    try:
        from prefect.deployments.runner import RunnerDeployment
        from prefect.client.schemas.actions import DeploymentUpdate
        import os

        # Check if deployment exists before apply
        deployment_exists_before = False
        try:
            existing = prefect_client.read_deployment_by_name(MANAGED_PACKET_DEPLOYMENT_NAME)
            deployment_exists_before = existing is not None
        except Exception:
            deployment_exists_before = False

        # Validate entrypoint before apply
        entrypoint_path, entrypoint_func = entrypoint.split(":")
        entrypoint_file = Path(entrypoint_path)
        if not entrypoint_file.exists():
            return DeploymentApplyResult(
                success=False,
                deployment_name=MANAGED_PACKET_DEPLOYMENT_NAME,
                deployment_id=None,
                work_pool_name=work_pool_name,
                work_queue_name=work_queue_name,
                entrypoint=entrypoint,
                working_directory=working_directory,
                created=False,
                prefect_runs_created=0,
                live_agents_started=0,
                entrypoint_not_inspectable=True,
                working_directory_not_inspectable=True,
                errors=[{"type": "INVALID_ENTRYPOINT", "message": f"Entrypoint file not found: {entrypoint_path}"}],
            )

        # Get deployment name parts
        flow_name, deployment_name = MANAGED_PACKET_DEPLOYMENT_NAME.split("/")

        # Create deployment from entrypoint
        deployment = RunnerDeployment.from_entrypoint(
            entrypoint=entrypoint,
            name=deployment_name,
            work_pool_name=work_pool_name,
            work_queue_name=work_queue_name,
            description="GRACE managed packet runner for live execution",
            tags=["grace", "managed", "packet-runner"],
        )

        # Set API URL and apply
        with PrefectAPIContext(api_url):
            deployment_id = str(deployment.apply(work_pool_name=work_pool_name))

            # Update deployment with working directory
            prefect_client.update_deployment(
                deployment_id=deployment_id,
                deployment=DeploymentUpdate(
                    pull_steps=[
                        {
                            "prefect.deployments.steps.set_working_directory": {
                                "directory": working_directory,
                            }
                        }
                    ],
                    path=None,
                ),
            )

            return DeploymentApplyResult(
                success=True,
                deployment_name=MANAGED_PACKET_DEPLOYMENT_NAME,
                deployment_id=deployment_id,
                work_pool_name=work_pool_name,
                work_queue_name=work_queue_name,
                entrypoint=entrypoint,
                working_directory=working_directory,
                created=not deployment_exists_before,
                prefect_runs_created=0,
                live_agents_started=0,
                entrypoint_not_inspectable=True,  # Prefect API does not reliably expose entrypoint
                working_directory_not_inspectable=True,  # Prefect API does not reliably expose working_directory
                errors=[],
            )

    except Exception as e:
        return DeploymentApplyResult(
            success=False,
            deployment_name=MANAGED_PACKET_DEPLOYMENT_NAME,
            deployment_id=None,
            work_pool_name=work_pool_name,
            work_queue_name=work_queue_name,
            entrypoint=entrypoint,
            working_directory=working_directory,
            created=False,
            prefect_runs_created=0,
            live_agents_started=0,
            entrypoint_not_inspectable=True,
            working_directory_not_inspectable=True,
            errors=[{"type": "DEPLOYMENT_APPLY_FAILED", "message": f"Failed to apply deployment: {e}"}],
        )

#END_BLOCK_DEPLOYMENT_HELPER
