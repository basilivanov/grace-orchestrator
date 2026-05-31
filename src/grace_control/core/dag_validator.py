# ############################################################################
# AI_HEADER: dag_validator
# ROLE: Validate packet dependency DAG — cycles, ordering, conflicts.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate packet DAG: detect cycles, resolve execution order, detect scope conflicts.
# inputs: packets list, optional dependency graph.
# returns: ValidationResult with valid flag, ordered packets, conflicts.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns ValidationResult with valid=False on issues.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: ValidationResult
#   - class: Conflict
#   - function: validate_dag
#   - function: topological_sort
#   - function: detect_scope_conflicts
# END_MODULE_MAP

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class Conflict:
    packet_a: str
    packet_b: str
    overlapping_files: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    valid: bool
    ordered_packets: list[str] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    cycles: list[list[str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

#START_BLOCK_VALIDATOR
def validate_dag(packets: list[dict]) -> ValidationResult:
    """Validate packet DAG: no cycles, resolve order, detect scope conflicts."""
    errors: list[str] = []

    graph: dict[str, list[str]] = {}
    scope_map: dict[str, list[str]] = {}
    for p in packets:
        pid = p.get("id", p.get("packet_id", ""))
        deps = p.get("depends_on", [])
        if isinstance(deps, str):
            deps = [d.strip() for d in deps.split(",") if d.strip()]
        graph[pid] = deps
        scope = p.get("scope", p.get("spec_json", {}).get("scope", []))
        if isinstance(scope, str):
            scope = [scope]
        scope_map[pid] = scope

    cycles = _detect_cycles(graph)

    ordered = []
    if not cycles:
        ordered = topological_sort(graph)
    else:
        for cycle in cycles:
            errors.append(f"Cycle detected: {' → '.join(cycle)}")

    conflicts = detect_scope_conflicts(scope_map)

    for c in conflicts:
        errors.append(f"Scope conflict: {c.packet_a} and {c.packet_b} overlap on {c.overlapping_files}")

    return ValidationResult(
        valid=len(errors) == 0,
        ordered_packets=ordered,
        conflicts=conflicts,
        cycles=cycles,
        errors=errors,
    )


def _detect_cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in graph}
    cycles: list[list[str]] = []

    def dfs(node: str, path: list[str]):
        color[node] = GRAY
        path.append(node)
        for neighbor in graph.get(node, []):
            if neighbor not in color:
                color[neighbor] = WHITE
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                cycles.append(path[cycle_start:] + [neighbor])
            elif color[neighbor] == WHITE:
                dfs(neighbor, path)
        path.pop()
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            dfs(node, [])
    return cycles

#END_BLOCK_VALIDATOR

#START_BLOCK_SORT
def topological_sort(graph: dict[str, list[str]]) -> list[str]:
    indegree = {n: len(graph[n]) for n in graph}
    dependents: dict[str, list[str]] = defaultdict(list)
    for node, deps in graph.items():
        for d in deps:
            if d in indegree:
                dependents[d].append(node)

    queue: deque[str] = deque(n for n, c in indegree.items() if c == 0)
    result: list[str] = []

    while queue:
        node = queue.popleft()
        result.append(node)
        for dep in dependents.get(node, []):
            indegree[dep] -= 1
            if indegree[dep] == 0:
                queue.append(dep)

    if len(result) != len(graph):
        remaining = sorted(set(graph) - set(result))
        result.extend(remaining)
    return result

#END_BLOCK_SORT

#START_BLOCK_CONFLICTS
def detect_scope_conflicts(scope_map: dict[str, list[str]]) -> list[Conflict]:
    conflicts: list[Conflict] = []
    pids = list(scope_map.keys())
    for i in range(len(pids)):
        for j in range(i + 1, len(pids)):
            files_a = set(scope_map.get(pids[i], []))
            files_b = set(scope_map.get(pids[j], []))
            overlap = files_a & files_b
            if overlap:
                conflicts.append(Conflict(pids[i], pids[j], sorted(overlap)))
    return conflicts

#END_BLOCK_CONFLICTS
