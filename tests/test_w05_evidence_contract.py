# ############################################################################
# AI_HEADER: test_w05_evidence_contract
# ROLE: W05 regression tests — evidence contract end-to-end.
# ############################################################################

"""W05 Evidence Contract End-to-End.

Tests cover:
1. Evidence requirement preserves all fields
2. Materializer renders structured evidence
3. String evidence gets warning or rejected for STRICT
4. Missing coder-blocking evidence rework to coder
5. Architect-owned evidence issue returns to architect
6. Artifact patterns replace legacy pattern
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from grace_control.core.contracts import (
    AcceptanceProfile,
    EvidenceRequirement,
    ExecutionPacketContract,
    build_packet_contract,
    validate_evidence_for_profile,
    route_missing_evidence,
    check_artifact_patterns,
)
from grace_control.services.packet_materializer import PacketMaterializer


# ─── Test 1: Evidence requirement preserves all fields ─────────────────────

def test_evidence_requirement_preserves_all_fields():
    """W05: EvidenceRequirement must preserve all 11 required fields from
    the W05 spec: id, kind, stage, owner, producer, profile, required,
    coder_blocking, artifact_patterns, description, validation_hint."""
    req = EvidenceRequirement(
        id="EV-001",
        kind="file",
        stage="t1",
        owner="coder",
        producer="coder_run",
        profile="NORMAL",
        required=True,
        coder_blocking=True,
        artifact_patterns=["src/auth.py", "tests/test_auth.py"],
        description="Auth module with login/logout",
        validation_hint="Check that login returns a session token",
    )

    assert req.id == "EV-001"
    assert req.kind == "file"
    assert req.stage == "t1"
    assert req.owner == "coder"
    assert req.producer == "coder_run"
    assert req.profile == "NORMAL"
    assert req.required is True
    assert req.coder_blocking is True
    assert req.artifact_patterns == ["src/auth.py", "tests/test_auth.py"]
    assert req.description == "Auth module with login/logout"
    assert req.validation_hint == "Check that login returns a session token"


def test_evidence_requirement_defaults():
    """W05: EvidenceRequirement defaults should be sensible."""
    req = EvidenceRequirement(id="EV-002", kind="command")

    assert req.stage == ""
    assert req.owner == "coder"
    assert req.producer == ""
    assert req.profile == ""
    assert req.required is True
    assert req.coder_blocking is True
    assert req.artifact_patterns == []
    assert req.description == ""
    assert req.validation_hint == ""
    assert req.pattern is None  # Legacy field


def test_build_packet_contract_preserves_all_evidence_fields():
    """W05: build_packet_contract must preserve all evidence fields from dict."""
    packet_data = {
        "id": "pkt-001",
        "title": "Implement auth",
        "acceptance_profile": "NORMAL",
        "spec_json": {
            "scope": ["src/auth.py"],
            "frozen_scope": [],
            "expected_evidence": [
                {
                    "id": "EV-001",
                    "kind": "file",
                    "stage": "t1",
                    "owner": "coder",
                    "producer": "coder_run",
                    "profile": "NORMAL",
                    "required": True,
                    "coder_blocking": True,
                    "artifact_patterns": ["src/auth.py"],
                    "description": "Auth module implementation",
                    "validation_hint": "Check session token returned",
                },
            ],
            "verification": {"t0": [], "t1": [], "t2": []},
        },
    }

    contract = build_packet_contract(packet_data)

    assert len(contract.expected_evidence) == 1
    ev = contract.expected_evidence[0]
    assert ev.id == "EV-001"
    assert ev.kind == "file"
    assert ev.stage == "t1"
    assert ev.owner == "coder"
    assert ev.producer == "coder_run"
    assert ev.profile == "NORMAL"
    assert ev.required is True
    assert ev.coder_blocking is True
    assert ev.artifact_patterns == ["src/auth.py"]
    assert ev.description == "Auth module implementation"
    assert ev.validation_hint == "Check session token returned"


# ─── Test 2: Materializer renders structured evidence ──────────────────────

def test_materializer_renders_structured_evidence():
    """W05: PacketMaterializer must render full structured evidence fields
    in EXECUTION_PACKET.md, not only IDs."""
    materializer = PacketMaterializer()

    with tempfile.TemporaryDirectory() as tmpdir:
        state_root = Path(tmpdir)
        packet_data = {
            "id": "pkt-002",
            "title": "Add logging",
            "spec_json": {
                "scope": ["src/log.py"],
                "frozen_scope": [],
                "expected_evidence": [
                    {
                        "id": "EV-LOG",
                        "kind": "file",
                        "stage": "t1",
                        "owner": "coder",
                        "producer": "coder_run",
                        "profile": "NORMAL",
                        "required": True,
                        "coder_blocking": True,
                        "artifact_patterns": ["src/log.py"],
                        "description": "Logging module",
                        "validation_hint": "Check log levels work",
                    },
                ],
                "verification": {"t0": [], "t1": [], "t2": []},
            },
        }

        path = materializer.materialize(packet_data, state_root)
        content = path.read_text()

        # Must contain evidence fields, not just the ID
        assert "EV-LOG" in content, "Evidence ID not in packet"
        assert "kind: file" in content, "Evidence kind not rendered"
        assert "stage: t1" in content, "Evidence stage not rendered"
        assert "owner: coder" in content, "Evidence owner not rendered"
        assert "artifact_patterns" in content, "artifact_patterns not rendered"
        assert "description: Logging module" in content, "description not rendered"
        assert "validation_hint" in content, "validation_hint not rendered"
        assert "coder_blocking" in content, "coder_blocking not rendered"


# ─── Test 3: String evidence gets warning or rejected for STRICT ───────────

def test_string_evidence_gets_warning_or_rejected_for_strict():
    """W05: String evidence must get a warning in transition mode (NORMAL)
    and be rejected in STRICT mode."""
    # NORMAL profile: string evidence gets a warning
    packet_data_normal = {
        "id": "pkt-003",
        "title": "Test string evidence",
        "acceptance_profile": "NORMAL",
        "spec_json": {
            "scope": ["src/foo.py"],
            "frozen_scope": [],
            "expected_evidence": ["just_a_string_id"],
            "verification": {"t0": [], "t1": [], "t2": []},
        },
    }

    contract_normal = build_packet_contract(packet_data_normal)

    # Evidence is created (transition mode)
    assert len(contract_normal.expected_evidence) == 1
    ev = contract_normal.expected_evidence[0]
    assert ev.id == "just_a_string_id"

    # Warning is persisted in metadata
    warnings = contract_normal.metadata.get("_evidence_schema_warnings", [])
    assert len(warnings) >= 1, f"Expected warning for string evidence, got: {warnings}"
    assert any("string evidence" in w.lower() or "legacy shape" in w.lower() for w in warnings), \
        f"No string evidence warning in: {warnings}"

    # NORMAL: validate_evidence_for_profile should NOT reject string evidence
    errors_normal = validate_evidence_for_profile(
        contract_normal.expected_evidence, AcceptanceProfile.NORMAL
    )
    # In NORMAL, string evidence gets a warning but no errors
    # (it's transition mode)
    assert not errors_normal, f"NORMAL should not reject string evidence: {errors_normal}"

    # STRICT profile: string evidence is rejected
    packet_data_strict = {
        "id": "pkt-003s",
        "title": "Test string evidence strict",
        "acceptance_profile": "STRICT",
        "spec_json": {
            "scope": ["src/foo.py"],
            "frozen_scope": [],
            "expected_evidence": ["just_a_string_id"],
            "verification": {"t0": [], "t1": [], "t2": []},
        },
    }

    contract_strict = build_packet_contract(packet_data_strict)
    errors_strict = validate_evidence_for_profile(
        contract_strict.expected_evidence, AcceptanceProfile.STRICT
    )
    assert len(errors_strict) >= 1, \
        f"STRICT should reject string evidence: {errors_strict}"
    assert any("rejected" in e.lower() or "STRICT" in e for e in errors_strict), \
        f"STRICT rejection message missing: {errors_strict}"


# ─── Test 4: Missing coder-blocking evidence rework to coder ───────────────

def test_missing_coder_blocking_evidence_rework_to_coder():
    """W05: Missing coder-owned blocking evidence must route to coder rework."""
    evidence_reqs = [
        EvidenceRequirement(
            id="EV-CODER-BLOCK",
            kind="file", owner="coder", coder_blocking=True,
            description="Must have this file",
        ),
        EvidenceRequirement(
            id="EV-CODER-NONBLOCK",
            kind="log", owner="coder", coder_blocking=False,
            description="Nice to have log",
        ),
        EvidenceRequirement(
            id="EV-VERIFIER",
            kind="diff", owner="verifier", coder_blocking=False,
            description="Verifier check",
        ),
    ]

    # Missing coder-blocking evidence → route to coder
    route = route_missing_evidence(["EV-CODER-BLOCK"], evidence_reqs)
    assert route == "coder", \
        f"Missing coder-blocking evidence should route to coder, got: {route}"

    # Missing only non-blocking coder evidence → not coder rework (falls to verifier)
    route2 = route_missing_evidence(["EV-CODER-NONBLOCK", "EV-VERIFIER"], evidence_reqs)
    assert route2 == "verifier", \
        f"Missing only non-blocking coder + verifier evidence should route to verifier, got: {route2}"

    # Missing nothing → default coder
    route3 = route_missing_evidence([], evidence_reqs)
    assert route3 == "coder", \
        f"Default fallback should be coder, got: {route3}"


# ─── Test 5: Architect-owned evidence issue returns to architect ───────────

def test_architect_owned_evidence_issue_returns_to_architect():
    """W05: Architect-owned evidence issue must NOT become coder blame —
    route to architect instead."""
    evidence_reqs = [
        EvidenceRequirement(
            id="EV-ARCH",
            kind="spec", owner="architect", coder_blocking=False,
            description="Architect must provide spec",
        ),
        EvidenceRequirement(
            id="EV-CODER",
            kind="file", owner="coder", coder_blocking=True,
            description="Coder produces file",
        ),
        EvidenceRequirement(
            id="EV-VERIFIER",
            kind="diff", owner="verifier", coder_blocking=False,
            description="Verifier check",
        ),
    ]

    # Missing architect-owned evidence → route to architect (not coder!)
    route = route_missing_evidence(["EV-ARCH"], evidence_reqs)
    assert route == "architect", \
        f"Missing architect-owned evidence should route to architect, got: {route}"

    # Missing both architect and coder evidence → architect takes priority
    route2 = route_missing_evidence(["EV-ARCH", "EV-CODER"], evidence_reqs)
    assert route2 == "architect", \
        f"Architect-owned evidence should take priority over coder, got: {route2}"

    # Missing only verifier evidence → route to verifier
    route3 = route_missing_evidence(["EV-VERIFIER"], evidence_reqs)
    assert route3 == "verifier", \
        f"Missing verifier-only evidence should route to verifier, got: {route3}"


# ─── Test 6: Artifact patterns replace legacy pattern ──────────────────────

def test_artifact_patterns_replace_legacy_pattern():
    """W05: Legacy 'pattern' must be mapped to 'artifact_patterns' with
    visible warning. 'artifact_patterns' should be the canonical field."""

    # Test: legacy 'pattern' → 'artifact_patterns' with warning
    packet_data = {
        "id": "pkt-006",
        "title": "Pattern migration",
        "acceptance_profile": "NORMAL",
        "spec_json": {
            "scope": ["src/mod.py"],
            "frozen_scope": [],
            "expected_evidence": [
                {
                    "id": "EV-PAT",
                    "kind": "file",
                    "pattern": "src/mod.py",  # Legacy field
                    "description": "Module file",
                },
            ],
            "verification": {"t0": [], "t1": [], "t2": []},
        },
    }

    contract = build_packet_contract(packet_data)

    assert len(contract.expected_evidence) == 1
    ev = contract.expected_evidence[0]

    # artifact_patterns must contain the mapped pattern
    assert ev.artifact_patterns == ["src/mod.py"], \
        f"artifact_patterns wrong: {ev.artifact_patterns}"

    # Warning must be persisted
    warnings = contract.metadata.get("_evidence_schema_warnings", [])
    assert any("pattern" in w and "artifact_patterns" in w for w in warnings), \
        f"No pattern→artifact_patterns warning in: {warnings}"

    # STRICT: legacy pattern without artifact_patterns should be rejected
    packet_data_strict = {
        "id": "pkt-006s",
        "title": "Pattern strict",
        "acceptance_profile": "STRICT",
        "spec_json": {
            "scope": ["src/mod.py"],
            "frozen_scope": [],
            "expected_evidence": [
                {
                    "id": "EV-PAT-STRICT",
                    "kind": "file",
                    "pattern": "src/mod.py",  # Legacy field still present
                    "description": "Module file",
                },
            ],
            "verification": {"t0": [], "t1": [], "t2": []},
        },
    }

    contract_strict = build_packet_contract(packet_data_strict)
    # The build maps pattern to artifact_patterns, so STRICT won't reject
    # the mapped value. But if pattern exists alongside empty artifact_patterns,
    # STRICT should reject the bare legacy field.
    # Create a synthetic evidence with pattern but no artifact_patterns
    ev_legacy = EvidenceRequirement(
        id="EV-LEGACY",
        kind="file",
        pattern="src/legacy.py",
        artifact_patterns=[],  # Not populated from legacy
        description="Legacy evidence",
    )
    errors = validate_evidence_for_profile([ev_legacy], AcceptanceProfile.STRICT)
    assert any("pattern" in e and "artifact_patterns" in e for e in errors), \
        f"STRICT should reject bare legacy pattern: {errors}"


def test_artifact_pattern_check_matches_files():
    """W05: check_artifact_patterns must verify artifact patterns against
    available artifacts by evidence kind."""
    evidence_reqs = [
        EvidenceRequirement(
            id="EV-FILE",
            kind="file",
            artifact_patterns=["src/auth.py", "tests/test_auth.py"],
            description="Auth files",
        ),
        EvidenceRequirement(
            id="EV-LOG",
            kind="log",
            artifact_patterns=["logs/*.log"],
            description="Log files",
        ),
        EvidenceRequirement(
            id="EV-NO-PAT",
            kind="command",
            artifact_patterns=[],
            description="No pattern needed",
        ),
    ]

    # All patterns match
    artifacts = [
        "src/auth.py",
        "tests/test_auth.py",
        "logs/run.log",
        "logs/error.log",
    ]
    warnings = check_artifact_patterns(evidence_reqs, artifacts)
    assert not warnings, f"Expected no warnings when all patterns match: {warnings}"

    # Some patterns don't match
    artifacts_partial = ["src/auth.py"]  # Missing test_auth.py and logs/
    warnings2 = check_artifact_patterns(evidence_reqs, artifacts_partial)
    assert len(warnings2) >= 2, f"Expected warnings for unmatched patterns: {warnings2}"
    assert any("test_auth.py" in w for w in warnings2), \
        f"Missing warning for test_auth.py pattern: {warnings2}"
    assert any("logs/*.log" in w for w in warnings2), \
        f"Missing warning for logs pattern: {warnings2}"

    # kind is mentioned in warnings
    assert any("kind=" in w for w in warnings2), \
        f"Warnings should mention evidence kind: {warnings2}"

    # No pattern requirements produce no warnings
    warnings3 = check_artifact_patterns([evidence_reqs[2]], artifacts)
    assert not warnings3
