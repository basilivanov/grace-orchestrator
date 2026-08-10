# ############################################################################
# AI_HEADER: admin_cross_project_helpers — shared normalization for Admin Hub fan-out
# ROLE: Provides private, deterministic helpers used by the cross-project
#       observability service. It keeps transport coercion, DTO normalization,
#       cursor handling and attention classification out of the service facade.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Normalize project-local observability responses into safe Hub DTOs.
# inputs: Project contexts, remote API results and JSON-compatible payloads.
# returns: Private helper values used by AdminCrossProjectService.
# side_effects: None; helpers do not perform I/O or mutate project state.
# emitted_logs: None.
# error_behavior: Invalid limits, cursors and timestamps raise ValueError where
#                 the service contract requires explicit rejection.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: _RemoteResult
#     methods: []
# END_MODULE_MAP

from __future__ import annotations

import base64
import inspect
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from grace_control.config.project_registry import ProjectContext
from grace_control.core.structured_logger import GraceLogger
from grace_control.services.project_client import ProjectApiResult

_log = GraceLogger("admin_cross_project_helpers")

_SECRET_MARKERS = (
    "token",
    "password",
    "secret",
    "credential",
    "authorization",
    "private_key",
    "api_key",
    "fencing",
)


# START_BLOCK_INTERNAL_MODELS
@dataclass(frozen=True, slots=True)
class _RemoteResult:
    context: ProjectContext
    ok: bool
    payload: dict[str, Any] | None = None
    error_class: str | None = None
    error: str | None = None
    http_status: int | None = None
    headers: dict[str, str] | None = None


# END_BLOCK_INTERNAL_MODELS


# START_BLOCK_HELPERS
def _selector_values(project: Sequence[str] | str) -> list[str]:
    values = [project] if isinstance(project, str) else list(project)
    result: list[str] = []
    for value in values:
        result.extend(item.strip() for item in str(value).split(",") if item.strip())
    return list(dict.fromkeys(result))


async def _invoke_client(
    client: Any,
    path: str,
    query_path: str,
    params: Mapping[str, Any],
    operation: str,
) -> Any:
    getter = getattr(client, "get_json", None)
    if operation == "health":
        health_getter = getattr(client, "get_health", None)
        if health_getter is not None:
            result = health_getter()
            return await result if inspect.isawaitable(result) else result
    if getter is not None:
        result = getter(query_path)
        return await result if inspect.isawaitable(result) else result
    named_methods = {
        "health": "get_health",
        "diagnostics": "get_diagnostics",
        "events": "get_events",
        "logs": "get_logs",
        "search": "search",
    }
    method = getattr(client, named_methods.get(operation, ""), None)
    if method is None:
        raise RuntimeError(f"project client does not support {operation}")
    if operation == "health":
        result = method()
    else:
        try:
            result = method(dict(params))
        except TypeError:
            result = method(**dict(params))
    return await result if inspect.isawaitable(result) else result


def _coerce_remote(context: ProjectContext, raw: Any) -> _RemoteResult:
    if isinstance(raw, ProjectApiResult):
        return _RemoteResult(
            context,
            raw.ok,
            _safe_json(raw.payload) if raw.payload else None,
            raw.error_class,
            _safe_error_text(raw.error),
            raw.http_status,
            raw.headers,
        )
    if isinstance(raw, Mapping):
        if raw.get("ok") is False:
            return _RemoteResult(
                context,
                False,
                _safe_json(raw.get("payload")) if isinstance(raw.get("payload"), Mapping) else None,
                str(raw.get("error_class") or "project_error"),
                _safe_error_text(raw.get("error")),
                _safe_int_or_none(raw.get("http_status")),
            )
        payload = raw.get("payload") if isinstance(raw.get("payload"), Mapping) else raw
        if not isinstance(payload, Mapping):
            return _RemoteResult(context, False, error_class="malformed_response", error="response is not an object")
        return _RemoteResult(context, True, _safe_json(dict(payload)))
    return _RemoteResult(context, False, error_class="malformed_response", error="response is not an object")


def _with_query(path: str, params: Mapping[str, Any] | None) -> str:
    if not params:
        return path
    pairs: list[tuple[str, str]] = []
    for key, value in params.items():
        if value is None or value == "":
            continue
        if isinstance(value, (list, tuple)):
            pairs.extend((key, str(item)) for item in value if item is not None)
        else:
            pairs.append((key, str(value)))
    encoded = urlencode(pairs)
    return f"{path}?{encoded}" if encoded else path


