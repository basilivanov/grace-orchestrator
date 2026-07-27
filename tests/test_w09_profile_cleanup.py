# ############################################################################
# AI_HEADER: test_w09_profile_cleanup
# ROLE: W09 tests — profile cleanup and agent input validation.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Verify fail-closed agent profile loading, selection, and input safety.
# inputs: Packaged agent_profiles.yaml and isolated test fixtures.
# returns: Pytest assertions for profile and runtime safety contracts.
# side_effects: Resets the profile cache and creates temporary directories.
# emitted_logs: None.
# error_behavior: Fails assertions when profile routing or validation regresses.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: test_all_enabled_coder_profiles_receive_packet_input
#   - function: test_coder_agy_has_valid_input_mode
#   - function: test_profile_loader_rejects_unresolved_packetless_coder
#   - function: test_select_executor_skips_disabled_invalid_profiles
#   - function: test_architect_profiles_use_canonical_schema
#   - function: test_agent_run_service_rejects_unresolved_placeholders
#   - function: test_agent_run_service_rejects_cwd_escaping_worktree
#   - function: test_live_executor_profile_cannot_select_disabled_profile
# END_MODULE_MAP

"""W09 Profile Cleanup and Agent Input Validation.

Tests cover:
1. Every enabled coder profile receives packet input
2. coder_agy has a valid input mode
3. Profile loader rejects packetless coder profiles
4. select_executor skips disabled/invalid profiles
5. Architect profiles use canonical schema
"""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch

from grace_control.config.agent_profiles import AgentProfile, load_agent_profiles, reset_cache


# START_BLOCK_PROFILE_SAFETY
# ─── Test 1: All enabled coder profiles receive packet input ────────────────

# START_FUNCTION_CONTRACT
# name: test_all_enabled_coder_profiles_receive_packet_input
# purpose: Verify enabled coder profiles receive packet content explicitly.
# inputs: None.
# returns: None; asserts profile input contracts.
# side_effects: Resets the profile cache.
# emitted_logs: None.
# error_behavior: Fails when an enabled coder can run without packet input.
# END_FUNCTION_CONTRACT
def test_all_enabled_coder_profiles_receive_packet_input():
    """W09: Every enabled coder profile must have a valid packet input mode
    (file or stdin) with proper placeholder references."""
    reset_cache()
    profiles = load_agent_profiles()

    coder_profiles = [p for p in profiles.values()
                      if "coder" in p.executor_id.lower() and not p.disabled]
    assert len(coder_profiles) > 0, "No enabled coder profiles found"

    for profile in coder_profiles:
        assert profile.input_mode in ("file", "stdin"), \
            (f"Coder profile '{profile.executor_id}' has input_mode="
             f"'{profile.input_mode}', expected 'file' or 'stdin'")

        if profile.input_mode == "file":
            command_text = " ".join(profile.command)
            assert "{packet_path}" in command_text, \
                (f"File-input coder '{profile.executor_id}' must reference "
                 f"{{packet_path}} in command")

        elif profile.input_mode == "stdin":
            assert "{packet_markdown}" in (profile.input_template or ""), \
                (f"Stdin-input coder '{profile.executor_id}' must include "
                 f"{{packet_markdown}} in template")


# ─── Test 2: coder_agy has a valid input mode ──────────────────────────────

# START_FUNCTION_CONTRACT
# name: test_coder_agy_has_valid_input_mode
# purpose: Verify coder_agy receives its packet through file or stdin input.
# inputs: None.
# returns: None; asserts coder_agy profile fields.
# side_effects: Resets the profile cache.
# emitted_logs: None.
# error_behavior: Fails when coder_agy has packetless input configuration.
# END_FUNCTION_CONTRACT
def test_coder_agy_has_valid_input_mode():
    """W09: coder_agy must have a valid input mode with packet path reference.
    The profile was flagged as potentially packetless; this test verifies the
    fix — it must use 'file' or 'stdin' input mode with proper placeholders."""
    reset_cache()
    profiles = load_agent_profiles()

    agy = profiles.get("coder_agy")
    assert agy is not None, "coder_agy profile must exist in agent_profiles.yaml"
    assert not agy.disabled, "coder_agy must not be disabled — it has valid input"

    assert agy.input_mode in ("file", "stdin"), \
        f"coder_agy has input_mode='{agy.input_mode}', expected 'file' or 'stdin'"

    if agy.input_mode == "file":
        command_text = " ".join(agy.command)
        assert "{packet_path}" in command_text, \
            "coder_agy (file-input) must reference {packet_path} in command"
    elif agy.input_mode == "stdin":
        assert "{packet_markdown}" in (agy.input_template or ""), \
            "coder_agy (stdin-input) must include {packet_markdown} in template"


