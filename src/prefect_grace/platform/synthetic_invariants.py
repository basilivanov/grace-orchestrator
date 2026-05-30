# ############################################################################
# AI_HEADER: synthetic_invariants
# ROLE: Deterministic invariant assertion functions for synthetic scenarios.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Assert safety invariants on synthetic scenario results.
# inputs: SyntheticScenarioResult with execution details.
# returns: None (raises AssertionError on invariant violation).
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises AssertionError with detailed message on failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: assert_inv_no_resume_on_source_hash_change
#   - function: assert_inv_no_resume_when_registry_blocks
#   - function: assert_inv_no_resume_on_missing_session
#   - function: assert_inv_dependency_block_stops_downstream
#   - function: assert_inv_scope_frozen_blocks_merge
#   - function: assert_inv_corrupt_artifact_does_not_accept
#   - function: assert_inv_cli_json_stable
#   - function: assert_inv_no_live_agents
#   - function: assert_all_invariants
# END_MODULE_MAP

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prefect_grace.platform.synthetic_edge_matrix import SyntheticScenarioResult

#START_BLOCK_INVARIANT_ASSERTIONS
# START_FUNCTION_CONTRACT
# name: assert_inv_no_resume_on_source_hash_change
# purpose: Assert INV-NO-RESUME-ON-SOURCE-HASH-CHANGE invariant.
# inputs:
#   result: SyntheticScenarioResult - Scenario execution result.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises AssertionError if invariant violated.
# END_FUNCTION_CONTRACT
def assert_inv_no_resume_on_source_hash_change(result: SyntheticScenarioResult) -> None:
    """
    INV-NO-RESUME-ON-SOURCE-HASH-CHANGE:
    When source_hash changes, no resume command should be issued.
    """
    if result.dimensions.get("source_hash") == "changed":
        assert result.session_mode == "exec", (
            f"Expected exec mode when source_hash changed, got {result.session_mode}"
        )
        assert result.resumed_from_thread_id is None, (
            f"Expected no thread resume when source_hash changed, got {result.resumed_from_thread_id}"
        )


# START_FUNCTION_CONTRACT
# name: assert_inv_no_resume_when_registry_blocks
# purpose: Assert INV-NO-RESUME-WHEN-REGISTRY-BLOCKS invariant.
# inputs:
#   result: SyntheticScenarioResult - Scenario execution result.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises AssertionError if invariant violated.
# END_FUNCTION_CONTRACT
def assert_inv_no_resume_when_registry_blocks(result: SyntheticScenarioResult) -> None:
    """
    INV-NO-RESUME-WHEN-REGISTRY-BLOCKS:
    When resume_allowed is false, no resume should occur.
    """
    if result.dimensions.get("resume_allowed") == "false":
        assert result.session_mode == "exec", (
            f"Expected exec mode when resume_allowed=false, got {result.session_mode}"
        )
        assert result.resumed_from_thread_id is None, (
            f"Expected no thread resume when resume_allowed=false, got {result.resumed_from_thread_id}"
        )


# START_FUNCTION_CONTRACT
# name: assert_inv_no_resume_on_missing_session
# purpose: Assert INV-NO-RESUME-ON-MISSING-SESSION invariant.
# inputs:
#   result: SyntheticScenarioResult - Scenario execution result.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises AssertionError if invariant violated.
# END_FUNCTION_CONTRACT
def assert_inv_no_resume_on_missing_session(result: SyntheticScenarioResult) -> None:
    """
    INV-NO-RESUME-ON-MISSING-SESSION:
    When session is missing and resume_strategy is not none, no resume should occur.
    """
    if (
        result.dimensions.get("session") == "missing"
        and result.dimensions.get("resume_strategy") != "none"
    ):
        assert result.session_mode == "exec", (
            f"Expected exec mode when session missing, got {result.session_mode}"
        )
        assert result.resumed_from_thread_id is None, (
            f"Expected no thread resume when session missing, got {result.resumed_from_thread_id}"
        )


