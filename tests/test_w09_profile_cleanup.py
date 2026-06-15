# ############################################################################
# AI_HEADER: test_w09_profile_cleanup
# ROLE: W09 tests — profile cleanup and agent input validation.
# ############################################################################

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


# ─── Test 1: All enabled coder profiles receive packet input ────────────────

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

        for field in required_fields:
            assert field in command_text, \
                (f"Architect profile '{profile.executor_id}' command must "
                 f"reference canonical schema field '{field}'")

        # Architect profiles must use file input mode with {packet_path}
        assert profile.input_mode == "file", \
            (f"Architect profile '{profile.executor_id}' must use file input mode, "
             f"got '{profile.input_mode}'")

        assert "{packet_path}" in command_text, \
            (f"Architect profile '{profile.executor_id}' must reference "
             f"{{packet_path}} in command")


# ─── Additional: agent_run_service rejects unresolved placeholders ─────────

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