def _data_mapping(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    data = payload.get("data")
    return dict(data) if isinstance(data, Mapping) else dict(payload)


def _identity_mismatches(context: ProjectContext, payload: Mapping[str, Any]) -> list[str]:
    candidates: list[Mapping[str, Any]] = [payload]
    for key in ("identity", "project", "runtime", "data"):
        nested = payload.get(key)
        if isinstance(nested, Mapping):
            candidates.append(nested)
    key_value = _first_value(candidates, "project_key", "key")
    name_value = _first_value(candidates, "project_name", "name")
    root_value = _first_value(candidates, "project_root", "target_repo_root", "root")
    mismatches: list[str] = []
    if key_value not in (None, "") and str(key_value) != context.key:
        mismatches.append(f"runtime project key {key_value!r} != registry key {context.key!r}")
    if name_value not in (None, "") and str(name_value).strip() != context.name:
        mismatches.append(f"runtime project name {name_value!r} != registry name {context.name!r}")
    if root_value not in (None, ""):
        try:
            runtime_root = Path(str(root_value)).expanduser().resolve(strict=False)
            registry_root = context.project_root.expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            mismatches.append("runtime project root is not a valid path")
        else:
            if runtime_root != registry_root:
                mismatches.append("runtime project root does not match registry root")
    return mismatches


def _first_value(candidates: Sequence[Mapping[str, Any]], *keys: str) -> Any:
    for candidate in candidates:
        for key in keys:
            value = candidate.get(key)
            if value not in (None, ""):
                return value
    return None


def _safe_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _safe_json(item)
            for key, item in value.items()
            if not _secret_key(str(key))
        }
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_json(item) for item in value]
    return value


def _secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized.endswith("_fingerprint") or normalized in {"fingerprint", "fencing_fingerprint"}:
        return False
    return any(marker in normalized for marker in _SECRET_MARKERS)


def _safe_error_text(value: Any) -> str | None:
    if value is None:
        return None
    text = _redact_text(str(value)).replace("\n", " ").strip()
    return text[:240] or "project request failed"


def _redact_text(value: str) -> str:
    pattern = r"(?i)(?:token|password|secret|credential|authorization|fencing)(?:[_-][a-z0-9]+)?\s*[:=]\s*[^,;\s]+"
    return re.sub(pattern, lambda match: match.group(0).split("=", 1)[0].split(":", 1)[0] + "=<redacted>", value)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bounded_limit(value: int, maximum: int) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("limit must be an integer") from exc
    if integer < 1:
        raise ValueError("limit must be positive")
    return min(integer, maximum)


def _bounded_offset(value: Any) -> int:
    try:
        integer = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("offset must be an integer") from exc
    if integer < 0:
        raise ValueError("offset must not be negative")
    return integer


def _compact(values: Mapping[str, Any]) -> dict[str, str]:
    return {key: str(value) for key, value in values.items() if value not in (None, "")}


def _encode_cursor(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeError) as exc:
        raise ValueError("cursor is invalid") from exc
    if not isinstance(decoded, dict):
        raise ValueError("cursor is invalid")
    return decoded


