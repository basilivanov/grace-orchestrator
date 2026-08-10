# ############################################################################
# AI_HEADER: admin_control_center_helpers — Stage 04 UI read-model helpers
# ROLE: Normalizes project-scoped Admin API payloads into compact, safe
#       dashboard/entity/timeline/pipeline values for the Control Center.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide pure JSON-safe normalization and masking helpers for the
#          project-aware Admin Control Center.
# inputs: Mappings/lists returned by project-local Admin APIs.
# returns: Normalized view-model fragments.
# side_effects: None; helpers do not perform I/O or mutate global state.
# emitted_logs: None.
# error_behavior: Malformed legacy values degrade to explicit empty/unknown
#                 values rather than raising from template rendering.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: _normalize_features
#   - function: _normalize_packet
#   - function: _normalize_blocking
#   - function: _normalize_event
#   - function: _filter_timeline
#   - function: _normalize_stages
#   - function: _sum_states
#   - function: _mask_secrets
# END_MODULE_MAP

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("admin_control_center_helpers")

_SECRET_KEYS = frozenset({
    "api_key",
    "api_password",
    "api_token",
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
})
_ATTENTION_STATES = frozenset({
    "blocked",
    "blocked_recoverable",
    "blocked_final",
    "failed",
    "rejected",
    "BLOCKED",
    "BLOCKED_FINAL",
    "FAILED",
    "REJECTED",
})

# START_BLOCK_HELPERS
# START_FUNCTION_CONTRACT
# name: _first_value
# purpose: Select the first present operational value from card/runtime mappings.
# inputs: card, runtime and candidate field names.
# returns: First non-None value or None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _first_value(card: Mapping[str, Any], runtime: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if card.get(name) is not None:
            return card.get(name)
        if runtime.get(name) is not None:
            return runtime.get(name)
    return None


# START_FUNCTION_CONTRACT
# name: _count_state
# purpose: Count a packet state from case-variant diagnostic mappings.
# inputs: packet state mapping and candidate state names.
# returns: Integer count, or None when no mapping is available.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _count_state(states: Any, *names: str) -> int | None:
    if not isinstance(states, Mapping):
        return None
    for name in names:
        if name in states:
            try:
                return int(states[name])
            except (TypeError, ValueError):
                return 0
    folded = {str(key).casefold(): value for key, value in states.items()}
    for name in names:
        if name.casefold() in folded:
            try:
                return int(folded[name.casefold()])
            except (TypeError, ValueError):
                return 0
    return 0


# START_FUNCTION_CONTRACT
# name: _sum_states
# purpose: Sum all matching packet-state variants instead of treating the first
#          present diagnostic key as authoritative.
# inputs: packet state mapping and candidate state names.
# returns: Integer sum, or None when no state mapping is available.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _sum_states(states: Any, *names: str) -> int | None:
    if not isinstance(states, Mapping):
        return None
    folded = {str(key).casefold(): value for key, value in states.items()}
    total = 0
    found = False
    for name in names:
        key = name.casefold()
        if key not in folded:
            continue
        found = True
        try:
            total += int(folded[key])
        except (TypeError, ValueError):
            continue
    return total if found else 0


# START_FUNCTION_CONTRACT
# name: _matches_dashboard_filter
# purpose: Apply deterministic server-side dashboard status semantics.
# inputs: enriched project card and filter name.
# returns: True when the card belongs in the filter.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _matches_dashboard_filter(card: Mapping[str, Any], filter_name: str) -> bool:
    status = str(card.get("status", "unknown")).casefold()
    states = card.get("packets_by_state")
    running = (_count_state(states, "running", "RUNNING", "claimed", "CLAIMED") or 0) > 0
    blocked = (_sum_states(states, "blocked", "blocked_recoverable", "blocked_final") or 0) > 0
    if filter_name == "all":
        return True
    if filter_name == "running":
        return running or status == "running"
    if filter_name == "blocked":
        return blocked
    if filter_name == "offline":
        return status in {"offline", "degraded", "disabled"}
    if filter_name == "attention":
        return bool(card.get("has_attention")) or blocked
    if filter_name == "idle":
        return status == "online" and not running and not blocked and not card.get("has_attention")
    return True


