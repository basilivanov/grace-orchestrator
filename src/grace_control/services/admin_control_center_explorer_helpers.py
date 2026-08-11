# ############################################################################
# AI_HEADER: admin_control_center_explorer_helpers — bounded Stage 05 view helpers
# ROLE: Normalizes explorer payloads for the project-aware Admin Control Center.
#       These helpers never perform I/O and keep raw unknown fields reachable.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide pure safety, preview and explorer normalization helpers for
#          Events, Logs, Evidence, Artifacts, Files, Git and OpenAPI views.
# inputs: JSON-like project-local API payloads and bounded UI selectors.
# returns: JSON-safe view-model fragments or explicit validation results.
# side_effects: None; helpers do not read files, databases or repositories.
# emitted_logs: None.
# error_behavior: Unsafe relative paths are rejected; malformed optional DTOs
#                 degrade to explicit unavailable/unknown values.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: _safe_relative_path
#   - function: _event_matches_text
#   - function: _artifact_kind
#   - function: _normalize_artifacts
#   - function: _normalize_worktrees
#   - function: _lease_views
#   - function: _stale_base_view
#   - function: _openapi_path_is_safe
#   - function: _openapi_operations
#   - function: _openapi_parameter_definitions
#   - function: _openapi_request
#   - function: _json_query_params
# END_MODULE_MAP

from __future__ import annotations

import json
import mimetypes
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, urlsplit

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("admin_control_center_explorer_helpers")

_MAX_ARTIFACT_ROWS = 2000
_MAX_OPENAPI_OPERATIONS = 1000
_MAX_QUERY_PARAMS = 20
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"})
_JSON_EXTENSIONS = frozenset({".json", ".jsonl", ".har"})
_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})
_TEXT_EXTENSIONS = frozenset({".txt", ".log", ".patch", ".diff", ".csv", ".yaml", ".yml", ".toml"})
_OPENAPI_PATH_PARAMETER = re.compile(r"\{([^{}]+)\}")


# START_BLOCK_PATHS
# START_FUNCTION_CONTRACT
# name: _safe_relative_path
# purpose: Validate a browser-supplied path as a named-root relative POSIX path.
# inputs: value — optional relative path from a project-local logical root.
# returns: (is_safe, normalized_path, error_code) tuple.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Absolute, traversal, backslash and NUL paths are rejected.
# END_FUNCTION_CONTRACT
def _safe_relative_path(value: Any) -> tuple[bool, str, str | None]:
    text = str(value or "")
    if "\x00" in text or "\\" in text:
        return False, "", "PATH_TRAVERSAL"
    if text.startswith("/"):
        return False, "", "ABSOLUTE_PATH_DENIED"
    parts = PurePosixPath(text).parts if text else ()
    if any(part in {".", ".."} for part in parts):
        return False, "", "PATH_TRAVERSAL"
    normalized = "/".join(part for part in parts if part)
    return True, normalized, None


# END_BLOCK_PATHS


