# ############################################################################
# AI_HEADER: admin_control_center_explorer_service — Files, Git and OpenAPI owner
# ROLE: Owns bounded project-scoped filesystem, Git and discovered OpenAPI
#       explorer reads while keeping mutations behind AdminMutationService.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Compose Files, Git and OpenAPI explorer view models for one explicit
#          registry project without bypassing the Hub or safety helpers.
# inputs: AdminProjectAccess, project shell, mutation owner and explorer selectors.
# returns: Existing JSON-safe explorer dictionaries.
# side_effects: Bounded selected-project reads and one delegated OpenAPI mutation
#               when the explicit control gate permits it.
# emitted_logs: Hub-owned project read logs and AdminMutationService logs.
# error_behavior: Unsafe paths and undiscovered operations are rejected locally;
#                 typed project capability errors remain visible in DTOs.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: AdminControlCenterExplorerService
#     methods:
#       - files_page
#       - git_page
#       - api_page
#       - cached_openapi
#   - function: _json_body
#   - function: _json_confirmation
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from typing import Any

from grace_control.core.structured_logger import GraceLogger
from grace_control.services.admin_control_center_explorer_helpers import (
    _json_query_params,
    _normalize_worktrees,
    _openapi_operations,
    _openapi_request,
    _safe_relative_path,
)
from grace_control.services.admin_control_center_helpers import (
    _capability_message,
    _mask_secrets,
    _unwrap,
)
from grace_control.services.admin_control_center_project_shell import AdminControlCenterProjectShell
from grace_control.services.admin_mutation_service import AdminMutationService
from grace_control.services.admin_project_access import AdminProjectAccess

_log = GraceLogger("admin_control_center")

_OPENAPI_CACHE_TTL_SECONDS = 5.0


# START_BLOCK_PARSERS
# START_FUNCTION_CONTRACT
# name: _json_body
# purpose: Parse a bounded OpenAPI mutation body object.
# inputs: value — optional JSON object string.
# returns: (mapping, error) pair.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Arrays, oversized values and malformed JSON reject.
# END_FUNCTION_CONTRACT
def _json_body(value: str | None) -> tuple[dict[str, Any], str | None]:
    if not value:
        return {}, None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, "API_BODY_INVALID"
    if not isinstance(parsed, Mapping) or len(parsed) > 32 or len(value) > 64 * 1024:
        return {}, "API_BODY_INVALID"
    return dict(parsed), None


# START_FUNCTION_CONTRACT
# name: _json_confirmation
# purpose: Parse explicit server-enforced Control Center confirmation JSON.
# inputs: value — optional JSON object/string.
# returns: confirmation mapping/string or error.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Missing/malformed values reject before remote mutation.
# END_FUNCTION_CONTRACT
def _json_confirmation(value: str | None) -> tuple[dict[str, Any] | str, str | None]:
    if not value:
        return {}, "CONFIRMATION_REQUIRED"
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, "CONFIRMATION_INVALID"
    if isinstance(parsed, Mapping):
        return dict(parsed), None
    if isinstance(parsed, str):
        return parsed, None
    return {}, "CONFIRMATION_INVALID"


# END_BLOCK_PARSERS