# ─── Test 3: Profile loader rejects unresolved packetless coder ────────────

# START_FUNCTION_CONTRACT
# name: test_profile_loader_rejects_unresolved_packetless_coder
# purpose: Verify invalid packetless coder profiles fail during validation.
# inputs: None.
# returns: None; asserts expected validation errors.
# side_effects: Instantiates in-memory profiles.
# emitted_logs: None.
# error_behavior: Fails when an invalid enabled coder profile is accepted.
# END_FUNCTION_CONTRACT
def test_profile_loader_rejects_unresolved_packetless_coder():
    """W09: The profile loader must reject coder profiles without valid packet
    input. Invalid profiles fail during loading/selection, not during execution."""

    # Case 1: coder with input_mode "none" — rejected
    with pytest.raises(ValueError, match="coder profiles must have explicit packet input"):
        AgentProfile("coder-broken", {
            "command": ["some-cli", "run"],
            "input": {"mode": "none"},
        })

    # Case 2: coder with file input but no {packet_path} in command — rejected
    with pytest.raises(ValueError, match="file-input profiles must reference"):
        AgentProfile("coder-no-path", {
            "command": ["some-cli", "run"],
            "input": {"mode": "file"},
        })

    # Case 3: coder with stdin input but no {packet_markdown} in template — rejected
    with pytest.raises(ValueError, match="stdin-input profiles must include"):
        AgentProfile("coder-no-markdown", {
            "command": ["some-cli", "run"],
            "input": {"mode": "stdin", "template": "no packet here"},
        })

    # Case 4: coder with input_mode "none" but disabled=True — allowed (skip validation)
    profile_disabled = AgentProfile("coder-disabled-ok", {
        "disabled": True,
        "command": ["some-cli", "run"],
        "input": {"mode": "none"},
    })
    assert profile_disabled.disabled
    assert profile_disabled.input_mode == "none"  # no validation error


# ─── Test 4: select_executor skips disabled/invalid profiles ────────────────

# START_FUNCTION_CONTRACT
# name: test_select_executor_skips_disabled_invalid_profiles
# purpose: Verify executor selection never returns a disabled profile.
# inputs: None.
# returns: None; asserts selections across roles and attempts.
# side_effects: Resets the profile cache.
# emitted_logs: None.
# error_behavior: Fails when disabled profiles enter runtime routing.
# END_FUNCTION_CONTRACT
def test_select_executor_skips_disabled_invalid_profiles():
    """W09: select_executor must skip disabled profiles and never return them
    as execution candidates."""
    from grace_control.core.executor_selector import select_executor

    reset_cache()
    profiles = load_agent_profiles()

    # Identify all disabled profile IDs
    disabled_ids = [p.executor_id for p in profiles.values() if p.disabled]
    assert len(disabled_ids) > 0, "At least one profile should be disabled for this test"

    # Verify disabled profiles are never selected for any role or attempt
    for role in ("coder", "architect", "verifier", "reviewer", "context_collector"):
        for attempt in range(1, 6):
            result = select_executor(role, attempt=attempt)
            executor_id = result.get("executor_id", "")
            assert executor_id not in disabled_ids, \
                (f"Disabled profile '{executor_id}' was selected for "
                 f"role={role} attempt={attempt}")


# ─── Test 5: Architect profiles use canonical schema ───────────────────────

# START_FUNCTION_CONTRACT
# name: test_architect_profiles_use_canonical_schema
# purpose: Verify architect commands or wrappers expose the canonical packet schema.
# inputs: None.
# returns: None; asserts architect input and schema contracts.
# side_effects: Resets the profile cache.
# emitted_logs: None.
# error_behavior: Fails when architect output fields or packet input are missing.
# END_FUNCTION_CONTRACT
def test_architect_profiles_use_canonical_schema():
    """W09: Architect profiles must use the canonical packet schema in their
    commands, including scope, frozen_scope, acceptance_profile,
    coder_instructions, and expected_evidence."""
    reset_cache()
    profiles = load_agent_profiles()

    architect_profiles = [p for p in profiles.values()
                          if "architect" in p.executor_id.lower() and not p.disabled]
    assert len(architect_profiles) > 0, "No enabled architect profiles found"

    # Canonical schema fields that must appear in architect profile commands
    required_fields = ["scope", "frozen_scope", "acceptance_profile",
                       "coder_instructions", "expected_evidence"]

    for profile in architect_profiles:
        command_text = " ".join(profile.command)
        schema_source = command_text
        if "grace_control.runtime.mini_swe_runner" in command_text:
            from grace_control.runtime.mini_swe_runner import ROLE_CONTRACTS

            schema_source = f"{schema_source}\n{ROLE_CONTRACTS['architect']}"

        for field in required_fields:
            assert field in schema_source, \
                (f"Architect profile '{profile.executor_id}' command must "
                 f"reference canonical schema field '{field}' in its command "
                 "or wrapper role contract")

        # Architect profiles must use file input mode with {packet_path}
        assert profile.input_mode == "file", \
            (f"Architect profile '{profile.executor_id}' must use file input mode, "
             f"got '{profile.input_mode}'")

        assert "{packet_path}" in command_text, \
            (f"Architect profile '{profile.executor_id}' must reference "
             f"{{packet_path}} in command")


