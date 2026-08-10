# ############################################################################
# AI_HEADER: admin_project_service — isolated Hub project fan-out
# ROLE: Composes registry contexts and ProjectClient responses for the Admin
#       Hub API. It owns bounded concurrent health fan-out and identity checks;
#       routers only translate service results into HTTP responses.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build browser-safe project and health DTOs for the central Admin Hub.
# inputs: Immutable ProjectRegistry, optional project client factory and bounded
#          fan-out/transport settings.
# returns: Per-project DTOs and aggregate Hub health without cross-project DB
#          or filesystem access.
# side_effects: Performs bounded project-local API calls through ProjectClient.
# emitted_logs: admin_hub_fanout_start, admin_hub_project_error,
#               admin_hub_identity_mismatch, admin_hub_fanout_done.
# error_behavior: Isolates each project error and returns healthy results for
#                 other projects; unknown keys raise KeyError.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminProjectService
#     methods:
#       - list_projects
#       - get_project
#       - get_project_details
#       - get_project_health
#       - get_projects_health
#       - get_hub_health
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from grace_control.config.project_registry import (
    ProjectContext,
    ProjectRegistry,
    mask_api_endpoint,
)
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.project_client import ProjectApiResult, ProjectClient

_log = GraceLogger("admin_project_service")

_ERROR_STATUSES = frozenset({
    "api_offline",
    "timeout",
    "malformed_response",
    "identity_mismatch",
})
_SECRET_MARKERS = (
    "token",
    "password",
    "secret",
    "credential",
    "authorization",
    "private_key",
    "api_key",
)