# START_BLOCK_SERVICE
class AdminControlCenterExplorerService:
    """Own bounded Files, Git and OpenAPI explorer composition."""

    # START_FUNCTION_CONTRACT
    # name: __init__
    # purpose: Bind explorer composition to explicit access, shell and mutation
    #          collaborators.
    # inputs: access — project read/cache boundary; shell — selector owner;
    #         mutation — one app-scoped guarded mutation owner.
    # returns: None.
    # side_effects: None; cache storage is owned by AdminProjectAccess.
    # emitted_logs: None.
    # error_behavior: Collaborator contract errors propagate at construction.
    # END_FUNCTION_CONTRACT
    def __init__(
        self,
        access: AdminProjectAccess,
        shell: AdminControlCenterProjectShell,
        mutation: AdminMutationService,
    ) -> None:
        self._access = access
        self._shell = shell
        self._mutation = mutation

    # START_FUNCTION_CONTRACT
    # name: files_page
    # purpose: Build a project-scoped named-root filesystem explorer with
    #          bounded directory, stat and preview reads.
    # inputs: project_key; logical root/path; optional preview_path and tail.
    # returns: Files view model with roots, entries, preview and typed errors.
    # side_effects: Reads selected project filesystem endpoints only.
    # emitted_logs: Hub-owned project read logs.
    # error_behavior: Unsafe paths are rejected before remote reads.
    # END_FUNCTION_CONTRACT
    async def files_page(
        self,
        project_key: str,
        *,
        root: str | None = None,
        path: str = "",
        preview_path: str | None = None,
        tail: int = 0,
    ) -> dict[str, Any]:
        shell = await self._shell.explorer_shell(project_key)
        model: dict[str, Any] = {
            **shell,
            "root": root or "",
            "path": path or "",
            "entries": [],
            "roots": [],
            "preview": None,
            "stat": None,
            "preview_path": preview_path or "",
            "path_error": None,
            "error": None,
            "source": "FILE",
            "capability_available": False,
        }
        context = self._access.context(project_key)
        if not context.enabled:
            model["error"] = "Project is disabled; filesystem capability was not requested."
            return model
        roots_result = await self._access.read(project_key, "/api/admin/fs/roots", operation="filesystem_roots")
        roots_payload = _unwrap(roots_result.get("payload")) if roots_result.get("ok") else {}
        roots = roots_payload.get("roots", []) if isinstance(roots_payload, Mapping) else []
        if not roots_result.get("ok"):
            model["error"] = _capability_message(roots_result)
            model["error_class"] = roots_result.get("error_class")
            model["http_status"] = roots_result.get("http_status")
            return model
        model["capability_available"] = True
        model["roots"] = [dict(item) for item in roots if isinstance(item, Mapping)]
        root_names = [str(item.get("root")) for item in model["roots"] if item.get("root")]
        selected_root = str(root or (root_names[0] if root_names else ""))
        model["root"] = selected_root
        if selected_root not in root_names:
            model["error"] = "The selected filesystem root is not advertised by this project."
            model["error_class"] = "ROOT_NOT_FOUND"
            return model
        safe, clean_path, path_error = _safe_relative_path(path)
        if not safe:
            model["path_error"] = {"code": path_error, "message": "Only a relative logical path is allowed."}
            return model
        model["path"] = clean_path
        listing_result = await self._access.read(
            project_key,
            "/api/admin/fs/list",
            params={"root": selected_root, "path": clean_path},
            operation="filesystem_list",
        )
        listing = _unwrap(listing_result.get("payload")) if listing_result.get("ok") else {}
        if listing_result.get("ok"):
            model["entries"] = [
                {**dict(entry), "source": "FILE"}
                for entry in listing.get("entries", [])
                if isinstance(entry, Mapping)
            ]
            model["truncated"] = bool(listing.get("truncated"))
        else:
            model["error"] = _capability_message(listing_result)
            model["error_class"] = listing_result.get("error_class")
            model["http_status"] = listing_result.get("http_status")
        if preview_path:
            preview_safe, clean_preview, preview_error = _safe_relative_path(preview_path)
            model["preview_path"] = clean_preview if preview_safe else str(preview_path)
            if not preview_safe:
                model["path_error"] = {"code": preview_error, "message": "Only a relative logical path is allowed."}
                return model
            endpoint = "/api/admin/fs/tail" if tail and tail > 0 else "/api/admin/fs/file"
            params: dict[str, Any] = {"root": selected_root, "path": clean_preview}
            stat_result = await self._access.read(
                project_key,
                "/api/admin/fs/stat",
                params={"root": selected_root, "path": clean_preview},
                operation="filesystem_stat",
            )
            if stat_result.get("ok"):
                model["stat"] = {**_unwrap(stat_result.get("payload")), "source": "FILE"}
            if tail and tail > 0:
                params["lines"] = min(int(tail), 1000)
            else:
                params["max_bytes"] = 512 * 1024
            preview_result = await self._access.read(
                project_key,
                endpoint,
                params=params,
                operation="filesystem_preview",
            )
            if preview_result.get("ok"):
                preview = _unwrap(preview_result.get("payload"))
                preview["source"] = "FILE"
                model["preview"] = preview
            else:
                model["error"] = _capability_message(preview_result)
                model["error_class"] = preview_result.get("error_class")
                model["http_status"] = preview_result.get("http_status")
        return model

    # START_FUNCTION_CONTRACT
    # name: git_page
    # purpose: Build a bounded project/packet Git explorer from explicit read APIs.
    # inputs: project_key; optional packet metadata and ref/path selectors.
    # returns: Repository, worktree, changed-file and diff view model.
    # side_effects: Reads selected project Git APIs only.
    # emitted_logs: Hub-owned project read logs.
    # error_behavior: Git validation errors remain typed in the view model.
    # END_FUNCTION_CONTRACT
    async def git_page(
        self,
        project_key: str,
        *,
        packet: Mapping[str, Any] | None = None,
        ref: str | None = None,
        path: str | None = None,
    ) -> dict[str, Any]:
        shell = await self._shell.explorer_shell(project_key)
        model: dict[str, Any] = {
            **shell,
            "repository": {},
            "worktrees": [],
            "changed_files": [],
            "diff_stat": {},
            "diff": {},
            "packet_git": {},
            "ref": ref or "",
            "path": path or "",
            "error": None,
            "source": "GIT",
        }
        context = self._access.context(project_key)
        if not context.enabled:
            model["error"] = "Project is disabled; Git capability was not requested."
            return model
        repository_result, worktree_result, changed_result = await self._gather_git_reads(project_key, ref)
        if repository_result.get("ok"):
            model["repository"] = _mask_secrets(_unwrap(repository_result.get("payload")))
            if isinstance(model["repository"], Mapping):
                repository = dict(model["repository"])
                repo_root = str(repository.get("repo_root") or "")
                repository["repo_display"] = repo_root.rstrip("/").rsplit("/", 1)[-1] if repo_root else "unknown"
                model["repository"] = repository
        if worktree_result.get("ok"):
            worktrees_payload = _unwrap(worktree_result.get("payload"))
            model["worktrees"] = _normalize_worktrees(worktrees_payload, packet)
        if changed_result.get("ok"):
            changed_payload = _unwrap(changed_result.get("payload"))
            model["changed_files"] = [
                {**dict(row), "source": "GIT"}
                for row in changed_payload.get("changed_files", changed_payload.get("data", []))
                if isinstance(row, Mapping)
            ]
        selected_path_allowed = not path or not changed_result.get("ok") or any(
            str(row.get("path") or "") == str(path)
            for row in model["changed_files"]
        )
        if path and changed_result.get("ok") and not selected_path_allowed:
            model["error"] = "GIT_PATH_NOT_CHANGED"
            model["error_class"] = "GIT_PATH_NOT_CHANGED"
            stat_result: dict[str, Any] = {"ok": False, "error": "GIT_PATH_NOT_CHANGED"}
            diff_result: dict[str, Any] = {"ok": False, "error": "GIT_PATH_NOT_CHANGED"}
        else:
            stat_result, diff_result = await self._gather_git_diffs(project_key, ref, path)
        if stat_result.get("ok"):
            model["diff_stat"] = {**_unwrap(stat_result.get("payload")), "source": "GIT"}
        if diff_result.get("ok"):
            model["diff"] = {**_unwrap(diff_result.get("payload")), "source": "GIT"}
        failures = [
            result
            for result in (repository_result, worktree_result, changed_result, stat_result, diff_result)
            if not result.get("ok")
        ]
        if path and changed_result.get("ok") and not selected_path_allowed:
            failures = []
        if failures:
            model["error"] = _capability_message(failures[0])
            model["error_class"] = failures[0].get("error_class")
            model["http_status"] = failures[0].get("http_status")
        packet_map = packet if isinstance(packet, Mapping) else {}
        model["packet_git"] = {
            "branch": packet_map.get("branch") or packet_map.get("branch_name") or "unknown",
            "commit": packet_map.get("commit_sha") or packet_map.get("head_sha") or packet_map.get("merge_commit") or "unknown",
            "base_sha": packet_map.get("base_sha"),
            "integration_base_sha": packet_map.get("integration_base_sha"),
            "merge_commit": packet_map.get("merge_commit"),
            "merge_status": packet_map.get("merge_status") or packet_map.get("integration_recheck"),
            "source": "API",
        }
        return model

    # START_FUNCTION_CONTRACT
    # name: api_page
    # purpose: Discover exact OpenAPI operations and execute only an authorized
    #          discovered GET or delegated mutation.
    # inputs: project_key; path/method/execution selectors and bounded JSON gate
    #         values.
    # returns: API documentation plus response or typed error DTO.
    # side_effects: Reads /openapi.json and optionally one exact GET or delegated
    #               AdminMutationService mutation.
    # emitted_logs: Hub-owned project read and mutation service logs.
    # error_behavior: Arbitrary paths and gated mutations are rejected without
    #                 an unsafe project request.
    # END_FUNCTION_CONTRACT
    async def api_page(
        self,
        project_key: str,
        *,
        path: str | None = None,
        execute: bool = False,
        params_json: str | None = None,
        method: str = "GET",
        control_mode: bool = False,
        body_json: str | None = None,
        confirmation_json: str | None = None,
        actor: str = "operator",
        allow_mutation: bool = False,
    ) -> dict[str, Any]:
        shell = await self._shell.explorer_shell(project_key)
        model: dict[str, Any] = {
            **shell,
            "document": {},
            "operations": [],
            "selected_path": path or "",
            "request_path": "",
            "request_params": {},
            "params_display": "",
            "body_display": "",
            "confirmation_display": "",
            "response": None,
            "response_status": None,
            "response_headers": {},
            "response_error": None,
            "mutation_execution_disabled": not control_mode,
            "control_mode": bool(control_mode),
            "selected_method": str(method or "GET").upper(),
            "mutation_response": None,
            "execution_requested": bool(execute),
            "source": "API",
        }
        context = self._access.context(project_key)
        if not context.enabled:
            model["response_error"] = "Project is disabled; API discovery was not requested."
            return model
        openapi_result = await self._cached_openapi(project_key)
        if not openapi_result.get("ok"):
            model["response_error"] = _capability_message(openapi_result)
            model["error_class"] = openapi_result.get("error_class")
            return model
        document = _unwrap(openapi_result.get("payload"))
        operations, get_paths = _openapi_operations(document)
        model["document"] = _mask_secrets(document)
        model["operations"] = _mask_secrets(operations)
        if not execute:
            return model
        selected_path = str(path or "")
        selected_method = str(method or "GET").upper()
        operation = next(
            (
                row
                for row in operations
                if row.get("method") == selected_method and row.get("path") == selected_path
            ),
            None,
        )
        if selected_method == "GET" and selected_path not in get_paths:
            operation = None
        if operation is None:
            model["response_error"] = "API_PATH_NOT_DISCOVERED"
            return model
        params, params_error = _json_query_params(params_json)
        if params_error:
            model["response_error"] = params_error
            return model
        model["params_display"] = json.dumps(_mask_secrets(params), ensure_ascii=False, sort_keys=True)
        request_path, query_params, request_error = _openapi_request(selected_path, operation, params)
        if request_error:
            model["response_error"] = request_error
            return model
        model["request_path"] = request_path
        model["request_params"] = _mask_secrets(query_params)
        if selected_method != "GET":
            await self._execute_mutation(
                model,
                project_key=project_key,
                selected_path=selected_path,
                selected_method=selected_method,
                execute=execute,
                control_mode=control_mode,
                allow_mutation=allow_mutation,
                params=params,
                body_json=body_json,
                confirmation_json=confirmation_json,
                actor=actor,
                request_path=request_path,
                query_params=query_params,
            )
            return model
        result = await self._access.read(
            project_key,
            request_path,
            params=query_params,
            operation="api_explorer_get",
        )
        model["response_status"] = result.get("http_status")
        model["response_headers"] = result.get("headers") or {}
        if result.get("ok"):
            model["response"] = {
                "body": _mask_secrets(_unwrap(result.get("payload"))),
                "headers": result.get("headers") or {},
                "request_path": request_path,
                "request_params": _mask_secrets(query_params),
                "source": "API",
                "truncated": False,
            }
        else:
            model["response_error"] = result.get("error") or result.get("error_class")
        return model

    # START_FUNCTION_CONTRACT
    # name: _cached_openapi
    # purpose: Read and short-term cache a successful project OpenAPI document.
    # inputs: project_key — explicit registry key.
    # returns: Normalized project read result for /openapi.json.
    # side_effects: At most one bounded project GET per TTL.
    # emitted_logs: Hub-owned project read logs on cache misses.
    # error_behavior: Errors are returned uncached.
    # END_FUNCTION_CONTRACT
    async def _cached_openapi(self, project_key: str) -> dict[str, Any]:
        now = time.monotonic()
        cached = self._access.openapi_cache.get(project_key)
        if cached is not None and now - cached[0] < _OPENAPI_CACHE_TTL_SECONDS:
            return cached[1]
        result = await self._access.read(project_key, "/openapi.json", operation="openapi")
        if result.get("ok"):
            self._access.openapi_cache[project_key] = (now, result)
        return result

    # START_FUNCTION_CONTRACT
    # name: _gather_git_reads
    # purpose: Fan out the bounded repository, worktree and changed-file reads.
    # inputs: project_key and optional Git ref.
    # returns: Repository, worktree and changed-file result mappings.
    # side_effects: Three selected-project GET requests.
    # emitted_logs: Hub-owned Git read logs.
    # error_behavior: Typed failures are returned, not raised.
    # END_FUNCTION_CONTRACT
    async def _gather_git_reads(
        self,
        project_key: str,
        ref: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        return await asyncio.gather(
            self._access.read(project_key, "/api/admin/git/repository", operation="git_repository"),
            self._access.read(project_key, "/api/admin/git/worktrees", operation="git_worktrees"),
            self._access.read(
                project_key,
                "/api/admin/git/changed-files",
                params={"ref": ref} if ref else None,
                operation="git_changed_files",
            ),
        )

    # START_FUNCTION_CONTRACT
    # name: _gather_git_diffs
    # purpose: Fan out the bounded Git diff-stat and diff reads.
    # inputs: project_key and optional ref/path selectors.
    # returns: Diff-stat and diff result mappings.
    # side_effects: Two selected-project GET requests.
    # emitted_logs: Hub-owned Git read logs.
    # error_behavior: Typed failures are returned, not raised.
    # END_FUNCTION_CONTRACT
    async def _gather_git_diffs(
        self,
        project_key: str,
        ref: str | None,
        path: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        params = {"ref": ref, "path": path} if ref or path else None
        return await asyncio.gather(
            self._access.read(project_key, "/api/admin/git/diff-stat", params=params, operation="git_diff_stat"),
            self._access.read(project_key, "/api/admin/git/diff", params=params, operation="git_diff"),
        )

    # START_FUNCTION_CONTRACT
    # name: _execute_mutation
    # purpose: Apply the existing control/confirmation gate and delegate one
    #          discovered OpenAPI mutation to AdminMutationService.
    # inputs: model and exact operation/request values.
    # returns: None; mutates the in-progress JSON-safe model only.
    # side_effects: At most one selected-project mutation through the owner.
    # emitted_logs: AdminMutationService mutation audit logs.
    # error_behavior: Gate and validation failures become existing response_error.
    # END_FUNCTION_CONTRACT
    async def _execute_mutation(
        self,
        model: dict[str, Any],
        *,
        project_key: str,
        selected_path: str,
        selected_method: str,
        execute: bool,
        control_mode: bool,
        allow_mutation: bool,
        params: Mapping[str, Any],
        body_json: str | None,
        confirmation_json: str | None,
        actor: str,
        request_path: str,
        query_params: Mapping[str, Any],
    ) -> None:
        if not execute:
            return
        if not control_mode:
            model["response_error"] = "API_CONTROL_MODE_REQUIRED"
            return
        if not allow_mutation:
            model["response_error"] = None
            return
        body, body_error = _json_body(body_json)
        if body_error:
            model["response_error"] = body_error
            return
        model["body_display"] = json.dumps(_mask_secrets(body), ensure_ascii=False, sort_keys=True)
        confirmation, confirmation_error = _json_confirmation(confirmation_json)
        if confirmation_error:
            model["response_error"] = confirmation_error
            return
        model["confirmation_display"] = json.dumps(
            _mask_secrets(confirmation), ensure_ascii=False, sort_keys=True,
        )
        mutation = await self._mutation.execute_openapi(
            project_key,
            path=selected_path,
            method=selected_method,
            confirmation=confirmation,
            parameters={**params},
            body=body,
            actor=actor,
        )
        model["mutation_response"] = mutation
        model["response_status"] = mutation.get("status")
        if mutation.get("ok"):
            model["response"] = {
                "body": mutation.get("response") or {},
                "headers": {},
                "request_path": request_path,
                "request_params": _mask_secrets(query_params),
                "source": "API",
                "mutation": True,
            }
        else:
            model["response_error"] = (
                mutation.get("display_message")
                or mutation.get("error")
                or mutation.get("error_code")
            )


# END_BLOCK_SERVICE
