from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

ROLE_ORDER = {
    "coder": 10,
    "verifier": 20,
    "reviewer": 30,
    "architect": 40,
    "planner": 50,
}


def group_packets_by_wave(packets: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for packet in packets:
        grouped[_wave_id(packet)].append(packet)
    return [(wave_id, grouped[wave_id]) for wave_id in sorted(grouped, key=_wave_sort_key)]


def order_packets_for_wave(packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order packets within a wave based on dependencies and role priority.

    Implements a topological sort algorithm that respects packet dependencies
    while using role-based ordering as a tiebreaker. Ensures that all dependencies
    are satisfied before a packet is scheduled.

    Algorithm:
    1. Build a map of all packets by ID
    2. Iteratively select packets whose dependencies are all satisfied
    3. Sort ready packets by role priority (coder < verifier < reviewer < architect)
    4. Detect and raise error on circular dependencies

    Args:
        packets: List of packet dictionaries to order

    Returns:
        Ordered list of packets respecting dependencies and role priority

    Raises:
        ValueError: If a dependency cycle is detected or unresolved same-wave dependency exists
    """
    packets_by_id = {str(packet["packet_id"]): packet for packet in packets}
    remaining = dict(packets_by_id)
    ordered: list[dict[str, Any]] = []

    while remaining:
        ready = [
            packet
            for packet_id, packet in remaining.items()
            if all(dependency not in remaining for dependency in _dependencies(packet))
        ]
        if not ready:
            cycle = ", ".join(sorted(remaining))
            raise ValueError(f"Packet dependency cycle or unresolved same-wave dependency: {cycle}")
        ready.sort(key=_packet_sort_key)
        for packet in ready:
            packet_id = str(packet["packet_id"])
            ordered.append(packet)
            remaining.pop(packet_id)
    return ordered


def packet_map(packets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(packet["packet_id"]): packet for packet in packets}


def packet_result_key(prefix: str, packet_id: str) -> str:
    return f"{prefix}:{packet_id}"


def reviewer_target_packet_id(reviewer_packet: dict[str, Any], packets_by_id: dict[str, dict[str, Any]]) -> str:
    explicit_target = str(reviewer_packet.get("review_target_packet_id") or "").strip()
    if explicit_target:
        packet = packets_by_id.get(explicit_target)
        if packet:
            return explicit_target
        raise ValueError(f"Reviewer packet {reviewer_packet.get('packet_id')} references unknown explicit review target {explicit_target}")
    dependencies = _dependencies(reviewer_packet)
    for dependency in dependencies:
        packet = packets_by_id.get(dependency)
        if packet and _role(packet) == "coder":
            return dependency
    for dependency in dependencies:
        target = _first_upstream_coder_packet_id(dependency, packets_by_id, seen=set())
        if target:
            return target
    for dependency in dependencies:
        packet = packets_by_id.get(dependency)
        if packet and _role(packet) not in {"verifier", "reviewer", "architect"}:
            return dependency
    raise ValueError(f"Reviewer packet {reviewer_packet.get('packet_id')} does not depend on a review target")


def verifier_dependency_packet_id(verifier_packet: dict[str, Any], packets_by_id: dict[str, dict[str, Any]]) -> str | None:
    for dependency in _dependencies(verifier_packet):
        packet = packets_by_id.get(dependency)
        if packet and _role(packet) == "coder":
            return dependency
    return None


def architect_gate_packet_ids(packets: list[dict[str, Any]]) -> list[str]:
    return [
        str(packet["packet_id"])
        for packet in packets
        if _role(packet) == "architect" and _wave_id(packet) != "W00"
    ]


def packet_has_downstream_reviewer(packet_id: str, packets: list[dict[str, Any]]) -> bool:
    for packet in packets:
        if _role(packet) == "reviewer" and packet_id in _dependencies(packet):
            return True
    return False


def missing_internal_dependencies(
    packet: dict[str, Any],
    *,
    known_packet_ids: set[str],
    completed_packet_ids: set[str],
) -> list[str]:
    return [
        dependency
        for dependency in _dependencies(packet)
        if dependency in known_packet_ids and dependency not in completed_packet_ids
    ]


def append_unique_packet(queue: list[dict[str, Any]], packet: dict[str, Any]) -> None:
    packet_id = str(packet["packet_id"])
    if any(str(item.get("packet_id")) == packet_id for item in queue):
        return
    queue.append(packet)


def _packet_sort_key(packet: dict[str, Any]) -> tuple[int, str]:
    return (ROLE_ORDER.get(_role(packet), 99), str(packet.get("packet_id") or ""))


def _dependencies(packet: dict[str, Any]) -> list[str]:
    return [str(dependency) for dependency in packet.get("dependencies") or [] if str(dependency).strip()]


def _role(packet: dict[str, Any]) -> str:
    return str(packet.get("role") or "").strip().lower()


def _wave_id(packet: dict[str, Any]) -> str:
    return str(packet.get("wave_id") or "W01").strip().upper()


def _wave_sort_key(wave_id: str) -> tuple[str, int, str]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", wave_id.strip().upper())
    if not match:
        return (wave_id, 0, wave_id)
    return (match.group(1), int(match.group(2)), wave_id)


def _first_upstream_coder_packet_id(
    packet_id: str,
    packets_by_id: dict[str, dict[str, Any]],
    *,
    seen: set[str],
) -> str | None:
    if packet_id in seen:
        return None
    seen.add(packet_id)
    packet = packets_by_id.get(packet_id)
    if not packet:
        return None
    if _role(packet) == "coder":
        return packet_id
    for dependency in _dependencies(packet):
        target = _first_upstream_coder_packet_id(dependency, packets_by_id, seen=seen)
        if target:
            return target
    return None