# START_BLOCK_EVENTS
# START_FUNCTION_CONTRACT
# name: _event_matches_text
# purpose: Apply the global Events free-text filter across visible identity and
#          complete safe payload values.
# inputs: event — normalized event mapping; text — case-insensitive substring.
# returns: True when the event matches or text is empty.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for malformed payload values.
# END_FUNCTION_CONTRACT
def _event_matches_text(event: Mapping[str, Any], text: str | None) -> bool:
    if not text:
        return True
    try:
        haystack = json.dumps(dict(event), ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        haystack = str(event)
    return text.casefold() in haystack.casefold()


# END_BLOCK_EVENTS


# START_BLOCK_ARTIFACTS
# START_FUNCTION_CONTRACT
# name: _artifact_kind
# purpose: Classify an artifact for bounded preview behavior.
# inputs: name, mime, binary and size metadata.
# returns: Kind, previewable flag and safe category label.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Unknown extensions become bounded binary/file metadata.
# END_FUNCTION_CONTRACT
def _artifact_kind(
    name: Any,
    mime: Any = None,
    binary: bool = False,
    size: Any = 0,
) -> tuple[str, bool, str]:
    filename = str(name or "")
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    dot_suffix = f".{suffix}" if suffix else ""
    mime_text = str(mime or mimetypes.guess_type(filename)[0] or "application/octet-stream")
    try:
        size_value = max(0, int(size or 0))
    except (TypeError, ValueError):
        size_value = 0
    if dot_suffix in _IMAGE_EXTENSIONS or mime_text.startswith("image/"):
        return "image", size_value <= 1024 * 1024, "image"
    if dot_suffix in _JSON_EXTENSIONS or mime_text in {"application/json", "application/har+json"}:
        return "json", size_value <= 512 * 1024, "json"
    if dot_suffix in _MARKDOWN_EXTENSIONS:
        return "markdown", size_value <= 512 * 1024, "markdown"
    if dot_suffix in {".html", ".htm", ".xhtml"} or mime_text in {"text/html", "application/xhtml+xml"}:
        return "html", size_value <= 512 * 1024, "source text"
    if not binary and (mime_text.startswith("text/") or dot_suffix in _TEXT_EXTENSIONS):
        return "text", size_value <= 512 * 1024, "text"
    return "binary", False, "binary/large"


# START_FUNCTION_CONTRACT
# name: _normalize_artifacts
# purpose: Normalize bounded artifact metadata without recursively previewing it.
# inputs: raw — project-local tree/list payload.
# returns: artifact rows plus explicit truncation metadata.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Skips malformed rows and preserves safe unknown fields.
# END_FUNCTION_CONTRACT
def _normalize_artifacts(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        source_rows = raw.get("tree", raw.get("artifacts", raw.get("data", [])))
        truncated = bool(raw.get("truncated"))
        source_file = raw.get("evidence_path") or raw.get("source_file")
    else:
        source_rows = raw
        truncated = False
        source_file = None
    rows: list[dict[str, Any]] = []
    def visit(items: Any, prefix: str = "") -> None:
        nonlocal truncated
        if not isinstance(items, list):
            return
        for source in items:
            if len(rows) >= _MAX_ARTIFACT_ROWS:
                truncated = True
                return
            if not isinstance(source, Mapping):
                continue
            row = dict(source)
            name = row.get("relative_path") or row.get("path") or row.get("name") or ""
            name = str(name)
            if prefix and "/" not in name:
                name = f"{prefix}/{name}"
            kind, previewable, category = _artifact_kind(
                name,
                row.get("mime"),
                bool(row.get("binary")),
                row.get("size"),
            )
            row_kind = row.get("kind") or row.get("type") or kind
            is_directory = str(row_kind).casefold() in {"dir", "directory"}
            row.update({
                "name": str(row.get("name") or name.rsplit("/", 1)[-1]),
                "relative_path": name,
                "kind": row_kind,
                "category": "directory" if is_directory else category,
                "previewable": (
                    False
                    if is_directory
                    else bool(row.get("previewable", row.get("preview_capable", previewable))) and previewable
                ),
                "source": "API",
            })
            children = row.pop("children", None)
            rows.append(row)
            visit(children, name)

    if isinstance(source_rows, list):
        visit(source_rows)
    return {"artifacts": rows, "truncated": truncated, "source_file": source_file}


# END_BLOCK_ARTIFACTS


# START_BLOCK_GIT
# START_FUNCTION_CONTRACT
# name: _normalize_worktrees
# purpose: Add display-safe identity and display-only GRACE classifications to
#          Stage 02 Git worktree rows.
# inputs: raw worktree rows and optional packet metadata.
# returns: normalized worktree rows with no deletion actions.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Missing relationships remain explicitly unknown.
# END_FUNCTION_CONTRACT
def _normalize_worktrees(raw: Any, packet: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    packet_map = packet if isinstance(packet, Mapping) else {}
    packet_id = packet_map.get("id") or packet_map.get("packet_id")
    packet_state = str(packet_map.get("state") or "unknown")
    rows: list[dict[str, Any]] = []
    source_rows = raw.get("worktrees", raw.get("data", [])) if isinstance(raw, Mapping) else raw
    if not isinstance(source_rows, list):
        return rows
    for source in source_rows[:2000]:
        if not isinstance(source, Mapping):
            continue
        row = dict(source)
        path = str(row.get("path") or "")
        branch = str(row.get("branch") or "")
        prunable = bool(row.get("prunable"))
        exists = bool(row.get("exists", not prunable))
        row_packet_state = str(row.get("packet_state") or packet_state)
        if prunable or not exists:
            classification = "orphan_candidate"
        elif row_packet_state.casefold() in {"accepted", "ready", "merged"}:
            classification = "accepted_waiting_merge"
        elif row.get("cleanup_protected") or row_packet_state.casefold() in {"running", "claimed", "executing"}:
            classification = "cleanup_protected"
        elif row.get("stale"):
            classification = "stale"
        else:
            classification = "active"
        row.update({
            "display_path": path.rsplit("/", 1)[-1] if path else "—",
            "path_identity": path.rsplit("/", 1)[-1] if path else "unknown",
            "branch": branch or "—",
            "packet_id": row.get("packet_id") or packet_id,
            "attempt": row.get("attempt") or row.get("attempt_number"),
            "worker_id": row.get("worker_id") or row.get("worker"),
            "registered": bool(row.get("registered", True)),
            "exists": exists,
            "packet_state": row_packet_state,
            "lease_owner": row.get("lease_owner") or row.get("worker_id") or row.get("worker"),
            "size": row.get("size") or row.get("size_bytes"),
            "classification": classification,
            "source": "GIT",
        })
        rows.append(row)
    return rows


# END_BLOCK_GIT


# START_BLOCK_DIAGNOSTICS
# START_FUNCTION_CONTRACT
# name: _lease_views
# purpose: Normalize ordinary, parallel and merge lease metadata while masking
#          every fencing/secret token and retaining fingerprints only.
# inputs: diagnostics — project diagnostics mapping.
# returns: grouped lease view model.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Malformed lease rows become empty groups.
# END_FUNCTION_CONTRACT
def _lease_views(diagnostics: Any) -> dict[str, list[dict[str, Any]]]:
    data = diagnostics if isinstance(diagnostics, Mapping) else {}
    groups = {
        "ordinary": data.get("ordinary_leases", data.get("active_leases", [])),
        "parallel": data.get("active_parallel_leases", data.get("parallel_leases", [])),
        "merge": data.get("active_merge_leases", data.get("merge_leases", [])),
    }
    result: dict[str, list[dict[str, Any]]] = {}
    for name, source_rows in groups.items():
        rows: list[dict[str, Any]] = []
        if isinstance(source_rows, Mapping):
            source_rows = [source_rows]
        if not isinstance(source_rows, list):
            source_rows = []
        for source in source_rows[:2000]:
            if not isinstance(source, Mapping):
                continue
            row = {
                key: value
                for key, value in source.items()
                if (
                    ("token" not in str(key).casefold() and "fencing" not in str(key).casefold())
                    or str(key).casefold().endswith("_fingerprint")
                )
            }
            given_fingerprint = next((value for key, value in source.items() if str(key).casefold().endswith("_fingerprint")), None)
            token = next((value for key, value in source.items() if ("token" in str(key).casefold() or "fencing" in str(key).casefold()) and not str(key).casefold().endswith("_fingerprint")), None)
            if given_fingerprint not in (None, ""):
                row["token_fingerprint"] = str(given_fingerprint)
            elif token not in (None, ""):
                row["token_fingerprint"] = _fingerprint(token)
            row["lease_type"] = name
            row["source"] = "API"
            rows.append(row)
        result[name] = rows
    return result


# START_FUNCTION_CONTRACT
# name: _stale_base_view
# purpose: Normalize stale-base and integration-recheck lifecycle fields from
#          packet/run/project/Git source DTOs.
# inputs: packet, selected run, project card and optional repository DTO.
# returns: stable stale-base view preserving unknown failure classes.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Missing values render as unknown rather than healthy defaults.
# END_FUNCTION_CONTRACT
def _stale_base_view(
    packet: Mapping[str, Any] | None,
    run: Mapping[str, Any] | None,
    project: Mapping[str, Any] | None,
    repository: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    packet_map = packet if isinstance(packet, Mapping) else {}
    run_map = run if isinstance(run, Mapping) else {}
    project_map = project if isinstance(project, Mapping) else {}
    repository_map = repository if isinstance(repository, Mapping) else {}
    result_json = run_map.get("result_json") if isinstance(run_map.get("result_json"), Mapping) else {}
    parallel = result_json.get("parallel_execution") if isinstance(result_json.get("parallel_execution"), Mapping) else {}
    base_sha = packet_map.get("base_sha") or run_map.get("base_sha") or parallel.get("base_sha")
    current_head = (
        repository_map.get("head")
        or repository_map.get("target_branch_head")
        or project_map.get("target_head")
        or project_map.get("target_branch_head")
    )
    recheck = (
        packet_map.get("integration_recheck")
        or packet_map.get("stale_base_recheck")
        or run_map.get("integration_recheck")
        or parallel.get("integration_recheck")
    )
    failure_class = (
        packet_map.get("failure_class")
        or run_map.get("failure_class")
        or parallel.get("failure_class")
    )
    stale = packet_map.get("stale_base")
    if stale is None and base_sha and current_head:
        stale = str(base_sha) != str(current_head)
    return {
        "base_sha": base_sha,
        "current_head": current_head,
        "target_head": repository_map.get("target_branch_head") or project_map.get("target_head"),
        "stale": stale if stale is not None else None,
        "integration_recheck": recheck or "unknown",
        "integration_base_sha": packet_map.get("integration_base_sha") or run_map.get("integration_base_sha") or parallel.get("integration_base_sha"),
        "failure_class": failure_class or "unknown",
        "known_failure_class": failure_class in {
            "stale_base_conflict",
            "integration_verification_failed",
            "missing_base_sha",
            "merge_conflict",
        },
        "evidence": parallel.get("integration_recheck_evidence") or result_json.get("integration_recheck_evidence") or {},
        "source": "API",
    }


# END_BLOCK_DIAGNOSTICS


# START_BLOCK_OPENAPI
# START_FUNCTION_CONTRACT
# name: _schema_from_responses
# purpose: Select the first useful response schema from an OpenAPI response map.
# inputs: responses — OpenAPI responses mapping.
# returns: JSON-safe content/schema mapping.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns an empty mapping when no response schema is present.
# END_FUNCTION_CONTRACT
def _schema_from_responses(responses: Mapping[str, Any]) -> Any:
    for response in responses.values():
        if not isinstance(response, Mapping):
            continue
        content = response.get("content")
        if isinstance(content, Mapping):
            return content
        if response.get("schema") is not None:
            return response.get("schema")
    return {}


# START_FUNCTION_CONTRACT
# name: _openapi_path_is_safe
# purpose: Accept only same-origin OpenAPI path components for the discovered
#          GET executor and reject URL authorities, fragments and queries.
# inputs: value — raw OpenAPI path key.
# returns: True when value is a strict absolute path component.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Malformed, network-path, scheme-bearing, query-bearing or
#                 fragment-bearing values are rejected.
# END_FUNCTION_CONTRACT
def _openapi_path_is_safe(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
        return False
    if "\\" in value or "?" in value or "#" in value:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return not parsed.scheme and not parsed.netloc and not parsed.query and not parsed.fragment


# START_FUNCTION_CONTRACT
# name: _openapi_parameter_definitions
# purpose: Extract bounded scalar path/query parameters that are safe to expose
#          to the discovered GET executor.
# inputs: parameters — OpenAPI parameter objects, including path-level entries.
# returns: Deduplicated executable parameter definitions.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Header, cookie, body, reference and structured parameters are
#                 documentation-only and are not executable selectors.
# END_FUNCTION_CONTRACT
def _openapi_parameter_definitions(parameters: Any) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    if not isinstance(parameters, list):
        return definitions
    for parameter in parameters[:100]:
        if not isinstance(parameter, Mapping):
            continue
        name = parameter.get("name")
        location = str(parameter.get("in") or "").casefold()
        schema = parameter.get("schema")
        if not isinstance(name, str) or not name or location not in {"path", "query"}:
            continue
        if not isinstance(schema, Mapping):
            continue
        schema_type = str(schema.get("type") or "string").casefold()
        if schema_type in {"array", "object"}:
            continue
        identity = (location, name)
        if identity in seen:
            continue
        seen.add(identity)
        definitions.append({
            "name": name,
            "in": location,
            "required": bool(parameter.get("required")) or location == "path",
            "description": str(parameter.get("description") or ""),
            "schema": dict(schema),
        })
    return definitions


# START_FUNCTION_CONTRACT
# name: _openapi_operations
# purpose: Convert a selected project's OpenAPI paths into bounded executable
#          GET and documentation-only mutation rows.
# inputs: document — OpenAPI mapping.
# returns: operation rows and exact discovered GET path set.
# side_effects: None.
# error_behavior: Malformed paths are skipped; no browser path is inferred.
# END_FUNCTION_CONTRACT
def _openapi_operations(document: Any) -> tuple[list[dict[str, Any]], set[str]]:
    paths = document.get("paths") if isinstance(document, Mapping) else {}
    operations: list[dict[str, Any]] = []
    get_paths: set[str] = set()
    if not isinstance(paths, Mapping):
        return operations, get_paths
    for raw_path, item in list(paths.items())[:_MAX_OPENAPI_OPERATIONS]:
        if not _openapi_path_is_safe(raw_path) or not isinstance(item, Mapping):
            continue
        common_parameters = item.get("parameters", [])
        for method, operation in item.items():
            method_upper = str(method).upper()
            if method_upper not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"} or not isinstance(operation, Mapping):
                continue
            parameters = list(common_parameters) if isinstance(common_parameters, list) else []
            if isinstance(operation.get("parameters"), list):
                parameters.extend(operation["parameters"])
            responses = operation.get("responses") if isinstance(operation.get("responses"), Mapping) else {}
            response_schema = _schema_from_responses(responses)
            request_body = operation.get("requestBody") if isinstance(operation.get("requestBody"), Mapping) else {}
            row = {
                "method": method_upper,
                "path": raw_path,
                "summary": operation.get("summary") or "",
                "description": operation.get("description") or "",
                "parameters": parameters[:100],
                "parameter_definitions": _openapi_parameter_definitions(parameters),
                "request_schema": request_body.get("content", {}) if isinstance(request_body, Mapping) else {},
                "response_schema": response_schema,
                "mutation": method_upper not in {"GET", "HEAD", "OPTIONS"},
                "can_execute": method_upper == "GET",
                "source": "API",
            }
            operations.append(row)
            if method_upper == "GET":
                get_paths.add(raw_path)
    operations.sort(key=lambda row: (row["path"], row["method"]))
    return operations, get_paths


# START_FUNCTION_CONTRACT
# name: _openapi_request
# purpose: Validate discovered GET parameters and materialize a safe route plus
#          query mapping without permitting arbitrary selectors.
# inputs: path — discovered OpenAPI template; operation — discovered GET row;
#         params — bounded scalar values keyed by declared parameter name.
# returns: (request_path, query_params, error) tuple.
# side_effects: None.
# error_behavior: Rejects undeclared values, missing path/query requirements,
#                 unresolved templates and overlong materialized routes.
# END_FUNCTION_CONTRACT
def _openapi_request(
    path: str,
    operation: Mapping[str, Any],
    params: Mapping[str, Any],
) -> tuple[str, dict[str, Any], str | None]:
    if not _openapi_path_is_safe(path):
        return path, {}, "API_PATH_INVALID"
    definitions = operation.get("parameter_definitions", [])
    if not isinstance(definitions, list):
        definitions = []
    declared = {
        str(item.get("name")): item
        for item in definitions
        if isinstance(item, Mapping) and item.get("name")
    }
    if any(key not in declared for key in params):
        return path, {}, "API_PARAMS_UNDECLARED"
    path_values: dict[str, str] = {}
    query_values: dict[str, str] = {}
    for name, definition in declared.items():
        location = str(definition.get("in") or "")
        required = bool(definition.get("required"))
        if name not in params:
            if required or location == "path":
                return path, {}, "API_PATH_PARAM_REQUIRED" if location == "path" else "API_QUERY_PARAM_REQUIRED"
            continue
        if isinstance(params[name], (Mapping, list, tuple)):
            return path, {}, "API_PARAM_INVALID"
        value = str(params[name])
        if not value and (required or location == "path"):
            return path, {}, "API_PATH_PARAM_REQUIRED" if location == "path" else "API_QUERY_PARAM_REQUIRED"
        if location == "path":
            path_values[name] = value
        elif location == "query":
            query_values[name] = value

    placeholders = set(_OPENAPI_PATH_PARAMETER.findall(path))
    if placeholders - set(path_values):
        return path, {}, "API_PATH_PARAM_REQUIRED"
    if set(path_values) - placeholders:
        return path, {}, "API_PATH_PARAM_UNDECLARED"
    request_path = _OPENAPI_PATH_PARAMETER.sub(
        lambda match: quote(path_values[match.group(1)], safe="-_.~"),
        path,
    )
    if "{" in request_path or "}" in request_path or len(request_path) > 4096:
        return path, {}, "API_PATH_INVALID"
    return request_path, query_values, None


# START_FUNCTION_CONTRACT
# name: _json_query_params
# purpose: Parse a bounded JSON object of GET query/path parameters for a
#          discovered OpenAPI operation.
# inputs: value — optional JSON object string from the browser.
# returns: params mapping, error string or None.
# side_effects: None.
# error_behavior: Rejects nulls, arrays, nested objects, excessive keys and
#                 malformed JSON before any project request is attempted.
# END_FUNCTION_CONTRACT
def _json_query_params(value: str | None) -> tuple[dict[str, Any], str | None]:
    if not value:
        return {}, None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}, "API_PARAMS_INVALID"
    if not isinstance(parsed, Mapping) or len(parsed) > _MAX_QUERY_PARAMS:
        return {}, "API_PARAMS_INVALID"
    result: dict[str, Any] = {}
    for key, item in parsed.items():
        if not isinstance(key, str) or not key or item is None or isinstance(item, (Mapping, list, tuple)):
            return {}, "API_PARAMS_INVALID"
        text = str(item)
        if len(text) > 512:
            return {}, "API_PARAMS_INVALID"
        result[key] = text
    return result, None


# START_FUNCTION_CONTRACT
# name: _json_preview
# purpose: Decode a bounded JSON artifact only when its content is complete.
# inputs: content — optional text; kind — artifact classification.
# returns: structured JSON value or None when unavailable/incomplete.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Invalid or truncated JSON remains raw text only.
# END_FUNCTION_CONTRACT
def _json_preview(content: Any, kind: str) -> Any:
    if kind != "json" or not isinstance(content, str):
        return None
    try:
        return json.loads(content)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


# END_BLOCK_OPENAPI


# START_FUNCTION_CONTRACT
# name: _fingerprint
# purpose: Produce a short non-reversible lease token fingerprint.
# inputs: value — secret token-like value.
# returns: Stable short fingerprint string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises; empty values produce an empty fingerprint.
# END_FUNCTION_CONTRACT
def _fingerprint(value: Any) -> str:
    import hashlib

    if value in (None, ""):
        return ""
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:12]
