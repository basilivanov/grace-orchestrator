# ############################################################################
# AI_HEADER: pipeline_helpers.wave_progression
# ROLE: Pure wave progression planning helpers for feature_pipeline.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Plan and inspect feature wave progression without mutating feature or packet state.
# inputs: Architect manifests, planner waves, generated packet dictionaries, and wave progression dictionaries.
# returns: Wave progression plans, issue lists, and wave status booleans.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Missing optional fields fall back to deterministic defaults.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: plan_wave_sequence
#   - function: build_wave_progression
#   - function: required_wave_progression_issues
#   - function: next_required_wave_id
#   - function: all_required_waves_accepted
# END_MODULE_MAP

from __future__ import annotations

from prefect_grace.tasks.wave_executor import group_packets_by_wave


# START_FUNCTION_CONTRACT
# name: wave_required
# purpose: Determine whether a raw wave record is required.
# inputs:
#   raw: Optional wave dictionary.
# returns: True when the wave is required under existing optional/required semantics.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def wave_required(raw: dict | None) -> bool:
    payload = dict(raw or {})
    required = payload.get("required")
    if required is None:
        required = not bool(payload.get("optional"))
    return bool(required)


# START_FUNCTION_CONTRACT
# name: is_execution_wave_id
# purpose: Filter out non-execution architect wave identifiers.
# inputs:
#   value: Raw wave id value.
# returns: False only for W00, otherwise True.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def is_execution_wave_id(value: object) -> bool:
    return str(value or "").strip().upper() != "W00"


# START_FUNCTION_CONTRACT
# name: normalize_wave_progression_entry
# purpose: Normalize a raw wave record into a stable wave progression entry.
# inputs:
#   raw: Optional raw wave dictionary.
#   fallback_wave_id: Wave id used when raw data omits one.
#   source: Source label for the normalized entry.
# returns: Normalized wave progression entry.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def normalize_wave_progression_entry(
    raw: dict | None,
    *,
    fallback_wave_id: str,
    source: str,
) -> dict[str, object]:
    payload = dict(raw or {})
    wave_id = str(payload.get("wave_id") or fallback_wave_id).strip().upper()
    title = str(payload.get("title") or wave_id).strip()
    objective = str(payload.get("objective") or payload.get("goal") or title or wave_id).strip()
    return {
        "wave_id": wave_id,
        "title": title,
        "objective": objective,
        "required": wave_required(payload),
        "source": source,
    }


# START_FUNCTION_CONTRACT
# name: plan_wave_sequence
# purpose: Build the ordered execution wave sequence from architect, planner, and generated packet sources.
# inputs:
#   architect_manifest: Architect manifest payload.
#   planner_waves: Planner contract wave payloads.
#   generated_packets: Generated packet payloads.
# returns: Ordered wave progression entries without runtime status fields.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Skips malformed optional wave records.
# END_FUNCTION_CONTRACT
def plan_wave_sequence(
    *,
    architect_manifest: dict,
    planner_waves: list[dict],
    generated_packets: list[dict],
) -> list[dict[str, object]]:
    architect_entries = [
        normalize_wave_progression_entry(raw, fallback_wave_id=f"W{index:02d}", source="architect_manifest")
        for index, raw in enumerate(architect_manifest.get("waves") or [], start=1)
        if isinstance(raw, dict)
        and is_execution_wave_id(raw.get("wave_id") or f"W{index:02d}")
    ]
    planner_entries = [
        normalize_wave_progression_entry(raw, fallback_wave_id=f"W{index:02d}", source="planner_contract")
        for index, raw in enumerate(planner_waves or [], start=1)
        if isinstance(raw, dict)
        and is_execution_wave_id(raw.get("wave_id") or f"W{index:02d}")
    ]
    planner_by_id = {str(item["wave_id"]): item for item in planner_entries}
    ordered_ids: list[str] = []
    ordered_entries: list[dict[str, object]] = []
    seen: set[str] = set()

    primary_entries = architect_entries or planner_entries
    for entry in primary_entries:
        wave_id = str(entry["wave_id"])
        ordered_ids.append(wave_id)
        ordered_entries.append(dict(entry))
        seen.add(wave_id)

    secondary_entries = planner_entries if architect_entries else []
    for entry in secondary_entries:
        wave_id = str(entry["wave_id"])
        if wave_id in seen:
            continue
        ordered_ids.append(wave_id)
        ordered_entries.append(dict(entry))
        seen.add(wave_id)

    for wave_id, _packets in group_packets_by_wave(generated_packets):
        if not is_execution_wave_id(wave_id):
            continue
        if wave_id in seen:
            continue
        ordered_ids.append(wave_id)
        ordered_entries.append(
            dict(
                planner_by_id.get(
                    wave_id,
                    normalize_wave_progression_entry(
                        {"wave_id": wave_id, "title": wave_id, "objective": "Generated execution wave"},
                        fallback_wave_id=wave_id,
                        source="generated_packets",
                    ),
                )
            )
        )
        seen.add(wave_id)

    return ordered_entries


