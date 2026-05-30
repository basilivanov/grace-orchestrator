# ############################################################################
# AI_HEADER: synthetic_edge_matrix
# ROLE: Generate synthetic test scenarios for GRACE orchestrator safety invariants.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Generate deterministic test scenario matrix for orchestrator edge cases.
# inputs: Profile (smoke/full), seed, dimension overrides.
# returns: List of SyntheticScenario objects with dimensions and expected invariants.
# side_effects: None (pure generation).
# emitted_logs: None.
# error_behavior: Returns empty list on invalid profile.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: SyntheticScenario
#   - class: SyntheticScenarioResult
#   - function: build_synthetic_edge_matrix
#   - function: prune_impossible_scenarios
# END_MODULE_MAP

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from typing import Any

#START_BLOCK_MODELS
@dataclass
class SyntheticScenario:
    """
    Single synthetic test scenario with dimensions and expected invariants.
    """
    scenario_id: str
    dimensions: dict[str, str]
    expected_invariants: list[str]
    pruned: bool = False
    prune_reason: str | None = None


@dataclass
class SyntheticScenarioResult:
    """
    Result of executing a synthetic scenario.
    """
    scenario_id: str
    dimensions: dict[str, str]
    session_mode: str
    resumed_from_thread_id: str | None
    resume_allowed: bool | None
    command: list[str]
    returncode: int
    passed_invariants: list[str] = field(default_factory=list)
    failed_invariants: list[str] = field(default_factory=list)
    error: str | None = None
    # Computed result fields for stronger invariant checks
    merge_allowed: bool = False
    packet_accepted: bool = False
    blocked_reason: str | None = None

#END_BLOCK_MODELS
#START_BLOCK_DIMENSION_DEFINITIONS
# Dimension value definitions
DIMENSIONS = {
    "source_hash": ["same", "changed", "missing", "malformed"],
    "session": ["exists", "missing", "stale", "wrong_packet", "wrong_role", "killed_stalled"],
    "resume_strategy": ["none", "feature_role", "packet_parent"],
    "resume_allowed": ["true", "false", "missing"],
    "resume_block_reason": [
        "none",
        "contract_changed",
        "registry_blocked",
        "missing_last_executed_hash",
        "registry_error",
        "missing_session",
        "stale_session",
    ],
    "registry_error": ["none", "load_failed", "corrupt_yaml", "permission_denied"],
    "execution_state": ["no_prior_run", "last_success", "last_failed", "last_timeout"],
    "thread_state": ["fresh", "resumed", "auto_resumed", "stalled_killed"],
    "rework_mode": ["light_resume", "bounded_fresh", "fresh_session", "decision_required"],
    "rework_reason": [
        "reviewer_small_fix",
        "architect_contract_change",
        "planner_reslice",
        "evidence_blocker",
        "ambiguous",
    ],
    "registry_status": [
        "ready",
        "running",
        "accepted",
        "blocked",
        "changed_after_acceptance",
        "ready_for_retry",
        "cascading_blocked",
    ],
    "dependencies": ["accepted", "blocked", "mixed", "missing", "cyclic"],
    "artifact_layout": [
        "complete",
        "missing_summary",
        "missing_latest_review",
        "corrupt_evidence_json",
        "huge_history",
    ],
    "launcher_state": [
        "old_thread_present",
        "no_thread",
        "auto_resume_after_timeout",
        "parent_thread_from_another_packet",
    ],
    "scope": ["allowed_only", "frozen_only", "mixed_allowed_frozen", "no_changes"],
}

