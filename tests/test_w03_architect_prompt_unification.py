# ############################################################################
# AI_HEADER: test_w03_architect_prompt_unification
# ROLE: W03 regression tests — canonical architect prompt and profile unification.
# ############################################################################

"""W03 Canonical Architect Prompt and Profile Unification.

Tests cover:
1. Architect prompt file exists and loads
2. build_architect_prompt uses canonical prompt
3. Architect profiles match canonical schema
4. Legacy allowed_files schema is rejected or canonicalized
5. Architect output schema required fields
6. Integration: normalize_architect_plan canonicalizes allowed_files → scope
   (and forbidden_files → frozen_scope, write_scope → scope, inputs → coder_instructions)
7. Integration: canonicalization warnings are persisted under _architect_schema_warnings
"""

from __future__ import annotations

import re

import pytest
import yaml

from grace_control.core.prompts import (
    CANONICAL_PACKET_FIELDS,
    REQUIRED_PACKET_FIELDS,
    LEGACY_FIELD_MAP,
    load_architect_prompt,
    canonicalize_packet_fields,
)


# ─── Test 1: Architect prompt file exists and loads ──────────────────────

def test_architect_prompt_file_exists_and_loads():
    """W03: The canonical architect prompt file must exist and be loadable."""
    prompt = load_architect_prompt()
    assert prompt, "Canonical architect prompt is empty"
    assert len(prompt) > 200, "Canonical architect prompt seems too short"
    # Must contain key sections
    assert "Canonical Packet Schema" in prompt, "Missing Canonical Packet Schema section"
    assert "PACKET CONTRACT" in prompt.upper() or "Each packet MUST include" in prompt, \
        "Missing packet contract section"


# ─── Test 2: build_architect_prompt uses canonical prompt ────────────────

def test_build_architect_prompt_uses_canonical_prompt():
    """W03: build_architect_prompt must load and include the canonical prompt.

    We verify by reading the source file directly (to avoid sqlalchemy import)
    and checking that the method calls load_architect_prompt() instead of
    embedding inline prompt rules.
    """
    from pathlib import Path

    # Find the extracted prompt renderer
    svc_path = Path(__file__).resolve().parent.parent / "src" / "grace_control" / "services" / "architect_stage.py"
    source = svc_path.read_text()
    assert "build_architect_prompt" in source, "build_architect_prompt function not found"

    # Must call load_architect_prompt (the canonical source loader)
    assert "load_architect_prompt" in source, \
        "build_architect_prompt does not call load_architect_prompt()"

    # Must NOT embed inline prompt rules/schema — those come from the canonical file
    # Check that the method does not contain the inline rules that were removed
    # We check for specific patterns that existed in the old inline prompt
    method_start = source.find("def build_architect_prompt")
    method_end = source.find("\n    def ", method_start + 1)
    method_source = source[method_start:method_end]

    assert "CRITICAL — verification quoting rules" not in method_source, \
        "build_architect_prompt still embeds verification rules inline (should be in canonical prompt)"
    assert "CRITICAL — frozen_scope rules" not in method_source, \
        "build_architect_prompt still embeds frozen_scope rules inline (should be in canonical prompt)"
    assert "W03: Render the canonical Architect prompt" in method_source, \
        "build_architect_prompt missing its W03 extraction marker"

    # The canonical prompt must contain the full rules
    canonical = load_architect_prompt()
    assert "verification" in canonical.lower(), \
        "Canonical prompt missing verification rules"
    assert "frozen_scope" in canonical.lower(), \
        "Canonical prompt missing frozen_scope rules"


# ─── Test 3: Architect profiles match canonical schema ────────────────────

