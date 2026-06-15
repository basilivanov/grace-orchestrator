# ############################################################################
# AI_HEADER: test_w03_architect_prompt_unification
# ROLE: W03 regression tests — canonical architect prompt and profile unification.
# ############################################################################

"""W03 Canonical Architect Prompt and Profile Unification.

Tests cover:
1. Architect prompt file exists and loads
2. _build_architect_prompt uses canonical prompt
3. Architect profiles match canonical schema
4. Legacy allowed_files schema is rejected or canonicalized
5. Architect output schema required fields
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


# ─── Test 2: _build_architect_prompt uses canonical prompt ────────────────

def test_build_architect_prompt_uses_canonical_prompt():
    """W03: _build_architect_prompt must load and include the canonical prompt.

    We verify by reading the source file directly (to avoid sqlalchemy import)
    and checking that the method calls load_architect_prompt() instead of
    embedding inline prompt rules.
    """
    from pathlib import Path

    # Read the source file directly to avoid sqlalchemy import
    svc_path = Path(__file__).resolve().parent.parent / "src" / "grace_control" / "services" / "feature_planning_service.py"
    source = svc_path.read_text()

    # Find the _build_architect_prompt method
    assert "_build_architect_prompt" in source, "_build_architect_prompt method not found"

    # Must call load_architect_prompt (the canonical source loader)
    assert "load_architect_prompt" in source, \
        "_build_architect_prompt does not call load_architect_prompt()"

    # Must NOT embed inline prompt rules/schema — those come from the canonical file
    # Check that the method does not contain the inline rules that were removed
    # We check for specific patterns that existed in the old inline prompt
    method_start = source.find("def _build_architect_prompt")
    method_end = source.find("\n    def ", method_start + 1)
    method_source = source[method_start:method_end]

    assert "CRITICAL — verification quoting rules" not in method_source, \
        "_build_architect_prompt still embeds verification rules inline (should be in canonical prompt)"
    assert "CRITICAL — frozen_scope rules" not in method_source, \
        "_build_architect_prompt still embeds frozen_scope rules inline (should be in canonical prompt)"
    assert "W03: Thin renderer" in method_source, \
        "_build_architect_prompt missing W03 docstring indicating it's a thin renderer"

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

        # Must reference canonical schema
        assert "scope" in command_text.lower(), \
            f"Architect profile '{profile_id}' command does not reference 'scope'"

        # Must reference the canonical prompt file
        assert "architect_prompt.md" in command_text or "canonical" in command_text.lower(), \
            f"Architect profile '{profile_id}' does not reference the canonical prompt source"

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