#END_BLOCK_DIMENSION_DEFINITIONS
#START_BLOCK_PRUNING_RULES
# START_FUNCTION_CONTRACT
# name: _is_impossible_combination
# purpose: Check if a dimension combination is physically impossible.
# inputs:
#   dimensions: dict[str, str] - Scenario dimension values.
# returns: tuple[bool, str | None] - (is_impossible, reason).
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _is_impossible_combination(dimensions: dict[str, str]) -> tuple[bool, str | None]:
    """
    Check if a dimension combination is physically impossible.

    Returns (is_impossible, reason).
    """
    # Rule: session=missing + thread_state=resumed
    if dimensions.get("session") == "missing" and dimensions.get("thread_state") in ["resumed", "auto_resumed"]:
        return (True, "session_missing_cannot_resume_thread")

    # Rule: resume_strategy=none + thread_state=resumed
    if dimensions.get("resume_strategy") == "none" and dimensions.get("thread_state") in ["resumed", "auto_resumed"]:
        return (True, "resume_strategy_none_cannot_resume")

    # Rule: resume_strategy=none + registry_error!=none
    if dimensions.get("resume_strategy") == "none" and dimensions.get("registry_error") != "none":
        return (True, "resume_strategy_none_no_registry_check")

    # Rule: registry_status=accepted + dependencies=blocked
    if dimensions.get("registry_status") == "accepted" and dimensions.get("dependencies") == "blocked":
        return (True, "accepted_cannot_have_blocked_dependencies")

    # Rule: registry_status=accepted + dependencies=cyclic
    if dimensions.get("registry_status") == "accepted" and dimensions.get("dependencies") == "cyclic":
        return (True, "accepted_cannot_have_cyclic_dependencies")

    # Rule: artifact_layout=missing_latest_review + rework_reason=reviewer_small_fix
    if (
        dimensions.get("artifact_layout") == "missing_latest_review"
        and dimensions.get("rework_reason") == "reviewer_small_fix"
    ):
        return (True, "reviewer_fix_requires_review_artifact")

    return (False, None)


# START_FUNCTION_CONTRACT
# name: prune_impossible_scenarios
# purpose: Mark impossible scenarios as pruned.
# inputs:
#   scenarios: list[SyntheticScenario] - List of scenarios to check.
# returns: list[SyntheticScenario] - Scenarios with pruned flag set.
# side_effects: Modifies scenario.pruned and scenario.prune_reason fields.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def prune_impossible_scenarios(scenarios: list[SyntheticScenario]) -> list[SyntheticScenario]:
    """
    Mark impossible scenarios as pruned.
    """
    pruned_scenarios = []
    for scenario in scenarios:
        is_impossible, reason = _is_impossible_combination(scenario.dimensions)
        if is_impossible:
            scenario.pruned = True
            scenario.prune_reason = reason
        pruned_scenarios.append(scenario)
    return pruned_scenarios

#END_BLOCK_PRUNING_RULES
#START_BLOCK_INVARIANT_MAPPING
# START_FUNCTION_CONTRACT
# name: _map_invariants_for_scenario
# purpose: Map expected invariants based on scenario dimensions.
# inputs:
#   dimensions: dict[str, str] - Scenario dimension values.
# returns: list[str] - List of invariant names to check.
# side_effects: None.
# emitted_logs: None.
# error_behavior: None.
# END_FUNCTION_CONTRACT
def _map_invariants_for_scenario(dimensions: dict[str, str]) -> list[str]:
    """
    Map expected invariants based on scenario dimensions.
    """
    invariants = []

    # INV-NO-RESUME-ON-SOURCE-HASH-CHANGE
    if dimensions.get("source_hash") == "changed":
        invariants.append("INV-NO-RESUME-ON-SOURCE-HASH-CHANGE")

    # INV-NO-RESUME-WHEN-REGISTRY-BLOCKS
    if dimensions.get("resume_allowed") == "false":
        invariants.append("INV-NO-RESUME-WHEN-REGISTRY-BLOCKS")

    # INV-NO-RESUME-ON-MISSING-SESSION
    if dimensions.get("session") == "missing" and dimensions.get("resume_strategy") != "none":
        invariants.append("INV-NO-RESUME-ON-MISSING-SESSION")

    # INV-REGISTRY-ERROR-FAIL-CLOSED
    if (
        dimensions.get("resume_strategy") in ["feature_role", "packet_parent"]
        and dimensions.get("registry_error") != "none"
    ):
        invariants.append("INV-REGISTRY-ERROR-FAIL-CLOSED")

    # INV-DEPENDENCY-BLOCK-STOPS-DOWNSTREAM
    if dimensions.get("dependencies") in ["blocked", "cyclic"]:
        invariants.append("INV-DEPENDENCY-BLOCK-STOPS-DOWNSTREAM")

    # INV-SCOPE-FROZEN-BLOCKS-MERGE
    if dimensions.get("scope") in ["frozen_only", "mixed_allowed_frozen"]:
        invariants.append("INV-SCOPE-FROZEN-BLOCKS-MERGE")

    # INV-CORRUPT-ARTIFACT-DOES-NOT-ACCEPT
    if dimensions.get("artifact_layout") in ["corrupt_evidence_json", "missing_summary"]:
        invariants.append("INV-CORRUPT-ARTIFACT-DOES-NOT-ACCEPT")

    # INV-CLI-JSON-STABLE (always check)
    invariants.append("INV-CLI-JSON-STABLE")

    # INV-NO-LIVE-AGENTS (always check)
    invariants.append("INV-NO-LIVE-AGENTS")

    return invariants

