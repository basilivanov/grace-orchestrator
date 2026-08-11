# ############################################################################
# AI_HEADER: plan_validation_dependencies — packet DAG validation adapter
# ROLE: Map the canonical DAG validator's issue strings to compiler diagnostics.
#       The existing DAG owner remains authoritative for dependency semantics.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Validate packet references, cycles, wave ordering, and scope conflicts.
# inputs: CompileResult and architect plan packet dictionaries.
# returns: None; appends mapped diagnostics to CompileResult.
# side_effects: None.
# emitted_logs: None.
# error_behavior: DAG issues become stable compiler error codes.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: validate_dependencies
# END_MODULE_MAP

from __future__ import annotations

from grace_control.core.dag_validator import validate_dag
from grace_control.core.plan_validation.models import CompileResult, _add_error
from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("plan_validation.dependencies")


# START_BLOCK_VALIDATOR
# START_FUNCTION_CONTRACT
# name: validate_dependencies
# purpose: Map canonical DAG validation results to PlanCompiler diagnostics.
# inputs: result — CompileResult; plan — architect packet plan.
# returns: None; diagnostics are appended in canonical DAG order.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Missing, cyclic, misordered, duplicate, or conflicting packets are rejected.
# END_FUNCTION_CONTRACT
def validate_dependencies(result: CompileResult, plan: dict) -> None:
    """Validate packet-title references, cycles, and new-plan wave order."""
    packets: list[dict] = []
    has_explicit_conflict_keys = False
    for wave_index, wave in enumerate(plan.get("waves", [])):
        if not isinstance(wave, dict):
            continue
        for packet_index, packet in enumerate(wave.get("packets", []) or []):
            if not isinstance(packet, dict):
                continue
            title = packet.get("title", f"wave-{wave_index}-pkt-{packet_index}")
            has_explicit_conflict_keys |= "conflict_keys" in packet
            packets.append({
                "id": title,
                "title": title,
                "depends_on": packet.get("depends_on", []),
                "scope": packet.get("scope", []),
                "wave_index": wave_index,
            })

    if not packets:
        return

    legacy_contract = bool(plan.get("_legacy_packet_contract"))
    validation = validate_dag(
        packets,
        strict_wave_order=has_explicit_conflict_keys and not legacy_contract,
    )
    for issue in validation.errors:
        if issue.startswith("Missing dependency"):
            code = "E_DEPENDENCY_MISSING"
            field_path = "depends_on"
        elif issue.startswith("Cycle detected"):
            code = "E_DEPENDENCY_CYCLE"
            field_path = "depends_on"
        elif issue.startswith("Dependency wave order invalid"):
            code = "E_DEPENDENCY_WAVE_ORDER"
            field_path = "depends_on"
        elif issue.startswith("Duplicate packet"):
            code = "E_PACKET_TITLE_DUPLICATE"
            field_path = "title"
        elif issue.startswith("Scope conflict"):
            code = "E_SCOPE_CONFLICT"
            field_path = "scope"
        else:
            code = "E_DEPENDENCY_INVALID"
            field_path = "depends_on"
        _add_error(result, code, field_path, issue)
# END_BLOCK_VALIDATOR
