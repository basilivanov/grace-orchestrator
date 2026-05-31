"""
Tests for sandbox bypass policy enforcement.
"""

import os
import pytest

from prefect_grace.policies.sandbox_policy import (
    SandboxBypassDenied,
    check_sandbox_bypass_allowed,
    require_sandbox_bypass_allowed,
)


class TestCheckSandboxBypassAllowed:
    """Tests for check_sandbox_bypass_allowed function."""

    def test_bypass_denied_by_default(self):
        """Verify bypass is denied by default with no env var or config."""
        allowed, reason = check_sandbox_bypass_allowed(
            packet_id="test-packet",
            reason="test reason",
            project_config=None,
        )
        assert allowed is False
        assert "not allowed" in reason.lower()
        assert "GRACE_ALLOW_SANDBOX_BYPASS" in reason

    def test_bypass_allowed_by_env_var_true(self, monkeypatch):
        """Verify env var GRACE_ALLOW_SANDBOX_BYPASS=true allows bypass."""
        monkeypatch.setenv("GRACE_ALLOW_SANDBOX_BYPASS", "true")
        allowed, reason = check_sandbox_bypass_allowed(
            packet_id="test-packet",
            reason="test reason",
            project_config=None,
        )
        assert allowed is True
        assert "environment variable" in reason.lower()

    def test_bypass_allowed_by_env_var_1(self, monkeypatch):
        """Verify env var GRACE_ALLOW_SANDBOX_BYPASS=1 allows bypass."""
        monkeypatch.setenv("GRACE_ALLOW_SANDBOX_BYPASS", "1")
        allowed, reason = check_sandbox_bypass_allowed(
            packet_id="test-packet",
            reason="test reason",
            project_config=None,
        )
        assert allowed is True
        assert "environment variable" in reason.lower()

    def test_bypass_allowed_by_env_var_yes(self, monkeypatch):
        """Verify env var GRACE_ALLOW_SANDBOX_BYPASS=yes allows bypass."""
        monkeypatch.setenv("GRACE_ALLOW_SANDBOX_BYPASS", "yes")
        allowed, reason = check_sandbox_bypass_allowed(
            packet_id="test-packet",
            reason="test reason",
            project_config=None,
        )
        assert allowed is True
        assert "environment variable" in reason.lower()

    def test_bypass_denied_by_env_var_false(self, monkeypatch):
        """Verify env var GRACE_ALLOW_SANDBOX_BYPASS=false denies bypass."""
        monkeypatch.setenv("GRACE_ALLOW_SANDBOX_BYPASS", "false")
        allowed, reason = check_sandbox_bypass_allowed(
            packet_id="test-packet",
            reason="test reason",
            project_config=None,
        )
        assert allowed is False

    def test_bypass_allowed_by_config(self):
        """Verify config security.allow_sandbox_bypass=true allows bypass."""
        project_config = {
            "security": {
                "allow_sandbox_bypass": True,
            }
        }
        allowed, reason = check_sandbox_bypass_allowed(
            packet_id="test-packet",
            reason="test reason",
            project_config=project_config,
        )
        assert allowed is True
        assert "project config" in reason.lower()

    def test_bypass_denied_by_config_false(self):
        """Verify config security.allow_sandbox_bypass=false denies bypass."""
        project_config = {
            "security": {
                "allow_sandbox_bypass": False,
            }
        }
        allowed, reason = check_sandbox_bypass_allowed(
            packet_id="test-packet",
            reason="test reason",
            project_config=project_config,
        )
        assert allowed is False

    def test_env_var_precedence_over_config(self, monkeypatch):
        """Verify env var takes precedence over config."""
        monkeypatch.setenv("GRACE_ALLOW_SANDBOX_BYPASS", "true")
        project_config = {
            "security": {
                "allow_sandbox_bypass": False,
            }
        }
        allowed, reason = check_sandbox_bypass_allowed(
            packet_id="test-packet",
            reason="test reason",
            project_config=project_config,
        )
        assert allowed is True
        assert "environment variable" in reason.lower()

    def test_bypass_denied_with_empty_security_config(self):
        """Verify bypass denied when security config is empty."""
        project_config = {"security": {}}
        allowed, reason = check_sandbox_bypass_allowed(
            packet_id="test-packet",
            reason="test reason",
            project_config=project_config,
        )
        assert allowed is False

    def test_bypass_denied_with_no_security_config(self):
        """Verify bypass denied when security config is missing."""
        project_config = {"other_field": "value"}
        allowed, reason = check_sandbox_bypass_allowed(
            packet_id="test-packet",
            reason="test reason",
            project_config=project_config,
        )
        assert allowed is False


class TestRequireSandboxBypassAllowed:
    """Tests for require_sandbox_bypass_allowed function."""

    def test_require_bypass_raises_when_denied(self):
        """Verify exception raised when bypass is denied."""
        with pytest.raises(SandboxBypassDenied) as exc_info:
            require_sandbox_bypass_allowed(
                packet_id="test-packet",
                reason="test reason",
                project_config=None,
            )
        assert "denied" in str(exc_info.value).lower()

    def test_require_bypass_succeeds_when_allowed(self, monkeypatch):
        """Verify no exception when bypass is allowed."""
        monkeypatch.setenv("GRACE_ALLOW_SANDBOX_BYPASS", "true")
        # Should not raise
        require_sandbox_bypass_allowed(
            packet_id="test-packet",
            reason="test reason",
            project_config=None,
        )

    def test_require_bypass_succeeds_with_config(self):
        """Verify no exception when bypass allowed by config."""
        project_config = {
            "security": {
                "allow_sandbox_bypass": True,
            }
        }
        # Should not raise
        require_sandbox_bypass_allowed(
            packet_id="test-packet",
            reason="test reason",
            project_config=project_config,
        )
