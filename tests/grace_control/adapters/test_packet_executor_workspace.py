"""Tests for workspace mode safety (TZ §6.3)."""

from __future__ import annotations

from grace_control.adapters.packet_executor import (
    _BROAD_REPO_VERIFICATION_PATTERNS,
    _verification_unsafe_for_scoped,
)


def test_no_verification_is_safe_for_scoped():
    """Empty verification → scoped_copy is safe."""
    assert _verification_unsafe_for_scoped([], []) is False
    assert _verification_unsafe_for_scoped([], ["any/path.py"]) is False


def test_static_only_verification_is_safe_for_scoped():
    """git status / git diff only — scoped_copy is fine."""
    verification = ["git status --short", "git diff --stat"]
    assert _verification_unsafe_for_scoped(verification, []) is False


def test_pytest_verification_unsafe_for_scoped():
    """pytest in verification → unsafe for scoped_copy."""
    verification = ["python3 -m pytest tests/test_foo.py -q"]
    assert _verification_unsafe_for_scoped(verification, []) is True


def test_pnpm_test_unsafe_for_scoped():
    """pnpm test → unsafe for scoped_copy."""
    verification = ["pnpm test", "pnpm lint"]
    assert _verification_unsafe_for_scoped(verification, []) is True


def test_tsc_unsafe_for_scoped():
    """tsc typecheck → unsafe for scoped_copy."""
    verification = ["npx tsc --noEmit"]
    assert _verification_unsafe_for_scoped(verification, []) is True


def test_pytest_in_substring_caught():
    """Verification contains 'pytest' as substring → caught."""
    verification = ["echo pytest failing tests"]
    assert _verification_unsafe_for_scoped(verification, []) is True


def test_pytest_nested_in_list():
    """Verification is a list of lists (e.g. [[cmd, arg, ...]])."""
    verification = [["python3", "-m", "pytest", "tests/"]]
    assert _verification_unsafe_for_scoped(verification, []) is True


def test_known_patterns_list_is_nonempty():
    """Sanity check: pattern list is populated."""
    assert len(_BROAD_REPO_VERIFICATION_PATTERNS) > 0
    assert "pytest" in _BROAD_REPO_VERIFICATION_PATTERNS
    assert "pnpm test" in _BROAD_REPO_VERIFICATION_PATTERNS
