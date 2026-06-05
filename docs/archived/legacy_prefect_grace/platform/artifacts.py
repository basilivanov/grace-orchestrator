# ############################################################################
# AI_HEADER: artifacts
# ROLE: Generate structured artifact bodies for GRACE orchestration runs.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Generate Markdown and JSON artifact content for backlog sync, submissions, and packet status.
# inputs: Backlog sync results, packet data, registry state.
# returns: Formatted artifact strings and dicts.
# side_effects: None (pure formatting).
# emitted_logs: None.
# error_behavior: None.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: generate_backlog_sync_artifact
#   - function: generate_packet_table_markdown
#   - function: generate_dependency_graph_summary
# END_MODULE_MAP

from __future__ import annotations

from typing import Any

#START_BLOCK_ARTIFACT_GENERATORS
# START_FUNCTION_CONTRACT
# name: generate_packet_table_markdown
# purpose: Generate a Markdown table of packets with status.
# inputs:
#   packets: list of packet dicts.
# returns: Markdown string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def generate_packet_table_markdown(packets: list[dict[str, Any]]) -> str:
    if not packets:
        return "No packets found.\n"

    lines = [
        "| Packet ID | Feature ID | Wave | Status | Dependencies |",
        "|-----------|------------|------|--------|--------------|",
    ]

    for packet in packets:
        packet_id = packet.get("packet_id", "")
        feature_id = packet.get("feature_id", "")
        wave_id = packet.get("wave_id", "")
        status = packet.get("status", "")
        depends_on = packet.get("depends_on", [])
        deps_str = ", ".join(depends_on) if depends_on else "-"

        lines.append(f"| {packet_id} | {feature_id} | {wave_id} | {status} | {deps_str} |")

    return "\n".join(lines) + "\n"


# START_FUNCTION_CONTRACT
# name: generate_dependency_graph_summary
# purpose: Generate a summary of dependency graph validation.
# inputs:
#   dag_result: DAGValidationResult object.
# returns: Markdown string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def generate_dependency_graph_summary(dag_result: Any) -> str:
    lines = ["## Dependency Graph Summary\n"]

    lines.append(f"- Total packets: {dag_result.packets_total}")
    lines.append(f"- Ready packets: {len(dag_result.ready_packets)}")
    lines.append(f"- Blocked packets: {len(dag_result.cascading_blocked)}")
    lines.append(f"- Cycles detected: {len(dag_result.cycles)}")
    lines.append(f"- Missing dependencies: {len(dag_result.missing_dependencies)}")

    if dag_result.cycles:
        lines.append("\n### Cycles\n")
        for i, cycle in enumerate(dag_result.cycles, 1):
            cycle_str = " → ".join(cycle)
            lines.append(f"{i}. {cycle_str}")

    if dag_result.missing_dependencies:
        lines.append("\n### Missing Dependencies\n")
        for packet_id, missing in dag_result.missing_dependencies.items():
            missing_str = ", ".join(missing)
            lines.append(f"- {packet_id}: {missing_str}")

    if dag_result.ready_packets:
        lines.append("\n### Ready Packets\n")
        for packet_id in dag_result.ready_packets:
            lines.append(f"- {packet_id}")

    return "\n".join(lines) + "\n"


# START_FUNCTION_CONTRACT
# name: generate_backlog_sync_artifact
# purpose: Generate a comprehensive artifact for backlog sync results.
# inputs:
#   sync_result: BacklogSyncResult object.
#   packets: list of packet dicts.
#   dag_result: DAGValidationResult object.
# returns: Markdown string.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def generate_backlog_sync_artifact(
    sync_result: Any,
    packets: list[dict[str, Any]],
    dag_result: Any,
) -> str:
    lines = ["# GRACE Backlog Sync Report\n"]

    lines.append(f"**Project:** {sync_result.project_key}")
    lines.append(f"**Total Packets:** {sync_result.packets_total}")
    lines.append(f"**Registry Updates:** {sync_result.registry_updates}\n")

    lines.append("## Status Summary\n")
    lines.append(f"- Ready: {len(sync_result.ready)}")
    lines.append(f"- Accepted: {len(sync_result.accepted)}")
    lines.append(f"- Blocked: {len(sync_result.blocked)}")
    lines.append(f"- Changed after acceptance: {len(sync_result.changed_after_acceptance)}")
    lines.append(f"- Ready for retry: {len(sync_result.ready_for_retry)}")
    lines.append(f"- Cascading blocked: {len(sync_result.cascading_blocked)}\n")

    if sync_result.warnings:
        lines.append("## Warnings\n")
        for warning in sync_result.warnings:
            lines.append(f"- {warning}")
        lines.append("")

    if sync_result.errors:
        lines.append("## Errors\n")
        for error in sync_result.errors:
            lines.append(f"- {error}")
        lines.append("")

    lines.append(generate_dependency_graph_summary(dag_result))

    lines.append("## Packet Table\n")
    lines.append(generate_packet_table_markdown(packets))

    return "\n".join(lines)

#END_BLOCK_ARTIFACT_GENERATORS