# START_FUNCTION_CONTRACT
# name: _has_card_attention
# purpose: Detect operator attention without replacing unavailable values with
#          healthy zeroes.
# inputs: Project card mapping.
# returns: Boolean attention flag.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _has_card_attention(card: Mapping[str, Any]) -> bool:
    status = str(card.get("status", "")).casefold()
    return bool(
        card.get("latest_attention")
        or card.get("error")
        or card.get("partial")
        or status in {"offline", "degraded", "disabled"}
        or any(_count_state(card.get("packets_by_state"), state) or 0 for state in _ATTENTION_STATES)
    )


# START_FUNCTION_CONTRACT
# name: _card_sort_key
# purpose: Sort attention cards before running and healthy idle cards.
# inputs: Project card mapping.
# returns: Deterministic sort tuple.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _card_sort_key(card: Mapping[str, Any]) -> tuple[int, int, str]:
    status = str(card.get("status", "")).casefold()
    attention_rank = 0 if card.get("has_attention") else 1
    running_rank = 0 if status == "running" else 1
    return attention_rank, running_rank, str(card.get("project_key", ""))


# START_FUNCTION_CONTRACT
# name: _unwrap
# purpose: Unwrap project API responses that use the canonical data envelope.
# inputs: Optional mapping payload.
# returns: Mapping payload suitable for templates.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns an empty mapping for malformed payloads.
# END_FUNCTION_CONTRACT
def _unwrap(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    if isinstance(payload.get("data"), Mapping):
        return dict(payload["data"])
    return dict(payload)


# START_FUNCTION_CONTRACT
# name: _normalize_features
# purpose: Normalize the selected project's nested Feature/Wave/Packet tree
#          and precompute compact safety summaries for templates.
# inputs: Raw feature tree list.
# returns: JSON-safe normalized feature list.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Skips malformed rows without failing the project page.
# END_FUNCTION_CONTRACT
def _normalize_features(features: Any) -> list[dict[str, Any]]:
    if not isinstance(features, list):
        return []
    normalized: list[dict[str, Any]] = []
    for raw_feature in features:
        if not isinstance(raw_feature, Mapping):
            continue
        feature = dict(raw_feature)
        waves: list[dict[str, Any]] = []
        for raw_wave in feature.get("waves", []) or []:
            if not isinstance(raw_wave, Mapping):
                continue
            wave = dict(raw_wave)
            packets: list[dict[str, Any]] = []
            for raw_packet in wave.get("packets", []) or []:
                if not isinstance(raw_packet, Mapping):
                    continue
                packet = dict(raw_packet)
                _add_packet_summaries(packet)
                packets.append(packet)
            wave["packets"] = packets
            wave["packet_counts_by_state"] = _packet_counts(packets)
            wave["total_duration_seconds"] = _sum_number(packets, "duration_seconds", "elapsed_seconds")
            wave["total_tokens"] = _sum_number(packets, "tokens", "tokens_total")
            wave["total_cost_usd"] = _sum_number(packets, "cost_usd")
            waves.append(wave)
        feature["waves"] = waves
        all_packets = [
            packet
            for wave in waves
            for packet in wave.get("packets", []) or []
        ]
        feature["packet_counts_by_state"] = _packet_counts(all_packets)
        feature["total_duration_seconds"] = _sum_number(all_packets, "duration_seconds", "elapsed_seconds")
        feature["total_tokens"] = _sum_number(all_packets, "tokens", "tokens_total")
        feature["total_cost_usd"] = _sum_number(all_packets, "cost_usd")
        normalized.append(feature)
    return normalized


# START_FUNCTION_CONTRACT
# name: _add_packet_summaries
# purpose: Extract compact execution/safety fields without dumping full spec
#          JSON into the master tree.
# inputs: Mutable packet mapping.
# returns: None; packet is enriched in place.
# side_effects: Mutates only the new view-model mapping.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _add_packet_summaries(packet: dict[str, Any]) -> None:
    spec = packet.get("spec_json") if isinstance(packet.get("spec_json"), Mapping) else {}
    for name in ("scope", "conflict_keys", "depends_on", "base_sha", "integration_base_sha", "wait_reason", "wait_type"):
        if packet.get(name) is None and spec.get(name) is not None:
            packet[name] = spec.get(name)
    packet["scope_summary"] = _summary(packet.get("scope"))
    packet["conflict_keys_summary"] = _summary(packet.get("conflict_keys"))
    packet["depends_on_summary"] = _summary(packet.get("depends_on"))
    packet["wait_reason"] = _wait_reason(packet)
    packet.setdefault("worker", packet.get("worker_id"))
    packet.setdefault("model", packet.get("model"))
    packet.setdefault("elapsed", packet.get("elapsed_seconds") or packet.get("duration_seconds"))
    packet.setdefault("integration_recheck", packet.get("stale_base_recheck"))


# START_FUNCTION_CONTRACT
# name: _packet_counts
# purpose: Count packet states for feature and wave summary rows.
# inputs: Packet mappings.
# returns: Deterministic state-to-count mapping.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _packet_counts(packets: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for packet in packets:
        state = str(packet.get("state") or "unknown").upper()
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


# START_FUNCTION_CONTRACT
# name: _sum_number
# purpose: Sum the first available numeric field across packet mappings.
# inputs: packet mappings and candidate field names.
# returns: Numeric total or None when no value is available.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Ignores malformed numeric values.
# END_FUNCTION_CONTRACT
def _sum_number(packets: Sequence[Mapping[str, Any]], *names: str) -> int | float | None:
    total: int | float = 0
    found = False
    for packet in packets:
        value = next((packet.get(name) for name in names if packet.get(name) is not None), None)
        if value is None:
            continue
        try:
            total += float(value)
            found = True
        except (TypeError, ValueError):
            continue
    if not found:
        return None
    return int(total) if float(total).is_integer() else total


# START_FUNCTION_CONTRACT
# name: _find_entity
# purpose: Find feature, wave and packet only inside one selected project tree.
# inputs: normalized features and explicit entity type/id.
# returns: feature, wave, packet tuple with None for missing values.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _find_entity(
    features: Sequence[Mapping[str, Any]],
    entity_type: str | None,
    entity_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    if not entity_type or not entity_id:
        return None, None, None
    for feature in features:
        if entity_type == "feature" and str(feature.get("id")) == str(entity_id):
            return dict(feature), None, None
        for wave in feature.get("waves", []) or []:
            if entity_type == "wave" and str(wave.get("id")) == str(entity_id):
                return dict(feature), dict(wave), None
            for packet in wave.get("packets", []) or []:
                if entity_type == "packet" and str(packet.get("id")) == str(entity_id):
                    return dict(feature), dict(wave), dict(packet)
    return None, None, None


# START_FUNCTION_CONTRACT
# name: _feature_by_id
# purpose: Resolve a feature by ID in a normalized selected-project tree.
# inputs: features and feature_id.
# returns: Feature mapping or None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _feature_by_id(features: Sequence[Mapping[str, Any]], feature_id: Any) -> dict[str, Any] | None:
    if feature_id is None:
        return None
    return next((dict(row) for row in features if str(row.get("id")) == str(feature_id)), None)


# START_FUNCTION_CONTRACT
# name: _wave_by_id
# purpose: Resolve a wave by ID in a normalized selected-project tree.
# inputs: features and wave_id.
# returns: Wave mapping or None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _wave_by_id(features: Sequence[Mapping[str, Any]], wave_id: Any) -> dict[str, Any] | None:
    if wave_id is None:
        return None
    for feature in features:
        for wave in feature.get("waves", []) or []:
            if str(wave.get("id")) == str(wave_id):
                return dict(wave)
    return None


# START_FUNCTION_CONTRACT
# name: _normalize_packet
# purpose: Merge packet detail, tree and raw values into one compact debugging
#          model with wait and integration-safety semantics.
# inputs: detail, tree/raw packet mappings, runs and selected run.
# returns: Normalized packet mapping.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for incomplete legacy DTOs.
# END_FUNCTION_CONTRACT
def _normalize_packet(
    detail: Mapping[str, Any],
    tree_packet: Mapping[str, Any] | None,
    raw_packet: Mapping[str, Any] | None,
    runs: Sequence[Mapping[str, Any]],
    selected_run: Mapping[str, Any] | None,
) -> dict[str, Any]:
    nested = detail.get("packet") if isinstance(detail.get("packet"), Mapping) else detail
    merged: dict[str, Any] = {}
    for source in (tree_packet or {}, raw_packet or {}, nested or {}, detail):
        if isinstance(source, Mapping):
            merged.update(source)
    spec = merged.get("spec_json") if isinstance(merged.get("spec_json"), Mapping) else {}
    latest = selected_run if selected_run is not None else (runs[-1] if runs else {})
    for name in ("scope", "conflict_keys", "depends_on", "base_sha", "integration_base_sha", "wait_reason", "wait_type"):
        if merged.get(name) is None and spec.get(name) is not None:
            merged[name] = spec.get(name)
    for name in ("worker_id", "worker", "model", "base_sha", "integration_base_sha"):
        if merged.get(name) is None and isinstance(latest, Mapping):
            merged[name] = latest.get(name)
    if selected_run is not None:
        for name in (
            "worker_id",
            "worker",
            "model",
            "base_sha",
            "integration_base_sha",
            "started_at",
            "finished_at",
            "duration_ms",
            "elapsed_seconds",
            "status",
        ):
            if selected_run.get(name) is not None:
                merged[name] = selected_run.get(name)
    merged.setdefault("id", merged.get("packet_id"))
    merged.setdefault("title", merged.get("slug") or merged.get("id"))
    merged.setdefault("state", "unknown")
    merged["scope_summary"] = _summary(merged.get("scope"))
    merged["conflict_keys_summary"] = _summary(merged.get("conflict_keys"))
    merged["depends_on_summary"] = _summary(merged.get("depends_on"))
    merged["wait_reason"] = _wait_reason(merged)
    merged["elapsed"] = merged.get("elapsed") or merged.get("elapsed_seconds") or merged.get("duration_seconds")
    merged["integration_recheck"] = (
        merged.get("integration_recheck")
        or merged.get("stale_base_recheck")
        or detail.get("integration_recheck")
    )
    merged["base_sha"] = merged.get("base_sha") or merged.get("base_commit")
    merged["integration_base_sha"] = merged.get("integration_base_sha") or merged.get("integration_sha")
    return merged


# START_FUNCTION_CONTRACT
# name: _normalize_blocking
# purpose: Flatten blocking decision and last failure fields for the immediate
#          packet Blocking panel.
# inputs: packet detail, typed blocking request result and normalized packet.
# returns: Blocking panel mapping.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for incomplete failure reports.
# END_FUNCTION_CONTRACT
def _normalize_blocking(
    detail: Mapping[str, Any],
    blocking_result: Mapping[str, Any],
    packet: Mapping[str, Any],
) -> dict[str, Any]:
    decision_payload = _unwrap(blocking_result.get("payload")) if blocking_result.get("ok") else {}
    failure = decision_payload.get("last_failure") if isinstance(decision_payload.get("last_failure"), Mapping) else {}
    if not failure and isinstance(detail.get("last_failure"), Mapping):
        failure = detail.get("last_failure")
    state = str(packet.get("state", "")).casefold()
    has_blocking = bool(decision_payload.get("has_blocking")) or state in _ATTENTION_STATES
    issues = (
        failure.get("blocking_issues")
        or decision_payload.get("blocking_issues")
        or detail.get("blocking_issues")
        or []
    )
    command = (
        failure.get("command_preview")
        or failure.get("command")
        or decision_payload.get("last_failed_command")
        or detail.get("last_failed_command")
    )
    return {
        "has_blocking": has_blocking,
        "decided_by": decision_payload.get("decided_by") or detail.get("decided_by"),
        "reason": decision_payload.get("reason") or failure.get("summary") or detail.get("reason"),
        "failure_class": failure.get("failure_class") or decision_payload.get("failure_class") or detail.get("failure_class"),
        "failure_stage": failure.get("failure_stage") or failure.get("stage") or detail.get("failure_stage"),
        "issues": issues if isinstance(issues, list) else [issues],
        "command": command if isinstance(command, list) else ([command] if command else []),
        "exit_code": failure.get("exit_code") or detail.get("exit_code"),
        "stderr_tail": failure.get("stderr_tail") or failure.get("stderr") or detail.get("stderr_tail") or "",
        "at": decision_payload.get("at"),
    }


# START_FUNCTION_CONTRACT
# name: _normalize_event
# purpose: Preserve canonical event identity, source timestamp, trace ID and
#          full payload for timeline drill-down.
# inputs: Raw event mapping.
# returns: Normalized event mapping.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for unknown event shapes.
# END_FUNCTION_CONTRACT
def _normalize_event(event: Any) -> dict[str, Any]:
    if not isinstance(event, Mapping):
        return {"event_type": "unknown", "payload": event}
    row = dict(event)
    row["event_type"] = row.get("event_type") or row.get("type") or "unknown"
    row["component"] = row.get("component") or _mapping_value(row.get("payload_json"), "component") or _mapping_value(row.get("payload"), "component")
    row["reason"] = row.get("reason") or _mapping_value(row.get("payload_json"), "reason") or _mapping_value(row.get("payload"), "reason")
    row["payload"] = row.get("payload_json") if row.get("payload_json") is not None else row.get("payload", {})
    row["trace_id"] = row.get("trace_id") or ""
    return row


# START_FUNCTION_CONTRACT
# name: _filter_timeline
# purpose: Apply packet-local timeline filters without dropping unknown event
#          types or changing canonical timestamp, trace and payload fields.
# inputs: normalized events and optional event/component/run-stage/trace/text
#         filter values.
# returns: Filtered normalized event list in source order.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for malformed event payloads.
# END_FUNCTION_CONTRACT
def _filter_timeline(
    events: Sequence[Mapping[str, Any]],
    *,
    event_filter: str | None = None,
    component_filter: str | None = None,
    run_stage_filter: str | None = None,
    trace_filter: str | None = None,
    text_filter: str | None = None,
) -> list[dict[str, Any]]:
    def matches(value: Any, needle: str | None) -> bool:
        return not needle or needle.casefold() in str(value or "").casefold()

    filtered: list[dict[str, Any]] = []
    for raw_event in events:
        event = dict(raw_event)
        payload = event.get("payload")
        run_stage_values = (
            event.get("run_id"),
            event.get("run"),
            event.get("stage_run_id"),
            event.get("stage_id"),
            event.get("stage_key"),
            event.get("stage"),
            _mapping_value(payload, "run_id"),
            _mapping_value(payload, "run"),
            _mapping_value(payload, "stage_run_id"),
            _mapping_value(payload, "stage_id"),
            _mapping_value(payload, "stage_key"),
            _mapping_value(payload, "stage"),
        )
        if not matches(event.get("event_type"), event_filter):
            continue
        if not matches(event.get("component"), component_filter):
            continue
        if run_stage_filter and not any(matches(value, run_stage_filter) for value in run_stage_values):
            continue
        if not matches(event.get("trace_id"), trace_filter):
            continue
        if text_filter and text_filter.casefold() not in str(event).casefold():
            continue
        filtered.append(event)
    return filtered


# START_FUNCTION_CONTRACT
# name: _normalize_run
# purpose: Normalize run metadata for run selection and context propagation.
# inputs: Raw run mapping.
# returns: JSON-safe run mapping.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _normalize_run(run: Any) -> dict[str, Any]:
    if not isinstance(run, Mapping):
        return {"id": str(run), "status": "unknown"}
    nested = run.get("run") if isinstance(run.get("run"), Mapping) else {}
    row = {**dict(run), **dict(nested)}
    row["id"] = row.get("id") or row.get("run_id")
    row.setdefault("run_number", row.get("number"))
    row.setdefault("worker", row.get("worker_id"))
    row.setdefault("elapsed", row.get("duration_ms"))
    return row


# START_FUNCTION_CONTRACT
# name: _normalize_stages
# purpose: Preserve actual runtime order and render unknown stage keys as
#          generic cards with all available observability fields.
# inputs: detail stages, raw stages and pipeline mapping.
# returns: Ordered normalized stage mappings.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for missing/legacy stage data.
# END_FUNCTION_CONTRACT
def _normalize_stages(
    detail_stages: Any,
    raw_stages: Any,
    pipeline: Any,
) -> list[dict[str, Any]]:
    candidates = detail_stages if isinstance(detail_stages, list) else raw_stages
    if not isinstance(candidates, list) and isinstance(pipeline, Mapping):
        candidates = pipeline.get("stages", [])
    if not isinstance(candidates, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in candidates:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        row.setdefault("id", row.get("stage_run_id"))
        key = str(row.get("stage_key") or row.get("key") or "unknown_stage")
        row["stage_key"] = key
        row["label"] = row.get("label") or key.replace("_", " ").title()
        row["parent_stage"] = row.get("parent_stage") or row.get("parent_stage_run_id")
        row["attempt_number"] = row.get("attempt_number") or row.get("attempt")
        row["loop_round"] = row.get("loop_round") or row.get("round") or 1
        out.append(row)
    return out


# START_FUNCTION_CONTRACT
# name: _normalize_stage
# purpose: Normalize one selected stage detail while keeping unknown keys.
# inputs: Raw stage mapping.
# returns: Normalized stage mapping.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _normalize_stage(stage: Any) -> dict[str, Any]:
    rows = _normalize_stages([stage] if isinstance(stage, Mapping) else [], [], {})
    return rows[0] if rows else {}


# START_FUNCTION_CONTRACT
# name: _summary
# purpose: Render compact list/scalar safety metadata for tree rows.
# inputs: Value from scope/conflict/dependency fields.
# returns: Human-readable bounded summary string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _summary(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, (list, tuple, set)):
        values = [str(item) for item in value]
        if not values:
            return "—"
        return ", ".join(values[:4]) + (f" +{len(values) - 4}" if len(values) > 4 else "")
    if isinstance(value, Mapping):
        return ", ".join(f"{key}={val}" for key, val in list(value.items())[:4])
    return str(value)


# START_FUNCTION_CONTRACT
# name: _wait_reason
# purpose: Extract a first-class typed wait reason from a packet/detail mapping.
# inputs: Packet-like mapping.
# returns: Wait reason string or None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _wait_reason(mapping: Mapping[str, Any]) -> str | None:
    for key in ("wait_reason", "typed_wait_reason", "current_wait_reason", "wait_type", "wait"):
        value = mapping.get(key)
        if isinstance(value, Mapping):
            value = value.get("reason") or value.get("type") or value.get("wait_reason")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# START_FUNCTION_CONTRACT
# name: _waits_from
# purpose: Read wait summaries from a project card or diagnostics mapping.
# inputs: Project card mapping.
# returns: Wait list.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _waits_from(card: Mapping[str, Any]) -> list[Any]:
    waits = card.get("waits")
    if isinstance(waits, list):
        return waits
    return []


# START_FUNCTION_CONTRACT
# name: _effective_config
# purpose: Build the visible non-secret effective runtime configuration from
#          health and diagnostics snapshots.
# inputs: health and diagnostics mappings.
# returns: Configuration mapping.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _effective_config(health: Mapping[str, Any], diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "target_branch", "base_branch", "git_remote", "workspace_mode",
        "execution_backend", "effective_max_concurrency", "parallel_scope_guard",
        "merge_serialization", "stale_base_recheck", "api_status", "supervisor_status",
    )
    return {key: (health.get(key) if health.get(key) is not None else diagnostics.get(key)) for key in keys
            if health.get(key) is not None or diagnostics.get(key) is not None}


# START_FUNCTION_CONTRACT
# name: _mask_secrets
# purpose: Recursively mask credential-shaped configuration keys before
#          rendering system/raw data in the browser.
# inputs: JSON-like value.
# returns: JSON-like value with secret values replaced.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises for ordinary JSON-like values.
# END_FUNCTION_CONTRACT
def _mask_secrets(value: Any) -> Any:
    if isinstance(value, Mapping):
        masked: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.casefold()
            secret = lowered in _SECRET_KEYS or any(
                lowered.endswith(f"_{marker}") for marker in _SECRET_KEYS
            )
            masked[key_text] = "••••••" if secret and item not in (None, "") else _mask_secrets(item)
        return masked
    if isinstance(value, list):
        return [_mask_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [_mask_secrets(item) for item in value]
    return value


# START_FUNCTION_CONTRACT
# name: _mapping_value
# purpose: Read a scalar from a mapping without assuming a canonical payload key.
# inputs: candidate value and key.
# returns: Value or None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _mapping_value(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, Mapping) else None


# START_FUNCTION_CONTRACT
# name: _capability_message
# purpose: Turn a typed project API error into an operator-facing capability
#          banner without exposing transport credentials.
# inputs: normalized project read result.
# returns: Human-readable message.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Never raises.
# END_FUNCTION_CONTRACT
def _capability_message(result: Mapping[str, Any]) -> str:
    if result.get("error_class") in {"capability_unavailable", "http_error"} or result.get("http_status") == 404:
        return "This project runtime does not expose this capability."
    return str(result.get("error") or "This project data is currently unavailable.")


# END_BLOCK_HELPERS