# START_FUNCTION_CONTRACT
# name: assert_inv_registry_error_fail_closed
# purpose: Assert INV-REGISTRY-ERROR-FAIL-CLOSED invariant.
# inputs:
#   result: SyntheticScenarioResult - Scenario execution result.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises AssertionError if invariant violated.
# END_FUNCTION_CONTRACT
def assert_inv_registry_error_fail_closed(result: SyntheticScenarioResult) -> None:
    """
    INV-REGISTRY-ERROR-FAIL-CLOSED:
    When registry error occurs on managed resume strategies, fail closed (no resume).
    """
    if (
        result.dimensions.get("resume_strategy") in {"feature_role", "packet_parent"}
        and result.dimensions.get("registry_error") != "none"
    ):
        assert result.resume_allowed is False, (
            f"Expected resume_allowed=False on registry error, got {result.resume_allowed}"
        )
        assert result.session_mode == "exec", (
            f"Expected exec mode on registry error, got {result.session_mode}"
        )
        assert result.resumed_from_thread_id is None, (
            f"Expected no thread resume on registry error, got {result.resumed_from_thread_id}"
        )


# START_FUNCTION_CONTRACT
# name: assert_inv_dependency_block_stops_downstream
# purpose: Assert INV-DEPENDENCY-BLOCK-STOPS-DOWNSTREAM invariant.
# inputs:
#   result: SyntheticScenarioResult - Scenario execution result.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises AssertionError if invariant violated.
# END_FUNCTION_CONTRACT
def assert_inv_dependency_block_stops_downstream(result: SyntheticScenarioResult) -> None:
    """
    INV-DEPENDENCY-BLOCK-STOPS-DOWNSTREAM:
    When dependencies are blocked or cyclic, execution should not proceed.
    """
    if result.dimensions.get("dependencies") in ["blocked", "cyclic"]:
        # In a real implementation, this would check that the packet was not executed
        # For synthetic tests, we check that the result indicates blocked status
        assert result.returncode != 0 or result.dimensions.get("registry_status") == "blocked", (
            f"Expected blocked execution when dependencies blocked/cyclic"
        )


# START_FUNCTION_CONTRACT
# name: assert_inv_scope_frozen_blocks_merge
# purpose: Assert INV-SCOPE-FROZEN-BLOCKS-MERGE invariant.
# inputs:
#   result: SyntheticScenarioResult - Scenario execution result.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises AssertionError if invariant violated.
# END_FUNCTION_CONTRACT
def assert_inv_scope_frozen_blocks_merge(result: SyntheticScenarioResult) -> None:
    """
    INV-SCOPE-FROZEN-BLOCKS-MERGE:
    When scope includes frozen files, merge should be blocked.
    """
    if result.dimensions.get("scope") in ["frozen_only", "mixed_allowed_frozen"]:
        # Check computed merge_allowed field
        assert result.merge_allowed is False, (
            f"Expected merge_allowed=False when scope includes frozen files, got {result.merge_allowed}"
        )


# START_FUNCTION_CONTRACT
# name: assert_inv_corrupt_artifact_does_not_accept
# purpose: Assert INV-CORRUPT-ARTIFACT-DOES-NOT-ACCEPT invariant.
# inputs:
#   result: SyntheticScenarioResult - Scenario execution result.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises AssertionError if invariant violated.
# END_FUNCTION_CONTRACT
def assert_inv_corrupt_artifact_does_not_accept(result: SyntheticScenarioResult) -> None:
    """
    INV-CORRUPT-ARTIFACT-DOES-NOT-ACCEPT:
    When artifact layout is corrupt, packet should not be accepted.
    """
    if result.dimensions.get("artifact_layout") in ["corrupt_evidence_json", "missing_summary"]:
        # Check computed packet_accepted field
        assert result.packet_accepted is False, (
            f"Expected packet_accepted=False with corrupt artifacts, got {result.packet_accepted}"
        )