def test_architect_profiles_match_canonical_schema():
    """W03: Enabled architect profiles must reference the canonical schema
    and not use legacy field names in their PACKET CONTRACT sections."""
    from grace_control.config.agent_profiles import load_agent_profiles
    from pathlib import Path

    profiles = load_agent_profiles()
    architect_profiles = {
        k: v for k, v in profiles.items()
        if "architect" in k.lower()
    }

    assert len(architect_profiles) >= 1, "No architect profiles found"

    for profile_id, profile in architect_profiles.items():
        # Check that the command text references canonical fields
        command_text = " ".join(str(c) for c in profile.command)

        # The current runtime contract passes the canonical packet as a file.
        assert "--task-file" in command_text, \
            f"Architect profile '{profile_id}' does not use the packet-file contract"
        assert "{packet_path}" in command_text, \
            f"Architect profile '{profile_id}' does not pass the packet file"

        # Must NOT use legacy field names as primary
        for legacy_field in LEGACY_FIELD_MAP:
            if legacy_field in command_text:
                # Legacy field mentioned is OK if it's in the "Legacy fields" warning section
                assert "Legacy" in command_text or "canonicalized" in command_text.lower() or "NOT part" in command_text, \
                    f"Architect profile '{profile_id}' uses legacy field '{legacy_field}' without canonicalization warning"


# ─── Test 4: Legacy allowed_files schema rejected or canonicalized ────────

def test_legacy_allowed_files_schema_rejected_or_canonicalized():
    """W03: Legacy fields (allowed_files, forbidden_files, write_scope, inputs)
    must be canonicalized with visible warnings."""
    # Test allowed_files → scope
    packet = {
        "title": "Test packet",
        "role": "coder",
        "allowed_files": ["src/foo.py", "src/bar.py"],
        "description": "Test",
    }
    result, warnings = canonicalize_packet_fields(packet)
    assert "scope" in result, "allowed_files not canonicalized to scope"
    assert result["scope"] == ["src/foo.py", "src/bar.py"], "scope value wrong"
    assert len(warnings) >= 1, "No warning emitted for allowed_files"
    assert "allowed_files" in warnings[0], "Warning doesn't mention allowed_files"
    assert "scope" in warnings[0], "Warning doesn't mention scope"

    # Test forbidden_files → frozen_scope
    packet2 = {
        "title": "Test packet",
        "role": "coder",
        "scope": ["src/foo.py"],
        "forbidden_files": ["docs/archived/"],
        "description": "Test",
    }
    result2, warnings2 = canonicalize_packet_fields(packet2)
    assert "frozen_scope" in result2, "forbidden_files not canonicalized to frozen_scope"
    assert result2["frozen_scope"] == ["docs/archived/"], "frozen_scope value wrong"
    assert any("forbidden_files" in w for w in warnings2), "No warning for forbidden_files"

    # Test write_scope → scope
    packet3 = {
        "title": "Test packet",
        "role": "coder",
        "write_scope": ["src/baz.py"],
        "description": "Test",
    }
    result3, warnings3 = canonicalize_packet_fields(packet3)
    assert "scope" in result3, "write_scope not canonicalized to scope"
    assert result3["scope"] == ["src/baz.py"], "scope value wrong"
    assert any("write_scope" in w for w in warnings3), "No warning for write_scope"

    # Test inputs → coder_instructions
    packet4 = {
        "title": "Test packet",
        "role": "coder",
        "scope": ["src/foo.py"],
        "inputs": ["Read the spec", "Implement the feature"],
        "description": "Test",
    }
    result4, warnings4 = canonicalize_packet_fields(packet4)
    assert "coder_instructions" in result4, "inputs not canonicalized to coder_instructions"
    assert result4["coder_instructions"] == ["Read the spec", "Implement the feature"]
    assert any("inputs" in w for w in warnings4), "No warning for inputs"

    # Test that when both legacy and canonical exist, canonical wins
    packet5 = {
        "title": "Test packet",
        "role": "coder",
        "scope": ["src/canonical.py"],
        "allowed_files": ["src/legacy.py"],
        "description": "Test",
    }
    result5, warnings5 = canonicalize_packet_fields(packet5)
    assert result5["scope"] == ["src/canonical.py"], \
        "Legacy allowed_files overrode canonical scope"
    assert any("ignored" in w.lower() for w in warnings5), \
        "No warning about ignored legacy field when canonical exists"


# ─── Test 5: Architect output schema required fields ──────────────────────

