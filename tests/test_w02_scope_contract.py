# ############################################################################
# AI_HEADER: test_w02_scope_contract
# ROLE: W02 regression tests — fail-closed plan compiler and scope contract.
# ############################################################################

"""W02 Fail-closed Plan Compiler and Scope Contract.

Tests cover:
1. Plan compiler rejects empty scope for coder packets
2. build_packet_contract does not default empty scope
3. Materializer refuses packet without scope
4. Absolute scope path is error, not silently stripped
5. Scope/frozen overlap is error
6. Architect fallback does not enqueue empty-scope coder packet
7. Plan compiler rejects non-list scope (string, dict, int)
8. Root constraints.frozen_scope overlap with packet scope is error
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from grace_control.core.contracts import (
    AcceptanceProfile,
    ExecutionPacketContract,
    ScopeContractError,
    build_packet_contract,
    validate_packet_contract,
    validate_scope_paths,
)
from grace_control.core.plan_compiler import PlanCompiler
from grace_control.services.packet_materializer import PacketMaterializer


# ─── Test 1: Plan compiler rejects empty scope ────────────────────────────

def test_plan_compiler_rejects_empty_scope():
    """W02: Coder packet with empty scope must be rejected by compiler."""
    plan = {
        "waves": [
            {
                "title": "Test Wave",
                "packets": [
                    {
                        "title": "Empty scope coder",
                        "scope": [],
                        "role": "coder",
                        "description": "Implement something",
                        "verification": {"t0": [], "t1": [], "t2": []},
                        "expected_evidence": [],
                    }
                ],
            }
        ],
    }

    result = PlanCompiler().compile_plan(plan)
    assert not result.ok
    error_codes = [e.code for e in result.errors]
    assert "E_CODER_EMPTY_SCOPE" in error_codes


def test_plan_compiler_rejects_missing_scope():
    """W02: Coder packet with no scope key at all must be rejected."""
    plan = {
        "waves": [
            {
                "title": "Test Wave",
                "packets": [
                    {
                        "title": "No scope coder",
                        # scope key missing entirely
                        "role": "coder",
                        "description": "Implement something",
                        "verification": {"t0": [], "t1": [], "t2": []},
                        "expected_evidence": [],
                    }
                ],
            }
        ],
    }

    result = PlanCompiler().compile_plan(plan)
    assert not result.ok
    error_codes = [e.code for e in result.errors]
    assert "E_CODER_EMPTY_SCOPE" in error_codes


def test_plan_compiler_allows_verifier_empty_scope():
    """W02: Verifier packets are allowed to have empty scope."""
    plan = {
        "waves": [
            {
                "title": "Test Wave",
                "packets": [
                    {
                        "title": "Verification packet",
                        "scope": [],
                        "role": "verifier",
                        "description": "Run tests",
                        "verification": {"t0": [], "t1": [], "t2": []},
                        "expected_evidence": [],
                    }
                ],
            }
        ],
    }

    result = PlanCompiler().compile_plan(plan)
    # Should not have E_CODER_EMPTY_SCOPE for verifier
    error_codes = [e.code for e in result.errors]
    assert "E_CODER_EMPTY_SCOPE" not in error_codes


# ─── Test 2: build_packet_contract does not default empty scope ───────────

def test_build_packet_contract_does_not_default_empty_scope():
    """W02: build_packet_contract must not fallback to src/grace_control/."""
    packet_data = {
        "id": "pkt_test",
        "title": "Test",
        "spec_json": {
            # scope key missing — should NOT default to src/grace_control/
        },
    }

    contract = build_packet_contract(packet_data)
    # Scope should be empty [], NOT ["src/grace_control/"]
    assert contract.allowed_write_scope == []


def test_build_packet_contract_with_explicit_scope():
    """build_packet_contract works when scope is explicitly provided."""
    packet_data = {
        "id": "pkt_test",
        "title": "Test",
        "spec_json": {
            "scope": ["src/grace_control/services/"],
            "frozen_scope": ["docs/archived/"],
        },
    }

    contract = build_packet_contract(packet_data)
    assert contract.allowed_write_scope == ["src/grace_control/services/"]
    assert contract.frozen_scope == ["docs/archived/"]


# ─── Test 3: Materializer refuses packet without scope ────────────────────

def test_materializer_refuses_packet_without_scope(db):
    """W02: PacketMaterializer must raise ValueError when scope is empty."""
    materializer = PacketMaterializer()
    with tempfile.TemporaryDirectory() as tmp:
        packet_data = {
            "id": "pkt_noscope",
            "title": "No Scope",
            "spec_json": {},  # No scope
        }
        with pytest.raises(ValueError, match="no write scope"):
            materializer.materialize(packet_data, Path(tmp))


def test_materializer_materializes_with_scope(db):
    """PacketMaterializer works when scope is explicitly provided."""
    materializer = PacketMaterializer()
    with tempfile.TemporaryDirectory() as tmp:
        packet_data = {
            "id": "pkt_withscope",
            "title": "With Scope",
            "spec_json": {
                "scope": ["src/grace_control/"],
            },
        }
        path = materializer.materialize(packet_data, Path(tmp))
        assert path.exists()
        content = path.read_text()
        assert "src/grace_control/" in content


# ─── Test 4: Absolute scope path is error, not silently stripped ──────────

def test_absolute_scope_path_is_error_not_silently_stripped():
    """W02: Absolute paths in scope must be rejected, not stripped."""

    # Test in plan compiler
    plan = {
        "waves": [
            {
                "title": "Test Wave",
                "packets": [
                    {
                        "title": "Absolute scope",
                        "scope": ["/tmp/grace_worktrees/"],
                        "role": "coder",
                        "description": "Fix something",
                        "verification": {"t0": [], "t1": [], "t2": []},
                        "expected_evidence": [],
                    }
                ],
            }
        ],
    }

    result = PlanCompiler().compile_plan(plan)
    assert not result.ok
    error_codes = [e.code for e in result.errors]
    assert "E_SCOPE_ABSOLUTE_PATH" in error_codes

    # Test in build_packet_contract
    with pytest.raises(ScopeContractError, match="absolute path"):
        build_packet_contract({
            "id": "pkt_test",
            "title": "Test",
            "spec_json": {"scope": ["/absolute/path/"]},
        })

    # Test in validate_scope_paths
    errors = validate_scope_paths(["/absolute/path/"])
    assert any("absolute" in e for e in errors)


def test_parent_path_is_error():
    """W02: Parent paths (..) in scope must be rejected."""

    # Test in plan compiler
    plan = {
        "waves": [
            {
                "title": "Test Wave",
                "packets": [
                    {
                        "title": "Parent path scope",
                        "scope": ["../etc/passwd"],
                        "role": "coder",
                        "description": "Fix something",
                        "verification": {"t0": [], "t1": [], "t2": []},
                        "expected_evidence": [],
                    }
                ],
            }
        ],
    }

    result = PlanCompiler().compile_plan(plan)
    assert not result.ok
    error_codes = [e.code for e in result.errors]
    assert "E_SCOPE_PARENT_PATH" in error_codes


def test_python_import_path_is_error():
    """W02: Python import paths in scope must be rejected."""

    # Test in plan compiler
    plan = {
        "waves": [
            {
                "title": "Test Wave",
                "packets": [
                    {
                        "title": "Import path scope",
                        "scope": ["grace_control.services.packet_service"],
                        "role": "coder",
                        "description": "Fix something",
                        "verification": {"t0": [], "t1": [], "t2": []},
                        "expected_evidence": [],
                    }
                ],
            }
        ],
    }

    result = PlanCompiler().compile_plan(plan)
    assert not result.ok
    error_codes = [e.code for e in result.errors]
    assert "E_SCOPE_PYTHON_IMPORT_PATH" in error_codes


def test_root_files_with_extensions_are_filesystem_scope_paths():
    """Root config/docs are valid paths, not dotted Python imports."""
    errors = validate_scope_paths([
        "AGENTS.md",
        "pyproject.toml",
        "alembic.ini",
        "docker-compose.yml",
    ])
    assert errors == []


def test_actual_python_import_path_is_still_rejected_by_contract():
    errors = validate_scope_paths(["app.services.bidder"])
    assert any("Python import path" in error for error in errors)


# ─── Test 5: Scope/frozen overlap is error ────────────────────────────────

def test_scope_frozen_overlap_is_error():
    """W02: Scope/frozen_scope overlap must be rejected, not silently stripped."""

    # Test in plan compiler
    plan = {
        "waves": [
            {
                "title": "Test Wave",
                "packets": [
                    {
                        "title": "Overlap scope",
                        "scope": ["src/grace_control/services/packet_service.py"],
                        "frozen_scope": ["src/grace_control/services/packet_service.py"],
                        "role": "coder",
                        "description": "Fix something",
                        "verification": {"t0": [], "t1": [], "t2": []},
                        "expected_evidence": [],
                    }
                ],
            }
        ],
    }

    result = PlanCompiler().compile_plan(plan)
    assert not result.ok
    error_codes = [e.code for e in result.errors]
    assert "E_SCOPE_FROZEN_OVERLAP" in error_codes

    # Test in build_packet_contract
    with pytest.raises(ScopeContractError, match="overlap"):
        build_packet_contract({
            "id": "pkt_test",
            "title": "Test",
            "spec_json": {
                "scope": ["src/grace_control/services/"],
                "frozen_scope": ["src/grace_control/services/"],
            },
        })

    # Test in validate_scope_paths
    errors = validate_scope_paths(
        ["src/grace_control/services/"],
        ["src/grace_control/services/"],
    )
    assert any("overlap" in e for e in errors)

    # Test in validate_packet_contract
    contract = ExecutionPacketContract(
        packet_id="pkt_test",
        title="Test",
        allowed_write_scope=["src/grace_control/services/"],
        frozen_scope=["src/grace_control/services/"],
        acceptance_profile=AcceptanceProfile.NORMAL,
    )
    errors = validate_packet_contract(contract)
    assert any("overlap" in e for e in errors)


# ─── Test 6: Architect fallback does not enqueue empty-scope coder packet ─

def test_architect_fallback_does_not_enqueue_empty_scope_packet():
    """W02: _fallback_plan must not create executable coder packets with empty scope."""
    from grace_control.services.feature_planning_service import FeaturePlanningService

    # We can't easily instantiate FeaturePlanningService without a DB,
    # but we can test the _fallback_plan method directly
    # Since it's an instance method, we create a mock-like approach
    class _FakeDB:
        pass

    # _fallback_plan doesn't use self.db, so a minimal stub works
    svc = FeaturePlanningService.__new__(FeaturePlanningService)
    fallback = svc._fallback_plan("feat_test", "test description")

    # The fallback must NOT contain any packets (waves should be empty)
    assert fallback.get("waves") == []
    assert "PLAN_FAILED" in fallback.get("summary", "")

    # If waves existed, verify no coder packets with empty scope
    for wave in fallback.get("waves", []):
        for pkt in wave.get("packets", []):
            role = pkt.get("role", "coder")
            if role == "coder":
                scope = pkt.get("scope", [])
                assert scope, f"Coder packet '{pkt.get('title')}' has empty scope in fallback plan"


# ─── Test 7: Plan compiler rejects string scope ──────────────────────────

def test_plan_compiler_rejects_scope_string():
    """W02: A string scope is truthy but iterates as characters — must be rejected."""
    plan = {
        "waves": [
            {
                "title": "Test Wave",
                "packets": [
                    {
                        "title": "String scope coder",
                        "scope": "src/grace_control/services/",
                        "role": "coder",
                        "description": "Implement something",
                        "verification": {"t0": [], "t1": [], "t2": []},
                        "expected_evidence": [],
                    }
                ],
            }
        ],
    }

    result = PlanCompiler().compile_plan(plan)
    assert not result.ok
    error_codes = [e.code for e in result.errors]
    assert "E_SCOPE_NOT_LIST" in error_codes
    # Must NOT produce per-character path errors — the type error is sufficient
    per_char_errors = [e for e in result.errors if e.code in (
        "E_SCOPE_ABSOLUTE_PATH", "E_SCOPE_PYTHON_IMPORT_PATH", "E_SCOPE_PARENT_PATH",
    )]
    assert len(per_char_errors) == 0, (
        f"String scope should be rejected as type error, not iterated as characters; "
        f"got per-character errors: {[e.message for e in per_char_errors]}"
    )


def test_plan_compiler_rejects_scope_dict():
    """W02: A dict scope must be rejected with E_SCOPE_NOT_LIST."""
    plan = {
        "waves": [
            {
                "title": "Test Wave",
                "packets": [
                    {
                        "title": "Dict scope coder",
                        "scope": {"path": "src/grace_control/"},
                        "role": "coder",
                        "description": "Implement something",
                        "verification": {"t0": [], "t1": [], "t2": []},
                        "expected_evidence": [],
                    }
                ],
            }
        ],
    }

    result = PlanCompiler().compile_plan(plan)
    assert not result.ok
    error_codes = [e.code for e in result.errors]
    assert "E_SCOPE_NOT_LIST" in error_codes


def test_plan_compiler_rejects_scope_int():
    """W02: An int scope must be rejected with E_SCOPE_NOT_LIST."""
    plan = {
        "waves": [
            {
                "title": "Test Wave",
                "packets": [
                    {
                        "title": "Int scope coder",
                        "scope": 42,
                        "role": "coder",
                        "description": "Implement something",
                        "verification": {"t0": [], "t1": [], "t2": []},
                        "expected_evidence": [],
                    }
                ],
            }
        ],
    }

    result = PlanCompiler().compile_plan(plan)
    assert not result.ok
    error_codes = [e.code for e in result.errors]
    assert "E_SCOPE_NOT_LIST" in error_codes


# ─── Test 8: Root constraints frozen_scope overlap ────────────────────────

def test_plan_compiler_rejects_root_constraints_scope_overlap():
    """W02: Packet scope overlapping root constraints.frozen_scope must be rejected.

    Root constraints.frozen_scope is applied during materialization AFTER compiler
    validation. Without this check, a packet with scope overlapping root frozen_scope
    would silently become a READY packet that violates the scope contract.
    """
    plan = {
        "constraints": {
            "frozen_scope": ["src/grace_control/services/"],
        },
        "waves": [
            {
                "title": "Test Wave",
                "packets": [
                    {
                        "title": "Overlap with root frozen",
                        "scope": ["src/grace_control/services/"],
                        "role": "coder",
                        "description": "Implement something",
                        "verification": {"t0": [], "t1": [], "t2": []},
                        "expected_evidence": [],
                    }
                ],
            }
        ],
    }

    result = PlanCompiler().compile_plan(plan)
    assert not result.ok
    error_codes = [e.code for e in result.errors]
    assert "E_ROOT_FROZEN_SCOPE_OVERLAP" in error_codes


def test_plan_compiler_allows_non_overlapping_root_frozen():
    """W02: Packet scope that does NOT overlap root constraints.frozen_scope is OK."""
    plan = {
        "constraints": {
            "frozen_scope": ["docs/archived/"],
        },
        "waves": [
            {
                "title": "Test Wave",
                "packets": [
                    {
                        "title": "No overlap with root frozen",
                        "scope": ["src/grace_control/services/"],
                        "role": "coder",
                        "description": "Implement something",
                        "verification": {"t0": [], "t1": [], "t2": []},
                        "expected_evidence": [],
                    }
                ],
            }
        ],
    }

    result = PlanCompiler().compile_plan(plan)
    assert result.ok