# ─── Additional: agent_run_service rejects unresolved placeholders ─────────

# START_FUNCTION_CONTRACT
# name: test_agent_run_service_rejects_unresolved_placeholders
# purpose: Verify unresolved command placeholders fail before subprocess launch.
# inputs: None.
# returns: None; asserts a RuntimeError.
# side_effects: Creates packet input under temporary paths when validation reaches it.
# emitted_logs: None.
# error_behavior: Fails when unresolved placeholders reach runtime execution.
# END_FUNCTION_CONTRACT
def test_agent_run_service_rejects_unresolved_placeholders():
    """W09: AgentRunService.run() must reject commands with unresolved
    template placeholders after rendering — fail-closed, not at runtime."""
    import asyncio
    from grace_control.services.agent_run_service import AgentRunService

    svc = AgentRunService()

    # Create an executor dict with an unresolved placeholder
    executor = {
        "executor_id": "test-unresolved",
        "command": ["echo", "{unknown_var}"],
        "input_mode": "none",
        "input_template": "",
        "model": "test",
        "effort": "medium",
        "cwd": "{worktree_path}",
    }

    with pytest.raises(RuntimeError, match="Unresolved template placeholder"):
        asyncio.run(svc.run(
            executor,
            packet_id="test-pkt",
            worktree_path=Path("/tmp/grace-worktree"),
            state_root=Path("/tmp/grace-state"),
            packet_markdown="test",
        ))


# ─── Additional: agent_run_service rejects cwd escaping worktree ───────────

# START_FUNCTION_CONTRACT
# name: test_agent_run_service_rejects_cwd_escaping_worktree
# purpose: Verify an executor cwd cannot escape its isolated worktree.
# inputs: None.
# returns: None; asserts a RuntimeError.
# side_effects: Creates and removes a temporary worktree directory.
# emitted_logs: None.
# error_behavior: Fails when cwd path escape is accepted.
# END_FUNCTION_CONTRACT
def test_agent_run_service_rejects_cwd_escaping_worktree():
    """W09: AgentRunService.run() must reject a cwd that escapes the
    intended worktree — prevents path-escape attacks."""
    import asyncio
    from grace_control.services.agent_run_service import AgentRunService

    svc = AgentRunService()

    # Create a real worktree directory for the test
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir) / "worktree"
        worktree.mkdir()

        # Create an executor whose cwd resolves outside the worktree
        executor = {
            "executor_id": "test-escape",
            "command": ["echo", "hello"],
            "input_mode": "none",
            "input_template": "",
            "model": "test",
            "effort": "medium",
            "cwd": "/tmp",  # escapes worktree
        }

        with pytest.raises(RuntimeError, match="escapes worktree"):
            asyncio.run(svc.run(
                executor,
                packet_id="test-pkt",
                worktree_path=worktree,
                state_root=Path(tmpdir) / "state",
                packet_markdown="test",
            ))


# ─── Regression: live executor profile cannot select disabled profile ───────

# START_FUNCTION_CONTRACT
# name: test_live_executor_profile_cannot_select_disabled_profile
# purpose: Verify a live profile override cannot enable a disabled executor.
# inputs: None.
# returns: None; asserts a ValueError.
# side_effects: Resets profile cache and patches process environment temporarily.
# emitted_logs: None.
# error_behavior: Fails when a disabled live override is selected.
# END_FUNCTION_CONTRACT
def test_live_executor_profile_cannot_select_disabled_profile():
    """W09 regression: GRACE_LIVE_EXECUTOR_PROFILE must not select a disabled
    profile. Setting GRACE_LIVE_EXECUTOR_PROFILE=opencode (which is disabled)
    must raise ValueError — fail-closed, not silently returned."""
    from grace_control.core.executor_selector import select_executor

    reset_cache()

    with patch.dict("os.environ", {"GRACE_LIVE_EXECUTOR_PROFILE": "opencode"}):
        with pytest.raises(ValueError, match="selects a disabled profile"):
            select_executor("coder")
# END_BLOCK_PROFILE_SAFETY