def test_architect_output_schema_required_fields():
    """W03: The canonical prompt must define all required packet fields
    and the CANONICAL_PACKET_FIELDS constant must match."""
    prompt = load_architect_prompt()

    # All REQUIRED_PACKET_FIELDS must be mentioned in the canonical prompt
    for field in REQUIRED_PACKET_FIELDS:
        assert field in prompt, \
            f"Required field '{field}' not mentioned in canonical architect prompt"

    # The canonical prompt must include the table of fields
    assert "title" in prompt
    assert "role" in prompt
    assert "scope" in prompt
    assert "frozen_scope" in prompt
    assert "acceptance_profile" in prompt
    assert "depends_on" in prompt
    assert "conflict_keys" in prompt
    assert "description" in prompt
    assert "coder_instructions" in prompt
    assert "acceptance_criteria" in prompt
    assert "verification" in prompt
    assert "expected_evidence" in prompt

    # CANONICAL_PACKET_FIELDS must include workspace_requirements
    assert "workspace_requirements" in CANONICAL_PACKET_FIELDS, \
        "workspace_requirements missing from CANONICAL_PACKET_FIELDS"

    # Verify legacy field mapping covers all expected legacy fields
    assert "allowed_files" in LEGACY_FIELD_MAP
    assert "forbidden_files" in LEGACY_FIELD_MAP
    assert "write_scope" in LEGACY_FIELD_MAP
    assert "inputs" in LEGACY_FIELD_MAP

    # Legacy fields must NOT be in CANONICAL_PACKET_FIELDS
    for legacy_field in LEGACY_FIELD_MAP:
        assert legacy_field not in CANONICAL_PACKET_FIELDS, \
            f"Legacy field '{legacy_field}' should not be in CANONICAL_PACKET_FIELDS"


def test_architect_prompt_defines_parallel_safety_rules():
    prompt = load_architect_prompt()

    for rule in (
        "same wave = parallel candidates",
        "producer and consumer",
        "overlapping",
        "db-schema",
        "alembic-head",
        "pre-emit",
    ):
        assert rule.lower() in prompt.lower(), f"Missing parallel-safety rule: {rule}"


def test_conflict_keys_are_materialized_and_legacy_packets_default_to_empty():
    from grace_control.services.feature_planning_service import normalize_architect_plan

    plan = normalize_architect_plan({
        "waves": [{"title": "Wave 1", "packets": [{
            "title": "Contract packet",
            "role": "coder",
            "scope": ["src/contract.py"],
            "conflict_keys": [" api:user-service ", "db-schema"],
        }]}],
    }, require_current_contract=True)
    assert plan["waves"][0]["packets"][0]["conflict_keys"] == [
        "api:user-service", "db-schema"
    ]
    assert "_legacy_packet_contract" not in plan

    legacy = normalize_architect_plan({
        "waves": [{"title": "Legacy wave", "packets": [{
            "title": "Legacy packet",
            "role": "coder",
            "scope": ["src/legacy.py"],
        }]}],
    })
    assert legacy["waves"][0]["packets"][0]["conflict_keys"] == []
    assert legacy["_legacy_packet_contract"] is True


# START_FUNCTION_CONTRACT
# name: test_current_architect_packet_without_conflict_keys_is_rejected
# purpose: Ensure current Architect output cannot silently enter legacy mode.
# inputs: None.
# returns: None; asserts missing current-contract metadata is rejected.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails when missing conflict_keys is accepted in strict mode.
# END_FUNCTION_CONTRACT
def test_current_architect_packet_without_conflict_keys_is_rejected():
    from grace_control.services.feature_planning_service import normalize_architect_plan

    with pytest.raises(ValueError, match="requires conflict_keys"):
        normalize_architect_plan({
            "waves": [{"title": "Wave 1", "packets": [{
                "title": "Current packet",
                "role": "coder",
                "scope": ["src/current.py"],
            }]}],
        }, require_current_contract=True)