#END_BLOCK_INVARIANT_MAPPING
#START_BLOCK_MATRIX_BUILDER
# START_FUNCTION_CONTRACT
# name: build_synthetic_edge_matrix
# purpose: Build deterministic synthetic scenario matrix.
# inputs:
#   profile: str - "smoke" for fast PR checks, "full" for comprehensive coverage.
#   seed: int - Random seed for deterministic generation.
#   dimensions_override: dict[str, list[str]] | None - Optional dimension value overrides.
# returns: list[SyntheticScenario] - List of generated scenarios.
# side_effects: Uses random.seed() for deterministic generation.
# emitted_logs: None.
# error_behavior: Returns empty list on invalid profile.
# END_FUNCTION_CONTRACT
def build_synthetic_edge_matrix(
    profile: str = "smoke",
    seed: int = 1,
    dimensions_override: dict[str, list[str]] | None = None,
) -> list[SyntheticScenario]:
    """
    Build deterministic synthetic scenario matrix.

    The same seed and profile must produce the same scenario IDs, dimensions,
    pruning decisions, and ordering across runs.

    Args:
        profile: "smoke" for fast PR checks, "full" for comprehensive coverage.
        seed: Random seed for deterministic generation.
        dimensions_override: Optional dimension value overrides.

    Returns:
        List of SyntheticScenario objects.
    """
    random.seed(seed)

    # Select dimensions based on profile
    if profile == "smoke":
        # Smoke: minimal critical dimensions covering all required invariants
        selected_dimensions = {
            "source_hash": ["same", "changed"],
            "session": ["exists", "missing"],
            "resume_strategy": ["none", "packet_parent"],
            "resume_allowed": ["true", "false"],
            "resume_block_reason": ["none", "contract_changed"],
            "registry_error": ["none", "load_failed"],
            "registry_status": ["ready", "blocked"],
            "dependencies": ["accepted", "blocked"],
            "artifact_layout": ["complete", "corrupt_evidence_json"],  # Added for INV-CORRUPT-ARTIFACT
            "scope": ["allowed_only", "frozen_only"],  # Added for INV-SCOPE-FROZEN
        }
    elif profile == "full":
        # Full: comprehensive dimensions
        selected_dimensions = {
            "source_hash": ["same", "changed", "missing"],
            "session": ["exists", "missing", "stale"],
            "resume_strategy": ["none", "feature_role", "packet_parent"],
            "resume_allowed": ["true", "false", "missing"],
            "resume_block_reason": ["none", "contract_changed", "missing_session", "registry_error"],
            "registry_error": ["none", "load_failed", "corrupt_yaml"],
            "execution_state": ["no_prior_run", "last_success", "last_failed"],
            "registry_status": ["ready", "running", "accepted", "blocked"],
            "dependencies": ["accepted", "blocked", "mixed"],
            "artifact_layout": ["complete", "missing_summary", "corrupt_evidence_json"],
            "scope": ["allowed_only", "frozen_only", "mixed_allowed_frozen"],
        }
    else:
        # Unknown profile, return empty
        return []

    # Apply overrides
    if dimensions_override:
        for key, values in dimensions_override.items():
            if key in selected_dimensions:
                selected_dimensions[key] = values

    # Generate cartesian product
    dimension_keys = sorted(selected_dimensions.keys())
    dimension_values = [selected_dimensions[k] for k in dimension_keys]

    scenarios = []
    for idx, combination in enumerate(itertools.product(*dimension_values)):
        dimensions = dict(zip(dimension_keys, combination))

        scenario_id = f"scenario-{idx:04d}"
        expected_invariants = _map_invariants_for_scenario(dimensions)

        scenario = SyntheticScenario(
            scenario_id=scenario_id,
            dimensions=dimensions,
            expected_invariants=expected_invariants,
        )
        scenarios.append(scenario)

    # Prune impossible combinations
    scenarios = prune_impossible_scenarios(scenarios)

    # Shuffle for deterministic but non-sequential execution
    random.shuffle(scenarios)

    return scenarios

#END_BLOCK_MATRIX_BUILDER