# START_FUNCTION_CONTRACT
# name: wave_packets_by_wave_id
# purpose: Group generated packets by wave id.
# inputs:
#   generated_packets: Generated packet dictionaries.
# returns: Mapping from wave id to packet dictionaries.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def wave_packets_by_wave_id(generated_packets: list[dict]) -> dict[str, list[dict]]:
    return {
        wave_id: list(packets)
        for wave_id, packets in group_packets_by_wave(generated_packets)
    }


# START_FUNCTION_CONTRACT
# name: architect_wave_gate_packet_id_for_wave
# purpose: Find the architect gate packet id in a wave packet list.
# inputs:
#   wave_packets: Packet dictionaries for one wave.
# returns: Architect packet id or empty string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def architect_wave_gate_packet_id_for_wave(wave_packets: list[dict]) -> str:
    for packet in wave_packets:
        if str(packet.get("role") or "").strip().lower() == "architect":
            return str(packet.get("packet_id") or "")
    return ""


# START_FUNCTION_CONTRACT
# name: build_wave_progression
# purpose: Build pending wave progression records from architect, planner, and generated packet data.
# inputs:
#   architect_manifest: Architect manifest payload.
#   planner_waves: Planner contract wave payloads.
#   generated_packets: Generated packet payloads.
# returns: Ordered pending wave progression records with packet ids and architect gate ids.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Missing optional data produces deterministic empty/default fields.
# END_FUNCTION_CONTRACT
def build_wave_progression(
    *,
    architect_manifest: dict,
    planner_waves: list[dict],
    generated_packets: list[dict],
) -> list[dict[str, object]]:
    packets_by_wave_id = wave_packets_by_wave_id(generated_packets)
    progression: list[dict[str, object]] = []
    for position, entry in enumerate(
        plan_wave_sequence(
            architect_manifest=architect_manifest,
            planner_waves=planner_waves,
            generated_packets=generated_packets,
        ),
        start=1,
    ):
        wave_id = str(entry["wave_id"])
        wave_packets = list(packets_by_wave_id.get(wave_id) or [])
        progression.append(
            {
                **entry,
                "position": position,
                "status": "pending",
                "packet_ids": [str(packet.get("packet_id") or "") for packet in wave_packets if str(packet.get("packet_id") or "").strip()],
                "architect_gate_packet_id": architect_wave_gate_packet_id_for_wave(wave_packets),
                "reasons": [],
            }
        )
    return progression


# START_FUNCTION_CONTRACT
# name: required_wave_progression_issues
# purpose: Find required waves that are missing generated packets or architect gate packets.
# inputs:
#   wave_progression: Wave progression records.
# returns: Human-readable issue list.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def required_wave_progression_issues(wave_progression: list[dict[str, object]]) -> list[str]:
    issues: list[str] = []
    for wave in wave_progression:
        if not bool(wave.get("required", True)):
            continue
        wave_id = str(wave.get("wave_id") or "")
        if not list(wave.get("packet_ids") or []):
            issues.append(f"{wave_id}: required wave from architect plan was not materialized into execution packets")
        if not str(wave.get("architect_gate_packet_id") or "").strip():
            issues.append(f"{wave_id}: required wave is missing an architect gate packet")
    return issues


# START_FUNCTION_CONTRACT
# name: wave_id_from_issue
# purpose: Extract a wave id prefix from a wave progression issue string.
# inputs:
#   reason: Issue string.
# returns: Uppercase wave id or empty string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def wave_id_from_issue(reason: str) -> str:
    text = str(reason or "").strip()
    if ":" not in text:
        return ""
    wave_id = text.split(":", 1)[0].strip().upper()
    return wave_id if wave_id else ""


# START_FUNCTION_CONTRACT
# name: next_required_wave_id
# purpose: Return the first non-accepted required wave id.
# inputs:
#   wave_progression: Wave progression records.
# returns: Wave id string or empty string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def next_required_wave_id(wave_progression: list[dict[str, object]]) -> str:
    for wave in wave_progression:
        if not bool(wave.get("required", True)):
            continue
        if str(wave.get("status") or "") != "accepted":
            return str(wave.get("wave_id") or "")
    return ""


# START_FUNCTION_CONTRACT
# name: all_required_waves_accepted
# purpose: Determine whether all required waves are accepted.
# inputs:
#   wave_progression: Wave progression records.
# returns: True when every required wave has status accepted.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def all_required_waves_accepted(wave_progression: list[dict[str, object]]) -> bool:
    return all(
        (not bool(wave.get("required", True))) or str(wave.get("status") or "") == "accepted"
        for wave in wave_progression
    )


_wave_required = wave_required
_is_execution_wave_id = is_execution_wave_id
_normalize_wave_progression_entry = normalize_wave_progression_entry
_plan_wave_sequence = plan_wave_sequence
_wave_packets_by_wave_id = wave_packets_by_wave_id
_architect_wave_gate_packet_id_for_wave = architect_wave_gate_packet_id_for_wave
_build_wave_progression = build_wave_progression
_required_wave_progression_issues = required_wave_progression_issues
_wave_id_from_issue = wave_id_from_issue
_next_required_wave_id = next_required_wave_id
_all_required_waves_accepted = all_required_waves_accepted