# START_FUNCTION_CONTRACT
# name: test_current_architect_mixed_conflict_key_presence_is_rejected
# purpose: Ensure every current coder packet supplies conflict_keys.
# inputs: None.
# returns: None; asserts mixed contract presence is rejected.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Fails when a missing packet is defaulted in strict mode.
# END_FUNCTION_CONTRACT
def test_current_architect_mixed_conflict_key_presence_is_rejected():
    from grace_control.services.feature_planning_service import normalize_architect_plan

    with pytest.raises(ValueError, match=r"waves\[0\].packets\[1\]"):
        normalize_architect_plan({
            "waves": [{"title": "Wave 1", "packets": [
                {
                    "title": "Complete packet",
                    "role": "coder",
                    "scope": ["src/complete.py"],
                    "conflict_keys": [],
                },
                {
                    "title": "Incomplete packet",
                    "role": "coder",
                    "scope": ["src/incomplete.py"],
                },
            ]}],
        }, require_current_contract=True)


@pytest.mark.parametrize("conflict_keys", ["api:user-service", [""], ["api", " api "]])
def test_invalid_conflict_keys_are_rejected(conflict_keys):
    from grace_control.services.feature_planning_service import normalize_architect_plan

    with pytest.raises(ValueError, match="conflict_keys"):
        normalize_architect_plan({
            "waves": [{"title": "Wave 1", "packets": [{
                "title": "Invalid packet",
                "role": "coder",
                "scope": ["src/invalid.py"],
                "conflict_keys": conflict_keys,
            }]}],
        })


# ─── Test 6: Integration — allowed_files becomes scope before compiler ────

def test_normalize_architect_plan_canonicalizes_allowed_files_to_scope():
    """W03 integration: A parsed plan with allowed_files on a packet must
    have scope (not allowed_files) after normalize_architect_plan(), before
    the plan compiler runs."""
    from grace_control.services.feature_planning_service import normalize_architect_plan
    from grace_control.core.plan_compiler import PlanCompiler

    raw_plan = {
        "waves": [
            {
                "title": "Wave 1",
                "packets": [
                    {
                        "title": "Implement auth",
                        "role": "coder",
                        "allowed_files": ["src/auth.py", "src/auth_test.py"],
                        "description": "Add auth module",
                        "coder_instructions": ["Write auth code"],
                        "acceptance_criteria": ["Tests pass"],
                        "verification": {"t0": ["run tests"], "t1": [], "t2": []},
                        "expected_evidence": ["test output"],
                    },
                ],
            },
        ],
    }

    normalized = normalize_architect_plan(raw_plan)

    # The packet must now have 'scope' instead of 'allowed_files'
    pkt = normalized["waves"][0]["packets"][0]
    assert "scope" in pkt, "allowed_files was not canonicalized to scope"
    assert pkt["scope"] == ["src/auth.py", "src/auth_test.py"], \
        f"scope value wrong: {pkt['scope']}"
    assert "allowed_files" not in pkt, \
        "allowed_files still present after canonicalization"

    # The plan must pass the compiler without E_CODER_EMPTY_SCOPE
    compiler = PlanCompiler()
    result = compiler.compile_plan(normalized)
    scope_errors = [e for e in result.errors if e.get("code") == "E_CODER_EMPTY_SCOPE"]
    assert not scope_errors, \
        f"Packet with canonicalized scope still gets E_CODER_EMPTY_SCOPE: {scope_errors}"


def test_normalize_architect_plan_canonicalizes_forbidden_files_to_frozen_scope():
    """W03 integration: forbidden_files must become frozen_scope after normalization."""
    from grace_control.services.feature_planning_service import normalize_architect_plan

    raw_plan = {
        "waves": [
            {
                "title": "Wave 1",
                "packets": [
                    {
                        "title": "Fix bug",
                        "role": "coder",
                        "scope": ["src/bug.py"],
                        "forbidden_files": ["docs/", "config/"],
                        "description": "Fix the bug",
                    },
                ],
            },
        ],
    }

    normalized = normalize_architect_plan(raw_plan)
    pkt = normalized["waves"][0]["packets"][0]
    assert "frozen_scope" in pkt, "forbidden_files not canonicalized to frozen_scope"
    assert pkt["frozen_scope"] == ["docs/", "config/"], \
        f"frozen_scope value wrong: {pkt['frozen_scope']}"
    assert "forbidden_files" not in pkt, \
        "forbidden_files still present after canonicalization"


