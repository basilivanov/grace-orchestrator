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
def validate_dag(
    packets: list[dict],
    *,
    strict_wave_order: bool | None = None,
) -> ValidationResult:
    """Validate packet DAG, dependency references, and optional wave order."""
    errors: list[str] = []
    if strict_wave_order is None:
        strict_wave_order = any(
            isinstance(packet, dict) and "conflict_keys" in packet
            for packet in packets
        )

    graph: dict[str, list[str]] = {}
    scope_map: dict[str, list[str]] = {}
    wave_map: dict[str, int] = {}
    aliases: dict[str, str] = {}
    raw_dependencies: dict[str, object] = {}
    seen_ids: set[str] = set()
    for p in packets:
        pid = p.get("id") or p.get("packet_id") or p.get("title", "")
        if not pid:
            errors.append("Packet is missing an id or title")
            continue
        if pid in seen_ids:
            errors.append(f"Duplicate packet title/id: {pid}")
            continue
        if pid in aliases and aliases[pid] != pid:
            errors.append(f"Duplicate packet title/id: {pid}")
            continue
        title = p.get("title")
        if title and title in aliases and aliases[title] != pid:
            errors.append(f"Duplicate packet title/id: {title}")
            continue
        seen_ids.add(pid)
        aliases[pid] = pid
        if title:
            aliases[title] = pid
        raw_dependencies[pid] = p.get("depends_on", [])
        scope = p.get("scope", p.get("spec_json", {}).get("scope", []))
        if isinstance(scope, str):
            scope = [scope]
        scope_map[pid] = scope
        wave_index = p.get("wave_index")
        if isinstance(wave_index, int):
            wave_map[pid] = wave_index

    for pid, raw_deps in raw_dependencies.items():
        deps = raw_deps
        if isinstance(deps, str):
            deps = [d.strip() for d in deps.split(",") if d.strip()]
        elif not isinstance(deps, list):
            errors.append(f"Invalid depends_on for {pid}: expected list of packet titles")
            deps = []
        else:
            invalid_dependencies = [d for d in deps if not isinstance(d, str)]
            if invalid_dependencies:
                errors.append(
                    f"Invalid depends_on for {pid}: all references must be strings"
                )
            deps = [d.strip() for d in deps if isinstance(d, str)]
        graph[pid] = [aliases.get(dependency, dependency) for dependency in deps]

    for packet_id, dependencies in graph.items():
        for dependency in dependencies:
            if not isinstance(dependency, str) or dependency not in graph:
                errors.append(
                    f"Missing dependency: packet {packet_id} references {dependency!r}"
                )

    if strict_wave_order:
        for packet_id, dependencies in graph.items():
            packet_wave = wave_map.get(packet_id)
            if packet_wave is None:
                continue
            for dependency in dependencies:
                dependency_wave = wave_map.get(dependency)
                if dependency_wave is not None and dependency_wave >= packet_wave:
                    errors.append(
                        "Dependency wave order invalid: "
                        f"{packet_id} (wave {packet_wave}) depends on "
                        f"{dependency} (wave {dependency_wave}); dependency must be earlier"
                    )

    cycles = _detect_cycles(graph)

    ordered = []
    if not cycles:
        ordered = topological_sort(graph)
    else:
        for cycle in cycles:
            errors.append(f"Cycle detected: {' → '.join(cycle)}")

    conflicts = detect_scope_conflicts(scope_map, dependency_graph=graph)

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
    color: dict[str, int] = dict.fromkeys(graph, WHITE)
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
def _depends_transitively(graph: dict[str, list[str]], packet_id: str, dependency_id: str) -> bool:
    """Return whether packet_id directly or transitively depends on dependency_id."""
    pending = list(graph.get(packet_id, []))
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == dependency_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(graph.get(current, []))
    return False


def detect_scope_conflicts(
    scope_map: dict[str, list[str]],
    dependency_graph: dict[str, list[str]] | None = None,
) -> list[Conflict]:
    """Find overlapping scopes among packets that may execute unordered.

    An overlap is safe when one packet depends directly or transitively on the
    other: the later packet intentionally revisits an artifact after the first
    packet has completed.  With no dependency graph, preserve the standalone
    helper's conservative all-pairs behavior.
    """
    conflicts: list[Conflict] = []
    pids = list(scope_map.keys())
    for i in range(len(pids)):
        for j in range(i + 1, len(pids)):
            packet_a = pids[i]
            packet_b = pids[j]
            if dependency_graph and (
                _depends_transitively(dependency_graph, packet_a, packet_b)
                or _depends_transitively(dependency_graph, packet_b, packet_a)
            ):
                continue
            files_a = set(scope_map.get(packet_a, []))
            files_b = set(scope_map.get(packet_b, []))
            overlap = files_a & files_b
            significant_overlap = {f for f in overlap if not f.endswith("__init__.py")}
            if significant_overlap:
                conflicts.append(Conflict(packet_a, packet_b, sorted(significant_overlap)))
    return conflicts

#END_BLOCK_CONFLICTS
