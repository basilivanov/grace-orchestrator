# ############################################################################
# AI_HEADER: synthetic_runner
# ROLE: Execute synthetic scenarios without starting live agents.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Run synthetic scenarios using mocked orchestrator components.
# inputs: SyntheticScenario, tmp_path for fixtures.
# returns: SyntheticScenarioResult with execution details.
# side_effects: Writes temporary fixture files, reads registry/session state.
# emitted_logs: None.
# error_behavior: Returns result with error field on execution failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: run_synthetic_scenario
#   - function: _compute_resume_decision
#   - function: _mock_launcher_command
#   - function: _mock_returncode
#   - function: _compute_merge_allowed
#   - function: _compute_packet_accepted
#   - function: _compute_blocked_reason
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path
from typing import Any

from prefect_grace.platform.rework_resume_policy import decide_rework_resume
from prefect_grace.platform.scenario_fixtures import generate_fixture_for_scenario
from prefect_grace.platform.state_store import PacketRegistryStore
from prefect_grace.platform.synthetic_edge_matrix import SyntheticScenario, SyntheticScenarioResult

#START_BLOCK_RUNNER
# START_FUNCTION_CONTRACT
# name: run_synthetic_scenario
# purpose: Execute a synthetic scenario without starting live agents.
# inputs:
#   scenario: SyntheticScenario - Scenario to execute.
#   tmp_path: Path - Temporary directory for fixture files.
# returns: SyntheticScenarioResult - Execution result with command, returncode, and computed fields.
# side_effects: Writes temporary fixture files, reads registry/session state.
# emitted_logs: None.
# error_behavior: Returns result with error field on execution failure.
# END_FUNCTION_CONTRACT
def run_synthetic_scenario(scenario: SyntheticScenario, tmp_path: Path) -> SyntheticScenarioResult:
    """
    Execute a synthetic scenario without starting live agents.

    Args:
        scenario: Scenario to execute.
        tmp_path: Temporary directory for fixture files.

    Returns:
        SyntheticScenarioResult with execution details.
    """
    # Skip pruned scenarios
    if scenario.pruned:
        return SyntheticScenarioResult(
            scenario_id=scenario.scenario_id,
            dimensions=scenario.dimensions,
            session_mode="skipped",
            resumed_from_thread_id=None,
            resume_allowed=None,
            command=["skipped"],
            returncode=-1,
            error=f"Pruned: {scenario.prune_reason}",
        )

    # Generate fixture
    fixture = generate_fixture_for_scenario(
        scenario_id=scenario.scenario_id,
        dimensions=scenario.dimensions,
        tmp_path=tmp_path,
    )

    try:
        fixture.setup()
    except Exception as e:
        return SyntheticScenarioResult(
            scenario_id=scenario.scenario_id,
            dimensions=scenario.dimensions,
            session_mode="error",
            resumed_from_thread_id=None,
            resume_allowed=None,
            command=["error"],
            returncode=-1,
            error=f"Fixture setup failed: {str(e)}",
        )

    # Mock resume decision
    try:
        resume_decision = _compute_resume_decision(fixture, scenario.dimensions)
    except Exception as e:
        return SyntheticScenarioResult(
            scenario_id=scenario.scenario_id,
            dimensions=scenario.dimensions,
            session_mode="error",
            resumed_from_thread_id=None,
            resume_allowed=None,
            command=["error"],
            returncode=-1,
            error=f"Resume decision failed: {str(e)}",
        )

    # Mock launcher command
    command = _mock_launcher_command(
        resume_decision=resume_decision,
        dimensions=scenario.dimensions,
        fixture=fixture,
    )

    # Determine session mode
    session_mode = "resume" if resume_decision.get("resumed_from_thread_id") else "exec"

    # Mock returncode based on dimensions
    returncode = _mock_returncode(scenario.dimensions)

    # Compute result fields for stronger invariant checks
    merge_allowed = _compute_merge_allowed(scenario.dimensions)
    packet_accepted = _compute_packet_accepted(scenario.dimensions, returncode)
    blocked_reason = _compute_blocked_reason(scenario.dimensions, resume_decision)

    result = SyntheticScenarioResult(
        scenario_id=scenario.scenario_id,
        dimensions=scenario.dimensions,
        session_mode=session_mode,
        resumed_from_thread_id=resume_decision.get("resumed_from_thread_id"),
        resume_allowed=resume_decision.get("resume_allowed"),
        command=command,
        returncode=returncode,
        merge_allowed=merge_allowed,
        packet_accepted=packet_accepted,
        blocked_reason=blocked_reason,
    )

    return result


