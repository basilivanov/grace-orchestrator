"""Tests for scope guard."""

from pathlib import Path

import pytest
from grace_control.core.contracts import ScopeViolation
from grace_control.core.scope_guard import ScopeGuard, _match, _matches_any


class TestScopeGuard:
    def _guard(self):
        return ScopeGuard(Path("/tmp/test_repo"))

    def test_exact_allowed_path(self):
        g = self._guard()
        v = g.validate_changed_files(
            changed_files=["src/main.py"],
            allowed_write_scope=["src/main.py"],
            frozen_scope=[],
        )
        assert v == []

    def test_folder_prefix_allowed(self):
        g = self._guard()
        v = g.validate_changed_files(
            changed_files=["src/grace_control/core/contracts.py"],
            allowed_write_scope=["src/grace_control/core/"],
            frozen_scope=[],
        )
        assert v == []

    def test_glob_allowed(self):
        g = self._guard()
        v = g.validate_changed_files(
            changed_files=["src/grace_control/core/contracts.py"],
            allowed_write_scope=["src/grace_control/core/**"],
            frozen_scope=[],
        )
        assert v == []

    def test_out_of_scope(self):
        g = self._guard()
        v = g.validate_changed_files(
            changed_files=["apps/page.tsx"],
            allowed_write_scope=["src/"],
            frozen_scope=[],
        )
        assert len(v) == 1
        assert v[0].violation_type == "out_of_scope"

    def test_frozen_wins_over_allowed(self):
        g = self._guard()
        v = g.validate_changed_files(
            changed_files=["src/legacy.py"],
            allowed_write_scope=["src/**"],
            frozen_scope=["src/legacy.py"],
        )
        assert len(v) == 1
        assert v[0].violation_type == "frozen_scope"

    def test_absolute_path_rejected(self):
        g = self._guard()
        v = g.validate_changed_files(
            changed_files=["/etc/passwd"],
            allowed_write_scope=["src/"],
            frozen_scope=[],
        )
        assert len(v) == 1
        assert v[0].violation_type == "invalid_path"

    def test_parent_traversal_rejected(self):
        g = self._guard()
        v = g.validate_changed_files(
            changed_files=["../secret.py"],
            allowed_write_scope=["src/"],
            frozen_scope=[],
        )
        assert len(v) == 1
        assert v[0].violation_type == "invalid_path"

    def test_empty_allowed_scope(self):
        g = self._guard()
        v = g.validate_changed_files(
            changed_files=["src/main.py"],
            allowed_write_scope=[],
            frozen_scope=[],
        )
        assert len(v) == 1
        assert v[0].violation_type == "missing_allowed_scope"

    def test_no_changed_files(self):
        g = self._guard()
        v = g.validate_changed_files(
            changed_files=[],
            allowed_write_scope=["src/"],
            frozen_scope=[],
        )
        assert v == []

    def test_multiple_violations(self):
        g = self._guard()
        v = g.validate_changed_files(
            changed_files=["src/ok.py", "apps/bad.tsx", "frozen/legacy.py"],
            allowed_write_scope=["src/"],
            frozen_scope=["frozen/legacy.py"],
        )
        assert len(v) == 2  # bad.tsx + frozen/legacy.py


class TestMatch:
    def test_exact_match(self):
        assert _match("src/main.py", "src/main.py") is True

    def test_prefix_match(self):
        assert _match("src/core/contracts.py", "src/core/") is True

    def test_prefix_no_match(self):
        assert _match("other/file.py", "src/core/") is False

    def test_double_star_glob(self):
        assert _match("src/a/b/c.py", "src/**") is True

    def test_simple_glob(self):
        assert _match("src/main.py", "src/*.py") is True

    def test_no_match(self):
        assert _match("other/file.py", "src/*.py") is False