# START_BLOCK_SERVICE
class AdminProjectService:
    """Service-layer composition for the Admin Hub project surface."""

    def __init__(
        self,
        registry: ProjectRegistry,
        *,
        client_factory: Callable[[ProjectContext], Any] | None = None,
        max_concurrency: int = 8,
        connect_timeout: float = 1.0,
        read_timeout: float = 3.0,
    ) -> None:
        if max_concurrency <= 0:
            raise ValueError("Admin Hub max_concurrency must be positive")
        self._registry = registry
        self._max_concurrency = int(max_concurrency)
        self._connect_timeout = float(connect_timeout)
        self._read_timeout = float(read_timeout)
        self._client_factory = client_factory or (
            lambda context: ProjectClient(
                context,
                connect_timeout=self._connect_timeout,
                read_timeout=self._read_timeout,
            )
        )

    # START_FUNCTION_CONTRACT
    # name: list_projects
    # purpose: Return all configured projects with default health fan-out.
    # inputs: None.
    # returns: Browser-safe projects list and fetch timestamp.
    # side_effects: Concurrently queries enabled project APIs.
    # emitted_logs: admin_hub_fanout_start, admin_hub_fanout_done.
    # error_behavior: Includes disabled and failed projects without raising.
    # END_FUNCTION_CONTRACT
    async def list_projects(self) -> dict[str, Any]:
        health_rows = await self.get_projects_health()
        health_by_key = {row["project_key"]: row for row in health_rows}
        projects = [
            _project_dto(context, health_by_key[context.key])
            for context in self._registry.list_projects()
        ]
        return {"projects": projects, "fetched_at": _now_iso()}

    # START_FUNCTION_CONTRACT
    # name: get_project
    # purpose: Resolve one explicit immutable project context by safe key.
    # inputs: project_key — registry key from the request path.
    # returns: ProjectContext for the selected project.
    # side_effects: None.
    # emitted_logs: None.
    # error_behavior: Raises KeyError for an unknown key.
    # END_FUNCTION_CONTRACT
    def get_project(self, project_key: str) -> ProjectContext:
        return self._registry.get(project_key)

    # START_FUNCTION_CONTRACT
    # name: get_project_details
    # purpose: Return one project registry DTO plus its isolated health result.
    # inputs: project_key — configured project key.
    # returns: Browser-safe project DTO.
    # side_effects: Queries only the selected enabled project API.
    # emitted_logs: admin_hub_project_error, admin_hub_identity_mismatch.
    # error_behavior: Raises KeyError for unknown keys; remote errors are DTOs.
    # END_FUNCTION_CONTRACT
    async def get_project_details(self, project_key: str) -> dict[str, Any]:
        context = self.get_project(project_key)
        health = await self._health_for_context(context)
        return _project_dto(context, health)

    # START_FUNCTION_CONTRACT
    # name: get_project_health
    # purpose: Return one normalized health DTO for an explicit project key.
    # inputs: project_key — configured project key.
    # returns: Health DTO with registry/runtime identity and isolated error.
    # side_effects: Queries the selected project unless it is disabled.
    # emitted_logs: admin_hub_project_error, admin_hub_identity_mismatch.
    # error_behavior: Raises KeyError for unknown keys; remote errors are DTOs.
    # END_FUNCTION_CONTRACT
    async def get_project_health(self, project_key: str) -> dict[str, Any]:
        context = self.get_project(project_key)
        return await self._health_for_context(context)

    # START_FUNCTION_CONTRACT
    # name: get_projects_health
    # purpose: Fan out health requests to enabled projects with bounded
    #          concurrency while retaining disabled project rows.
    # inputs: None.
    # returns: Health DTO list in registry order.
    # side_effects: Performs concurrent project-local API GET requests.
    # emitted_logs: admin_hub_fanout_start, admin_hub_fanout_done.
    # error_behavior: One failed/slow project cannot reject the list.
    # END_FUNCTION_CONTRACT
    async def get_projects_health(self) -> list[dict[str, Any]]:
        contexts = self._registry.list_projects()
        _log.info("admin_hub_fanout_start", project_count=len(contexts))
        semaphore = asyncio.Semaphore(self._max_concurrency)

        async def _run(context: ProjectContext) -> dict[str, Any]:
            if not context.enabled:
                return _disabled_health(context)
            async with semaphore:
                return await self._health_for_context(context)

        rows = await asyncio.gather(*(_run(context) for context in contexts))
        _log.info("admin_hub_fanout_done", project_count=len(rows))
        return list(rows)

    # START_FUNCTION_CONTRACT
    # name: get_hub_health
    # purpose: Return aggregate Hub health plus every isolated project health
    #          row for operator dashboards.
    # inputs: None.
    # returns: Browser-safe aggregate health DTO.
    # side_effects: Concurrently queries enabled project APIs.
    # emitted_logs: admin_hub_fanout_start, admin_hub_fanout_done.
    # error_behavior: Never raises for project transport failures.
    # END_FUNCTION_CONTRACT
    async def get_hub_health(self) -> dict[str, Any]:
        rows = await self.get_projects_health()
        enabled = [row for row in rows if row["enabled"]]
        online = [row for row in enabled if row["status"] == "online"]
        if not enabled:
            status = "disabled"
        elif len(online) == len(enabled):
            status = "online"
        elif online:
            status = "degraded"
        else:
            status = "offline"
        return {
            "status": status,
            "ok": status == "online",
            "projects": {
                "total": len(rows),
                "enabled": len(enabled),
                "online": len(online),
                "failed": len(enabled) - len(online),
                "disabled": len(rows) - len(enabled),
            },
            "health": rows,
            "fetched_at": _now_iso(),
        }

    async def _health_for_context(self, context: ProjectContext) -> dict[str, Any]:
        if not context.enabled:
            return _disabled_health(context)
        try:
            client = self._client_factory(context)
            getter = getattr(client, "get_health", None)
            if getter is None:
                getter = client.health
            result = getter()
            if inspect.isawaitable(result):
                result = await result
            normalized = _coerce_result(context, result)
        except Exception as exc:
            _log.error(
                "admin_hub_project_error",
                project_key=context.key,
                error_class="client_error",
            )
            normalized = ProjectApiResult(
                project_key=context.key,
                ok=False,
                error_class="api_offline",
                error=_safe_error(exc),
                last_attempt_at=_now_iso(),
            )
        if not normalized.ok:
            return _failed_health(context, normalized)
        payload = normalized.payload or {}
        mismatches = _identity_mismatches(context, payload)
        if mismatches:
            _log.error(
                "admin_hub_identity_mismatch",
                project_key=context.key,
                reason="registry_runtime_identity_mismatch",
            )
            return _failed_health(
                context,
                ProjectApiResult(
                    project_key=context.key,
                    ok=False,
                    error_class="identity_mismatch",
                    error="; ".join(mismatches),
                    payload=_public_json(payload),
                    http_status=normalized.http_status,
                    last_attempt_at=normalized.last_attempt_at or _now_iso(),
                ),
            )
        safe_payload = _public_json(payload)
        return {
            "project_key": context.key,
            "enabled": context.enabled,
            "ok": True,
            "status": "online",
            "error_class": None,
            "error": None,
            "last_attempt_at": normalized.last_attempt_at or _now_iso(),
            "registry": _registry_identity(context),
            "runtime": safe_payload,
        }


# END_BLOCK_SERVICE