def test_normalize_architect_plan_canonicalizes_write_scope_and_inputs():
    """W03 integration: write_scope → scope and inputs → coder_instructions."""
    from grace_control.services.feature_planning_service import normalize_architect_plan

    raw_plan = {
        "waves": [
            {
                "title": "Wave 1",
                "packets": [
                    {
                        "title": "Refactor module",
                        "role": "coder",
                        "write_scope": ["src/module.py"],
                        "inputs": ["Read existing code first", "Preserve API compatibility"],
                        "description": "Refactor the module",
                    },
                ],
            },
        ],
    }

    normalized = normalize_architect_plan(raw_plan)
    pkt = normalized["waves"][0]["packets"][0]
    assert "scope" in pkt, "write_scope not canonicalized to scope"
    assert pkt["scope"] == ["src/module.py"], f"scope value wrong: {pkt['scope']}"
    assert "coder_instructions" in pkt, "inputs not canonicalized to coder_instructions"
    assert pkt["coder_instructions"] == ["Read existing code first", "Preserve API compatibility"], \
        f"coder_instructions value wrong: {pkt['coder_instructions']}"
    assert "write_scope" not in pkt
    assert "inputs" not in pkt


# ─── Test 7: Integration — warnings are persisted ─────────────────────────

def test_normalize_architect_plan_persists_schema_warnings():
    """W03: Canonicalization warnings must be visible in
    plan['_architect_schema_warnings'] after normalization."""
    from grace_control.services.feature_planning_service import normalize_architect_plan

    raw_plan = {
        "waves": [
            {
                "title": "Wave 1",
                "packets": [
                    {
                        "title": "Packet A",
                        "role": "coder",
                        "allowed_files": ["src/a.py"],
                        "description": "Do A",
                    },
                    {
                        "title": "Packet B",
                        "role": "coder",
                        "scope": ["src/b.py"],
                        "forbidden_files": ["docs/"],
                        "description": "Do B",
                    },
                ],
            },
        ],
    }

    normalized = normalize_architect_plan(raw_plan)

    # Warnings must be persisted under _architect_schema_warnings
    assert "_architect_schema_warnings" in normalized, \
        "No _architect_schema_warnings key in normalized plan"
    warnings = normalized["_architect_schema_warnings"]
    assert len(warnings) >= 2, \
        f"Expected at least 2 warnings, got {len(warnings)}: {warnings}"

    # Warnings must include the packet location prefix
    assert any("waves[0].packets[0]" in w for w in warnings), \
        f"No warning for waves[0].packets[0] in: {warnings}"
    assert any("waves[0].packets[1]" in w for w in warnings), \
        f"No warning for waves[0].packets[1] in: {warnings}"

    # Warning content must mention the legacy and canonical field names
    assert any("allowed_files" in w and "scope" in w for w in warnings), \
        f"No warning mentioning allowed_files→scope in: {warnings}"
    assert any("forbidden_files" in w and "frozen_scope" in w for w in warnings), \
        f"No warning mentioning forbidden_files→frozen_scope in: {warnings}"


def test_normalize_architect_plan_no_warnings_when_canonical():
    """W03: A plan using only canonical fields must NOT have _architect_schema_warnings."""
    from grace_control.services.feature_planning_service import normalize_architect_plan

    raw_plan = {
        "waves": [
            {
                "title": "Wave 1",
                "packets": [
                    {
                        "title": "Packet A",
                        "role": "coder",
                        "scope": ["src/a.py"],
                        "frozen_scope": [],
                        "description": "Do A",
                    },
                ],
            },
        ],
    }

    normalized = normalize_architect_plan(raw_plan)
    assert "_architect_schema_warnings" not in normalized, \
        "Unexpected _architect_schema_warnings when all fields are canonical"
