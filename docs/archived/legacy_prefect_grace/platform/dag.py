# ############################################################################
# AI_HEADER: dag
# ROLE: Deterministic dependency graph validator for GRACE packets.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build and validate packet dependency graphs, detect cycles, compute ready packets.
# inputs: List of parsed packet records with packet_id and depends_on fields.
# returns: DAGValidationResult with ordered packets, cycles, blockers, ready packets.
# side_effects: None (pure computation).
# emitted_logs: None.
# error_behavior: Returns structured validation result with errors/warnings.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: DAGValidationResult
#   - function: validate_packet_dag
#   - function: compute_ready_packets
#   - function: detect_cycles
# END_MODULE_MAP

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#START_BLOCK_MODELS
@dataclass
class DAGValidationResult:
    packets_total: int
    ordered_packets: list[str] = field(default_factory=list)
    missing_dependencies: dict[str, list[str]] = field(default_factory=dict)
    cycles: list[list[str]] = field(default_factory=list)
    cascading_blocked: list[str] = field(default_factory=list)
    ready_packets: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

#END_BLOCK_MODELS
#START_BLOCK_DAG_CORE
# START_FUNCTION_CONTRACT
# name: detect_cycles
# purpose: Detect dependency cycles using depth-first search.
# inputs:
#   graph: dict mapping packet_id to list of dependency packet_ids.
# returns: list of cycles, where each cycle is a list of packet_ids.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def detect_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    cycles: list[list[str]] = []
    visited: set[str] = set()
    rec_stack: set[str] = set()
    path: list[str] = []

    def _dfs_visit(node: str) -> None:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                _dfs_visit(neighbor)
            elif neighbor in rec_stack:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(cycle)

        path.pop()
        rec_stack.remove(node)

    for node in graph:
        if node not in visited:
            _dfs_visit(node)

    return cycles


# START_FUNCTION_CONTRACT
# name: topological_sort
# purpose: Perform topological sort on dependency graph.
# inputs:
#   graph: dict mapping packet_id to list of dependency packet_ids.
#   all_nodes: set of all packet_ids.
# returns: list of packet_ids in topological order, or empty list if cycles exist.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns empty list if cycles detected.
# END_FUNCTION_CONTRACT
def topological_sort(graph: dict[str, list[str]], all_nodes: set[str]) -> list[str]:
    in_degree = {node: 0 for node in all_nodes}

    for node in all_nodes:
        deps = graph.get(node, [])
        in_degree[node] = len([d for d in deps if d in all_nodes])

    queue = [node for node in all_nodes if in_degree[node] == 0]
    result: list[str] = []

    while queue:
        queue.sort()
        node = queue.pop(0)
        result.append(node)

        for other_node in all_nodes:
            if node in graph.get(other_node, []):
                in_degree[other_node] -= 1
                if in_degree[other_node] == 0:
                    queue.append(other_node)

    if len(result) != len(all_nodes):
        return []

    return result


# START_FUNCTION_CONTRACT
# name: compute_ready_packets
# purpose: Compute packets that have no unmet dependencies.
# inputs:
#   packets: list of packet dicts with packet_id and depends_on.
#   blocked_packets: set of packet_ids that are blocked.
# returns: list of packet_ids that are ready to run.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def compute_ready_packets(
    packets: list[dict[str, Any]],
    blocked_packets: set[str]
) -> list[str]:
    ready: list[str] = []
    packet_ids = {p["packet_id"] for p in packets}

    for packet in packets:
        packet_id = packet["packet_id"]
        if packet_id in blocked_packets:
            continue

        depends_on = packet.get("depends_on", [])
        if not depends_on:
            ready.append(packet_id)

    return sorted(ready)


# START_FUNCTION_CONTRACT
# name: validate_packet_dag
# purpose: Validate packet dependency graph and compute ordering.
# inputs:
#   packets: list of packet dicts with packet_id and depends_on fields.
# returns: DAGValidationResult with validation details.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns result with errors field populated.
# END_FUNCTION_CONTRACT
def validate_packet_dag(packets: list[dict[str, Any]]) -> DAGValidationResult:
    result = DAGValidationResult(packets_total=len(packets))

    if not packets:
        return result

    packet_ids = {p["packet_id"] for p in packets}
    graph: dict[str, list[str]] = {}
    missing_deps: dict[str, list[str]] = {}

    for packet in packets:
        packet_id = packet["packet_id"]
        depends_on = packet.get("depends_on", [])

        if not isinstance(depends_on, list):
            depends_on = [depends_on] if depends_on else []

        graph[packet_id] = depends_on

        missing = [dep for dep in depends_on if dep not in packet_ids]
        if missing:
            missing_deps[packet_id] = missing

    result.missing_dependencies = missing_deps

    cycles = detect_cycles(graph)
    result.cycles = cycles

    if cycles:
        result.errors.append(f"Dependency cycles detected: {len(cycles)} cycle(s)")
        cycle_nodes = set()
        for cycle in cycles:
            cycle_nodes.update(cycle)
        result.cascading_blocked = sorted(cycle_nodes)
    else:
        ordered = topological_sort(graph, packet_ids)
        result.ordered_packets = ordered

    blocked = set(missing_deps.keys()) | set(result.cascading_blocked)
    result.cascading_blocked = sorted(blocked)

    result.ready_packets = compute_ready_packets(packets, blocked)

    if missing_deps:
        result.warnings.append(f"{len(missing_deps)} packet(s) have missing dependencies")

    return result

#END_BLOCK_DAG_CORE