def _event_row(context: ProjectContext, event: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(_safe_json(event))
    row["project_key"] = context.key
    row["project_name"] = context.name
    row["payload"] = _safe_json(event.get("payload", event.get("payload_json", {})))
    row["payload_json"] = row["payload"]
    row["source"] = "EVENT"
    row["entity_url"] = _entity_url(
        context.key,
        str(event.get("entity_type") or "event"),
        event.get("entity_id") or event.get("id"),
    )
    row["detail_url"] = row["entity_url"]
    return row


def _log_row(context: ProjectContext, line: Any, default_source: Any) -> dict[str, Any]:
    raw = _redact_text(line) if isinstance(line, str) else json.dumps(_safe_json(line), sort_keys=True, default=str)
    data: Mapping[str, Any] = {}
    if isinstance(line, Mapping):
        data = line
    elif isinstance(line, str) and line.lstrip().startswith("{"):
        try:
            decoded = json.loads(line)
            if isinstance(decoded, Mapping):
                data = decoded
                raw = json.dumps(_safe_json(decoded), sort_keys=True, default=str)
        except json.JSONDecodeError:
            data = {}
    timestamp = data.get("timestamp", data.get("ts", data.get("time")))
    source = data.get("source", data.get("component", default_source or "api"))
    message = data.get("message", data.get("msg", data.get("text", raw)))
    return {
        "project_key": context.key,
        "project_name": context.name,
        "source": str(source or "api"),
        "timestamp": timestamp,
        "level": data.get("level", data.get("severity")),
        "packet_id": data.get("packet_id", data.get("packet")),
        "run_id": data.get("run_id", data.get("run")),
        "stage_id": data.get("stage_id", data.get("stage")),
        "worker_id": data.get("worker_id", data.get("worker")),
        "trace_id": data.get("trace_id"),
        "message": str(message or ""),
        "raw": raw,
    }


def _log_matches(
    row: Mapping[str, Any],
    source: str | None,
    worker: str | None,
    packet: str | None,
    run: str | None,
    stage: str | None,
    level: str | None,
    trace_id: str | None,
    contains: str | None,
    expression: re.Pattern[str] | None,
    since: str | None,
    until: str | None,
) -> bool:
    for expected, key in (
        (source, "source"),
        (worker, "worker_id"),
        (packet, "packet_id"),
        (run, "run_id"),
        (stage, "stage_id"),
        (level, "level"),
        (trace_id, "trace_id"),
    ):
        if expected and str(row.get(key) or "").casefold() != str(expected).casefold():
            return False
    text = f"{row.get('message') or ''} {row.get('raw') or ''}"
    if contains and contains.lower() not in text.lower():
        return False
    if expression and not expression.search(text):
        return False
    timestamp = row.get("timestamp")
    if since and _timestamp_before(timestamp, since):
        return False
    if until and _timestamp_after(timestamp, until):
        return False
    return True


def _timestamp_value(value: Any) -> float:
    if not value:
        return float("-inf")
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return float("-inf")


def _timestamp_before(value: Any, bound: str) -> bool:
    return _timestamp_value(value) < _timestamp_value(bound)


def _timestamp_after(value: Any, bound: str) -> bool:
    value_number = _timestamp_value(value)
    bound_number = _timestamp_value(bound)
    return value_number > bound_number


def _event_sort_key(row: Mapping[str, Any]) -> tuple[float, str, str]:
    return (
        _timestamp_value(row.get("timestamp")),
        str(row.get("project_key") or ""),
        str(row.get("id") or row.get("entity_id") or ""),
    )


def _log_sort_key(row: Mapping[str, Any]) -> tuple[float, str, str]:
    return (
        _timestamp_value(row.get("timestamp")),
        str(row.get("project_key") or ""),
        str(row.get("raw") or ""),
    )


def _search_row(context: ProjectContext, item: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(_safe_json(item))
    kind = str(row.get("kind", row.get("type", "unknown")))
    identifier = row.get("id") or row.get(f"{kind}_id") or row.get("entity_id") or ""
    row.update({
        "kind": kind,
        "id": identifier,
        "project_key": context.key,
        "project_name": context.name,
        "target_url": _entity_url(context.key, kind, identifier),
        "detail_url": _entity_url(context.key, kind, identifier),
    })
    return row


def _project_search_row(context: ProjectContext) -> dict[str, Any]:
    return {
        "kind": "project",
        "id": context.key,
        "title": context.name,
        "project_key": context.key,
        "project_name": context.name,
        "target_url": _project_url(context.key),
        "detail_url": _project_url(context.key),
    }


def _matches_project(query: str, context: ProjectContext) -> bool:
    if not query:
        return False
    needle = query.casefold()
    return needle in context.key.casefold() or needle in context.name.casefold() or any(
        needle in tag.casefold() for tag in context.tags
    )


def _entity_url(project_key: str, kind: str, identifier: Any) -> str:
    value = str(identifier or "")
    if kind in {"packet", "run", "stage", "feature", "wave", "worker"} and value:
        return f"/admin/p/{project_key}/{kind}/{quote(value, safe='-_.~')}"
    if kind in {"event", "trace"} and value:
        return f"/admin/p/{project_key}/events?entity_id={quote(value, safe='')}"
    return _project_url(project_key)


def _project_url(project_key: str) -> str:
    return f"/admin/p/{project_key}"


def _health_status(result: _RemoteResult, runtime: Mapping[str, Any] | None) -> str:
    if not result.context.enabled:
        return "disabled"
    if not result.ok:
        return "degraded" if result.error_class == "identity_mismatch" else "offline"
    status = str((runtime or {}).get("status", "online")).lower()
    if status in {"offline", "degraded", "unhealthy", "error", "failed", "critical"}:
        return "degraded"
    return "online"


def _value(mapping: Mapping[str, Any] | None, key: str) -> Any:
    return mapping.get(key) if isinstance(mapping, Mapping) else None


def _sizes(runtime: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(runtime, Mapping):
        return None
    keys = ("state_size", "worktree_size", "evidence_size", "state_bytes", "worktree_bytes", "evidence_bytes")
    values = {key: runtime[key] for key in keys if key in runtime}
    return values or None


def _attention_for_project(
    context: ProjectContext,
    status: str,
    runtime: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any] | None,
    latest_event: Mapping[str, Any] | None,
    errors: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if status in {"offline", "degraded"}:
        error = errors[0] if errors else {}
        kind = "identity_mismatch" if error.get("error_class") == "identity_mismatch" else "offline"
        items.append(_attention_item(
            context,
            "critical" if kind == "identity_mismatch" else "error",
            kind,
            "project",
            context.key,
            "Project is unavailable" if kind == "offline" else "Project identity mismatch",
            str(error.get("message") or "project health is not online"),
            error.get("timestamp"),
        ))
    if isinstance(runtime, Mapping) and runtime.get("db_ok") is False:
        items.append(_attention_item(context, "critical", "system_unhealthy", "system", context.key,
                                     "Database is unhealthy", "project health reports db_ok=false", None))
    if isinstance(snapshot, Mapping):
        packets = snapshot.get("packets_by_state")
        if isinstance(packets, Mapping):
            for state, count in packets.items():
                if _safe_int(count, 0) > 0 and _blocked_or_failed(str(state)):
                    items.append(_attention_item(
                        context,
                        "error" if "failed" in str(state).lower() else "warning",
                        "packet_state",
                        "packet",
                        None,
                        f"Packets require attention: {state}",
                        f"{count} packet(s) are in {state}",
                        None,
                    ))
        if _safety_disabled(snapshot):
            items.append(_attention_item(
                context, "warning", "parallel_safety_disabled", "system", context.key,
                "Parallel safety is disabled", "multi-worker execution lacks the scope guard", None,
            ))
        merge = snapshot.get("active_merge_lease_holder")
        if isinstance(merge, Mapping) and _merge_lease_attention(merge):
            items.append(_attention_item(
                context, "warning", "merge_lease_attention", "merge_lease",
                merge.get("packet_id"), "Merge lease needs attention",
                "merge lease is expired or marked stuck", merge.get("expires_at"),
            ))
    return items


def _attention_for_snapshot(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    context = ProjectContext(
        key=str(snapshot.get("project_key") or "unknown"),
        name=str(snapshot.get("project_name") or snapshot.get("project_key") or "unknown"),
        enabled=True,
        unix_user=None,
        project_root="/",
        api_url="http://diagnostics.local",
        api_socket=None,
        description="",
        tags=(),
    )
    runtime = snapshot.get("system_health")
    runtime = runtime if isinstance(runtime, Mapping) else None
    status = str((runtime or {}).get("status", "online")).casefold()
    if status in {"offline", "degraded", "unhealthy", "error", "failed", "critical"}:
        normalized_status = "degraded"
    else:
        normalized_status = "online"
    return _attention_for_project(context, normalized_status, runtime, snapshot, None, ())


def _attention_item(
    context: ProjectContext,
    severity: str,
    kind: str,
    entity_type: str | None,
    entity_id: Any,
    title: str,
    reason: str,
    timestamp: Any,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "project_key": context.key,
        "project_name": context.name,
        "kind": kind,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "title": title,
        "reason": reason,
        "timestamp": timestamp,
        "detail_url": _entity_url(context.key, entity_type or "project", entity_id or context.key),
    }


def _blocked_or_failed(state: str) -> bool:
    normalized = state.casefold()
    return "failed" in normalized or "blocked" in normalized or normalized in {"error", "stuck"}


def _safety_disabled(snapshot: Mapping[str, Any]) -> bool:
    max_concurrency = _safe_int(snapshot.get("effective_max_concurrency"), 1)
    guard = snapshot.get("parallel_scope_guard")
    return max_concurrency > 1 and guard is False


def _merge_lease_attention(lease: Mapping[str, Any]) -> bool:
    if lease.get("stuck") is True or str(lease.get("status", "")).casefold() in {"stuck", "expired"}:
        return True
    expires = lease.get("expires_at")
    return bool(expires and _timestamp_value(expires) < datetime.now(UTC).timestamp())


def _sort_attention(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rank = {"critical": 0, "error": 1, "warning": 2, "info": 3}
    return sorted(
        (dict(item) for item in items),
        key=lambda item: (
            rank.get(str(item.get("severity")), 9),
            -_timestamp_value(item.get("timestamp")),
            str(item.get("project_key", "")),
            str(item.get("kind", "")),
        ),
    )


def _coverage(rows: Sequence[Mapping[str, Any]], total: int) -> dict[str, Any]:
    responded = sum(1 for row in rows if row.get("responded"))
    partial = sum(1 for row in rows if row.get("partial"))
    disabled = sum(1 for row in rows if row.get("disabled"))
    failed = max(total - responded - disabled, 0)
    return {
        "projects_total": total,
        "projects_responded": responded,
        "projects_failed": failed,
        "projects_disabled": disabled,
        "projects_partial": partial,
        "partial": partial > 0 or failed > 0,
    }


def _coverage_from_results(results: Sequence[_RemoteResult], total: int) -> dict[str, int]:
    failed = sum(1 for result in results if not result.ok)
    return {
        "projects_total": total,
        "projects_responded": total - failed,
        "projects_failed": failed,
    }


def _aggregate_snapshots(snapshots: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    packet_counts: dict[str, int] = {}
    feature_counts: dict[str, int] = {}
    workers_total = 0
    workers_idle = 0
    workers_busy = 0
    runs_total = 0
    ordinary_leases = 0
    parallel_leases = 0
    merge_leases = 0
    max_concurrency = 0
    for snapshot in snapshots:
        for state, count in (snapshot.get("packets_by_state") or {}).items():
            packet_counts[str(state)] = packet_counts.get(str(state), 0) + _safe_int(count, 0)
        for state, count in (snapshot.get("features_by_status") or {}).items():
            feature_counts[str(state)] = feature_counts.get(str(state), 0) + _safe_int(count, 0)
        workers = snapshot.get("workers") or {}
        workers_total += _safe_int(workers.get("total"), 0) if isinstance(workers, Mapping) else 0
        workers_idle += _safe_int(workers.get("idle"), 0) if isinstance(workers, Mapping) else 0
        workers_busy += _safe_int(workers.get("busy"), 0) if isinstance(workers, Mapping) else 0
        runs_total += _safe_int(snapshot.get("runs_total"), 0)
        ordinary = snapshot.get("ordinary_leases")
        parallel = snapshot.get("active_parallel_leases")
        merge = snapshot.get("active_merge_leases")
        ordinary_leases += len(ordinary) if isinstance(ordinary, list) else _safe_int(snapshot.get("active_leases"), 0)
        parallel_leases += len(parallel) if isinstance(parallel, list) else _safe_int(snapshot.get("active_parallel_lease_count"), 0)
        merge_leases += len(merge) if isinstance(merge, list) else (1 if snapshot.get("active_merge_lease_holder") else 0)
        max_concurrency += _safe_int(snapshot.get("effective_max_concurrency"), 0)
    return {
        "packets_by_state": packet_counts,
        "features_by_status": feature_counts,
        "workers": {"total": workers_total, "idle": workers_idle, "busy": workers_busy},
        "runs_total": runs_total,
        "active_ordinary_leases": ordinary_leases,
        "active_parallel_leases": parallel_leases,
        "active_merge_leases": merge_leases,
        "effective_max_concurrency_sum": max_concurrency,
        "projects_in_aggregate": len(snapshots),
    }


def _error_dto(result: _RemoteResult, endpoint: str) -> dict[str, Any]:
    return {
        "project_key": result.context.key,
        "project_name": result.context.name,
        "endpoint": endpoint,
        "error_class": result.error_class or "project_error",
        "message": result.error or "project request failed",
        "http_status": result.http_status,
        "timestamp": _now_iso(),
    }


def _malformed_error(context: ProjectContext, endpoint: str, message: str) -> dict[str, Any]:
    return {
        "project_key": context.key,
        "project_name": context.name,
        "endpoint": endpoint,
        "error_class": "malformed_response",
        "message": message,
        "http_status": None,
        "timestamp": _now_iso(),
    }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# END_BLOCK_HELPERS
