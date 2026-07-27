from __future__ import annotations

import pytest

from grace_control.runtime.agent_runtime_contract import AgentRuntimeFailureCode
from grace_control.runtime.runtime_scope_enforcer import RuntimeScopeEnforcer


class TestScopeUnit:

    def test_allows_file_inside_directory_scope(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["src/foo/bar.py", "src/foo/baz.py"],
            allowed_scope=["src/foo"],
            frozen_scope=[],
        )
        assert result.ok
        assert result.changed_files == ["src/foo/bar.py", "src/foo/baz.py"]

    def test_allows_exact_file_scope(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["src/foo.py"],
            allowed_scope=["src/foo.py"],
            frozen_scope=[],
        )
        assert result.ok

    def test_allows_evidence_file_matching_glob_scope(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["verification-output/W00-P01-verification.log"],
            allowed_scope=["verification-output/W00*.log"],
            frozen_scope=[],
        )
        assert result.ok

    def test_rejects_out_of_scope_file(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["src/foo/bar.py", "outside/x.py"],
            allowed_scope=["src/foo"],
            frozen_scope=[],
        )
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_CHANGED_OUT_OF_SCOPE
        assert "outside/x.py" in result.out_of_scope_files

    def test_rejects_frozen_scope_file(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["src/foo/bar.py", "docs/frozen/secret.md"],
            allowed_scope=["src/foo", "docs"],
            frozen_scope=["docs/frozen"],
        )
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_TOUCHED_FROZEN_SCOPE
        assert "docs/frozen/secret.md" in result.frozen_touched_files

    def test_rejects_absolute_scope_path(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["/etc/passwd"],
            allowed_scope=["/etc"],
            frozen_scope=[],
        )
        assert not result.ok
        assert result.failure_code is not None

    def test_rejects_dotdot_scope_path(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["../outside/x.py"],
            allowed_scope=["src/foo"],
            frozen_scope=[],
        )
        assert not result.ok
        assert result.failure_code is not None

    def test_normalizes_paths(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["src\\foo\\bar.py", "src/foo/baz.py"],
            allowed_scope=["src/foo"],
            frozen_scope=[],
        )
        assert result.ok

    def test_directory_prefix_does_not_allow_sibling_prefix(self):
        """Allowed scope 'src/foo' must NOT match 'src/foobar/x.py'."""
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["src/foobar/x.py"],
            allowed_scope=["src/foo"],
            frozen_scope=[],
        )
        assert not result.ok, "sibling prefix must be rejected"
        assert "src/foobar/x.py" in result.out_of_scope_files

    def test_file_scope_does_not_allow_neighbor_file(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["src/foo.py"],
            allowed_scope=["src/bar.py"],
            frozen_scope=[],
        )
        assert not result.ok
        assert "src/foo.py" in result.out_of_scope_files

    def test_no_changes_allowed_by_default(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=[],
            allowed_scope=["src/foo"],
            frozen_scope=[],
            fail_on_no_changes=False,
        )
        assert result.ok
        assert result.summary == "No changes produced (allowed by config)"

    def test_no_changes_fails_when_setting_enabled(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=[],
            allowed_scope=["src/foo"],
            frozen_scope=[],
            fail_on_no_changes=True,
        )
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_NO_CHANGES_PRODUCED

    def test_rejects_invalid_allowed_scope_absolute(self):
        """Allowed scope with absolute path must be rejected."""
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["src/foo.py"],
            allowed_scope=["/etc"],
            frozen_scope=[],
        )
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_SCOPE_ENFORCEMENT_FAILED

    def test_rejects_invalid_allowed_scope_dotdot(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["src/foo.py"],
            allowed_scope=["../src"],
            frozen_scope=[],
        )
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_SCOPE_ENFORCEMENT_FAILED

    def test_rejects_invalid_frozen_scope_absolute(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["src/foo.py"],
            allowed_scope=["src"],
            frozen_scope=["/secret"],
        )
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_SCOPE_ENFORCEMENT_FAILED

    def test_rejects_invalid_frozen_scope_dotdot(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["src/foo.py"],
            allowed_scope=["src"],
            frozen_scope=["../secret"],
        )
        assert not result.ok
        assert result.failure_code == AgentRuntimeFailureCode.AGENT_SCOPE_ENFORCEMENT_FAILED

    def test_multiple_out_of_scope_files(self):
        result = RuntimeScopeEnforcer.enforce(
            changed_files=["src/ok.py", "src/bad.py", "other/x.py", "other/y.py"],
            allowed_scope=["src"],
            frozen_scope=[],
        )
        assert not result.ok
        assert len(result.out_of_scope_files) == 2
        assert "other/x.py" in result.out_of_scope_files
        assert "other/y.py" in result.out_of_scope_files