#END_BLOCK_RUNNER
#START_BLOCK_REAL_POLICY_INTEGRATION
def _compute_resume_decision(fixture: Any, dimensions: dict[str, str]) -> dict[str, Any]:
    """
    Compute resume decision using real policy logic.

    Calls decide_rework_resume for coder role scenarios and uses real
    PacketRegistryStore for registry state checks.
    """
    resume_strategy = dimensions.get("resume_strategy", "none")

    # Load registry state using real PacketRegistryStore
    try:
        registry = PacketRegistryStore(fixture.state_root)
        packet_record = registry.load_packet(fixture.packet_id)

        if packet_record is None:
            # No registry record
            current_source_hash = fixture._compute_source_hash()
            last_executed_source_hash = None
            resume_allowed_from_registry = None
            latest_coder_session_id = None
        else:
            current_source_hash = packet_record.get("source_hash", fixture._compute_source_hash())
            last_executed_source_hash = packet_record.get("last_executed_source_hash")
            resume_allowed_from_registry = packet_record.get("resume_allowed")
            latest_coder_session_id = packet_record.get("latest_coder_session_id")

        # Handle registry errors for managed strategies
        if resume_strategy in {"feature_role", "packet_parent"}:
            if dimensions.get("registry_error") != "none":
                # Fail closed on registry errors
                return {
                    "resume_allowed": False,
                    "resumed_from_thread_id": None,
                    "resume_strategy": resume_strategy,
                    "resume_block_reason": "registry_error",
                }

    except Exception as e:
        # Registry load failed
        if resume_strategy in {"feature_role", "packet_parent"}:
            # Fail closed for managed strategies
            return {
                "resume_allowed": False,
                "resumed_from_thread_id": None,
                "resume_strategy": resume_strategy,
                "resume_block_reason": "registry_load_failed",
            }
        else:
            # Fail open for legacy
            current_source_hash = fixture._compute_source_hash()
            last_executed_source_hash = None
            resume_allowed_from_registry = None
            latest_coder_session_id = None

    # For coder role with rework scenarios, use real decide_rework_resume
    if resume_strategy in {"feature_role", "packet_parent"}:
        try:
            decision = decide_rework_resume(
                packet_id=fixture.packet_id,
                current_source_hash=current_source_hash,
                last_executed_source_hash=last_executed_source_hash,
                requested_rework_mode=dimensions.get("rework_mode", "bounded_fresh"),
                rework_reason=dimensions.get("rework_reason", "test"),
                packet_dir=fixture.packet_dir,
                latest_coder_session_id=latest_coder_session_id,
            )

            # Extract resume decision from policy
            resume_allowed = decision.resume_allowed
            resumed_from_thread_id = latest_coder_session_id if resume_allowed and latest_coder_session_id else None

            return {
                "resume_allowed": resume_allowed,
                "resumed_from_thread_id": resumed_from_thread_id,
                "resume_strategy": resume_strategy,
                "resume_block_reason": decision.resume_block_reason,
            }
        except Exception as e:
            # Policy call failed, fail closed for managed strategies
            return {
                "resume_allowed": False,
                "resumed_from_thread_id": None,
                "resume_strategy": resume_strategy,
                "resume_block_reason": f"policy_error: {str(e)}",
            }

    # For none strategy, check registry state directly
    if resume_strategy == "none":
        # No resume for none strategy
        return {
            "resume_allowed": False,
            "resumed_from_thread_id": None,
            "resume_strategy": resume_strategy,
            "resume_block_reason": "none_strategy",
        }

    # Fallback: should not reach here
    return {
        "resume_allowed": False,
        "resumed_from_thread_id": None,
        "resume_strategy": resume_strategy,
        "resume_block_reason": "unknown",
    }


def _mock_launcher_command(
    resume_decision: dict[str, Any],
    dimensions: dict[str, str],
    fixture: Any,
) -> list[str]:
    """
    Generate mock launcher command based on resume decision.
    """
    resumed_from_thread_id = resume_decision.get("resumed_from_thread_id")

    if resumed_from_thread_id:
        # Resume command
        return [
            "mock-codex",
            "exec",
            "resume",
            "--json",
            "-m",
            "mock-model",
            resumed_from_thread_id,
            "-",
        ]
    else:
        # Fresh exec command
        return [
            "mock-codex",
            "exec",
            "-C",
            str(fixture.packet_dir),
            "-m",
            "mock-model",
            "--json",
            "-",
        ]


def _mock_returncode(dimensions: dict[str, str]) -> int:
    """
    Mock returncode based on scenario dimensions.
    """
    # Blocked dependencies -> non-zero
    if dimensions.get("dependencies") in ["blocked", "cyclic"]:
        return 1

    # Registry blocked -> non-zero
    if dimensions.get("registry_status") == "blocked":
        return 1

    # Corrupt artifacts -> non-zero
    if dimensions.get("artifact_layout") in ["corrupt_evidence_json"]:
        return 1

    # Default: success
    return 0


def _compute_merge_allowed(dimensions: dict[str, str]) -> bool:
    """
    Compute whether merge is allowed based on scope.
    """
    scope = dimensions.get("scope", "allowed_only")
    # Frozen scope blocks merge
    if scope in ["frozen_only", "mixed_allowed_frozen"]:
        return False
    return True


def _compute_packet_accepted(dimensions: dict[str, str], returncode: int) -> bool:
    """
    Compute whether packet is accepted based on dimensions and returncode.
    """
    # Non-zero returncode means not accepted
    if returncode != 0:
        return False

    # Corrupt artifacts should not be accepted
    if dimensions.get("artifact_layout") in ["corrupt_evidence_json", "missing_summary"]:
        return False

    # Blocked status means not accepted
    if dimensions.get("registry_status") == "blocked":
        return False

    # Blocked dependencies mean not accepted
    if dimensions.get("dependencies") in ["blocked", "cyclic"]:
        return False

    return True


def _compute_blocked_reason(dimensions: dict[str, str], resume_decision: dict[str, Any]) -> str | None:
    """
    Compute blocked reason based on dimensions and resume decision.
    """
    if dimensions.get("dependencies") in ["blocked", "cyclic"]:
        return "dependency_blocked"

    if dimensions.get("registry_status") == "blocked":
        return "registry_blocked"

    if dimensions.get("artifact_layout") in ["corrupt_evidence_json"]:
        return "corrupt_artifact"

    if resume_decision.get("resume_block_reason") and resume_decision.get("resume_block_reason") != "none":
        return resume_decision.get("resume_block_reason")

    return None


#END_BLOCK_REAL_POLICY_INTEGRATION