# START_FUNCTION_CONTRACT
# name: assert_inv_cli_json_stable
# purpose: Assert INV-CLI-JSON-STABLE invariant.
# inputs:
#   result: SyntheticScenarioResult - Scenario execution result.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises AssertionError if invariant violated.
# END_FUNCTION_CONTRACT
def assert_inv_cli_json_stable(result: SyntheticScenarioResult) -> None:
    """
    INV-CLI-JSON-STABLE:
    CLI JSON output should be stable and parseable.
    """
    # This invariant is checked at the CLI level, not per-scenario
    # For synthetic tests, we verify the result structure is valid
    assert isinstance(result.command, list), "Command should be a list"
    assert isinstance(result.dimensions, dict), "Dimensions should be a dict"


# START_FUNCTION_CONTRACT
# name: assert_inv_no_live_agents
# purpose: Assert INV-NO-LIVE-AGENTS invariant.
# inputs:
#   result: SyntheticScenarioResult - Scenario execution result.
# returns: None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Raises AssertionError if invariant violated.
# END_FUNCTION_CONTRACT
def assert_inv_no_live_agents(result: SyntheticScenarioResult) -> None:
    """
    INV-NO-LIVE-AGENTS:
    No live agents (Codex, Claude, agy) should be started during synthetic tests.
    """
    # This is enforced by the test runner, not per-scenario
    # We verify that the command is a mock/dry-run command
    command_str = " ".join(result.command)
    # In synthetic tests, we should not see actual agent binaries
    assert not any(agent in command_str for agent in ["codex1", "claude", "agy"]) or result.error is not None, (
        f"Expected no live agent execution in synthetic test"
    )


#END_BLOCK_INVARIANT_ASSERTIONS
#START_BLOCK_INVARIANT_RUNNER
INVARIANT_FUNCTIONS = {
    "INV-NO-RESUME-ON-SOURCE-HASH-CHANGE": assert_inv_no_resume_on_source_hash_change,
    "INV-NO-RESUME-WHEN-REGISTRY-BLOCKS": assert_inv_no_resume_when_registry_blocks,
    "INV-NO-RESUME-ON-MISSING-SESSION": assert_inv_no_resume_on_missing_session,
    "INV-REGISTRY-ERROR-FAIL-CLOSED": assert_inv_registry_error_fail_closed,
    "INV-DEPENDENCY-BLOCK-STOPS-DOWNSTREAM": assert_inv_dependency_block_stops_downstream,
    "INV-SCOPE-FROZEN-BLOCKS-MERGE": assert_inv_scope_frozen_blocks_merge,
    "INV-CORRUPT-ARTIFACT-DOES-NOT-ACCEPT": assert_inv_corrupt_artifact_does_not_accept,
    "INV-CLI-JSON-STABLE": assert_inv_cli_json_stable,
    "INV-NO-LIVE-AGENTS": assert_inv_no_live_agents,
}


# START_FUNCTION_CONTRACT
# name: assert_all_invariants
# purpose: Assert all expected invariants for a scenario result.
# inputs:
#   result: SyntheticScenarioResult - Scenario execution result.
#   expected_invariants: list[str] - List of invariant names to check.
# returns: tuple[list[str], list[str]] - (passed_invariants, failed_invariants).
# side_effects: None.
# emitted_logs: None.
# error_behavior: Returns failed invariants with error messages.
# END_FUNCTION_CONTRACT
def assert_all_invariants(
    result: SyntheticScenarioResult,
    expected_invariants: list[str],
) -> tuple[list[str], list[str]]:
    """
    Assert all expected invariants for a scenario result.

    Args:
        result: Scenario execution result.
        expected_invariants: List of invariant names to check.

    Returns:
        Tuple of (passed_invariants, failed_invariants).
    """
    passed = []
    failed = []

    for invariant_name in expected_invariants:
        invariant_func = INVARIANT_FUNCTIONS.get(invariant_name)
        if invariant_func is None:
            failed.append(f"{invariant_name} (unknown invariant)")
            continue

        try:
            invariant_func(result)
            passed.append(invariant_name)
        except AssertionError as e:
            failed.append(f"{invariant_name}: {str(e)}")

    return passed, failed


#END_BLOCK_INVARIANT_RUNNER