# START_BLOCK_DTO_HELPERS
def _project_dto(context: ProjectContext, health: Mapping[str, Any]) -> dict[str, Any]:
    health_status = str(health.get("status") or "api_offline")
    if health_status == "online":
        status = "online"
    elif health_status == "disabled":
        status = "disabled"
    elif health_status == "identity_mismatch":
        status = "degraded"
    else:
        status = "offline"
    error = None
    if not health.get("ok") and health_status != "disabled":
        error = {
            "class": health.get("error_class") or health_status,
            "message": health.get("error") or health_status,
        }
    return {
        "key": context.key,
        "name": context.name,
        "enabled": context.enabled,
        "unix_user": context.unix_user,
        "project_root": str(context.project_root),
        "description": context.description,
        "tags": list(context.tags),
        "api_endpoint": mask_api_endpoint(context),
        "status": status,
        "health_status": health_status,
        "health": dict(health),
        "error": error,
    }


def _registry_identity(context: ProjectContext) -> dict[str, str | None]:
    return {
        "key": context.key,
        "name": context.name,
        "project_root": str(context.project_root),
    }


def _disabled_health(context: ProjectContext) -> dict[str, Any]:
    return {
        "project_key": context.key,
        "enabled": False,
        "ok": False,
        "status": "disabled",
        "error_class": "disabled",
        "error": None,
        "last_attempt_at": None,
        "registry": _registry_identity(context),
        "runtime": None,
    }


def _failed_health(context: ProjectContext, result: ProjectApiResult) -> dict[str, Any]:
    error_class = result.error_class or "api_offline"
    status = error_class if error_class in _ERROR_STATUSES else "api_offline"
    return {
        "project_key": context.key,
        "enabled": context.enabled,
        "ok": False,
        "status": status,
        "error_class": error_class,
        "error": result.error or status,
        "last_attempt_at": result.last_attempt_at or _now_iso(),
        "registry": _registry_identity(context),
        "runtime": _public_json(result.payload) if result.payload else None,
    }


def _coerce_result(context: ProjectContext, result: Any) -> ProjectApiResult:
    if isinstance(result, ProjectApiResult):
        return result
    if isinstance(result, Mapping):
        if result.get("ok") is False:
            return ProjectApiResult(
                project_key=context.key,
                ok=False,
                payload=_public_json(result),
                error_class=str(result.get("error_class") or "api_offline"),
                error=str(result.get("error") or "project API reported failure"),
                last_attempt_at=str(result.get("last_attempt_at") or _now_iso()),
            )
        return ProjectApiResult(
            project_key=context.key,
            ok=True,
            payload=dict(result),
            last_attempt_at=_now_iso(),
        )
    raise TypeError("project client health result must be ProjectApiResult or mapping")


def _identity_mismatches(context: ProjectContext, payload: Mapping[str, Any]) -> list[str]:
    identity = _runtime_identity(payload)
    mismatches: list[str] = []
    runtime_key = identity.get("key")
    runtime_name = identity.get("name")
    runtime_root = identity.get("root")
    if runtime_key is not None and str(runtime_key) != context.key:
        mismatches.append(f"runtime project key {runtime_key!r} != registry key {context.key!r}")
    if runtime_name is not None and str(runtime_name).strip() != context.name:
        mismatches.append(f"runtime project name {runtime_name!r} != registry name {context.name!r}")
    if runtime_root is not None:
        try:
            normalized_runtime = Path(str(runtime_root)).expanduser().resolve(strict=False)
            normalized_registry = context.project_root.expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            mismatches.append("runtime project root is not a valid path")
        else:
            if normalized_runtime != normalized_registry:
                mismatches.append(
                    f"runtime project root {normalized_runtime} != registry root {normalized_registry}"
                )
    return mismatches


def _runtime_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    candidates: list[Mapping[str, Any]] = [payload]
    for key in ("identity", "project", "runtime", "data"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            candidates.append(nested)
    return {
        "key": _first_value(candidates, "project_key", "key"),
        "name": _first_value(candidates, "project_name", "name"),
        "root": _first_value(
            candidates,
            "project_root",
            "target_repo_root",
            "runtime_target_repo_root",
            "root",
        ),
    }


def _first_value(candidates: list[Mapping[str, Any]], *keys: str) -> Any:
    for candidate in candidates:
        for key in keys:
            value = candidate.get(key)
            if value is not None and value != "":
                return value
    return None


def _public_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _public_json(item)
            for key, item in value.items()
            if not _is_secret_key(str(key))
        }
    if isinstance(value, list):
        return [_public_json(item) for item in value]
    if isinstance(value, tuple):
        return [_public_json(item) for item in value]
    return value


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(marker in normalized for marker in _SECRET_MARKERS)


def _safe_error(error: Exception) -> str:
    return str(error).replace("\n", " ").strip()[:240] or error.__class__.__name__


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# END_BLOCK_DTO_HELPERS
